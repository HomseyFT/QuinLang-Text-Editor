from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from . import ast as A
from .compiler_types import (
    Type, Int, Str, Void, Bool, Ptr, type_from_name, is_array_type, UnknownTypeError,
)
from .builtins import get_builtins, BuiltinSig

class SemanticError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col

    def __str__(self) -> str:
        if self.line or self.col:
            return f"[{self.line}:{self.col}] {self.message}"
        return self.message

@dataclass
class Symbol:
    name: str
    type: Type

@dataclass
class FunctionSig:
    name: str
    params: List[Type]
    ret: Type

class Scope:
    def __init__(self, parent: Optional[Scope] = None):
        self.parent = parent
        self.vars: Dict[str, Symbol] = {}

    def define(self, sym: Symbol, line: int = 0, col: int = 0):
        if sym.name in self.vars:
            raise SemanticError(f"Redeclaration of variable '{sym.name}'", line, col)
        self.vars[sym.name] = sym

    def resolve(self, name: str) -> Optional[Symbol]:
        scope: Optional[Scope] = self
        while scope is not None:
            if name in scope.vars:
                return scope.vars[name]
            scope = scope.parent
        return None

class Context:
    def __init__(self):
        self.functions: Dict[str, FunctionSig] = {}
        self.node_type: Dict[int, Type] = {}

    def set_type(self, node: A.Expr, t: Type):
        self.node_type[id(node)] = t

    def get_type(self, node: A.Expr) -> Type:
        return self.node_type[id(node)]

class SemanticAnalyzer:
    def __init__(self):
        self.ctx = Context()

    def _resolve_type(self, name: str, line: int, col: int) -> Type:
        """Map a source-level type name onto a concrete Type, with location on failure."""
        try:
            return type_from_name(name)
        except UnknownTypeError as e:
            raise SemanticError(str(e), line, col)

    def analyze(self, program: A.Program) -> Context:
        # Register builtin functions first
        for name, (param_names, ret_name) in get_builtins().items():
            if name in self.ctx.functions:
                continue
            param_types = [type_from_name(tn) for tn in param_names]
            ret_type = type_from_name(ret_name)
            self.ctx.functions[name] = FunctionSig(name, param_types, ret_type)

        # First pass: collect user-defined function signatures
        for fn in program.functions:
            param_types: List[Type] = []
            for p in fn.params:
                pt = self._resolve_type(p.type_name, p.line, p.col)
                if is_array_type(pt):
                    raise SemanticError(
                        f"Array types are not supported for parameters (parameter '{p.name}'); "
                        f"arrays are local to the function that declares them",
                        p.line, p.col,
                    )
                param_types.append(pt)
            ret_type = self._resolve_type(fn.return_type, fn.line, fn.col) if fn.return_type else Void
            if is_array_type(ret_type):
                raise SemanticError(f"Function '{fn.name}' cannot return an array type", fn.line, fn.col)
            if fn.name in self.ctx.functions:
                raise SemanticError(f"Redefinition of function '{fn.name}'", fn.line, fn.col)
            self.ctx.functions[fn.name] = FunctionSig(fn.name, param_types, ret_type)

        self._check_entry_point(program)

        # Second pass: analyze function bodies
        for fn in program.functions:
            self._analyze_function(fn)
        return self.ctx

    def _check_entry_point(self, program: A.Program):
        sig = self.ctx.functions.get('main')
        if sig is None:
            raise SemanticError("Missing entry point 'main'")
        node = next((f for f in program.functions if f.name == 'main'), None)
        line = node.line if node else 0
        col = node.col if node else 0
        if sig.params:
            raise SemanticError("Entry point 'main' must not take parameters", line, col)
        if sig.ret not in (Int, Void):
            raise SemanticError(
                f"Entry point 'main' must return int or void, got {sig.ret}", line, col
            )

    def _analyze_function(self, fn: A.Function):
        sig = self.ctx.functions[fn.name]
        scope = Scope()
        for p, t in zip(fn.params, sig.params):
            scope.define(Symbol(p.name, t), p.line, p.col)
        # Check if function body always returns
        always_returns = any(self._always_returns(st, scope, sig.ret) for st in fn.body)
        for st in fn.body:
            self._analyze_stmt(st, scope, sig.ret)
        if sig.ret != Void and not always_returns:
            raise SemanticError(f"Function '{fn.name}' missing return statement", fn.line, fn.col)

    def _analyze_stmt(self, st: A.Stmt, scope: Scope, ret_type: Type = Void):
        if isinstance(st, A.VarDecl):
            var_type = self._resolve_type(st.type_name, st.line, st.col) if st.type_name else None
            if st.init is not None:
                init_t = self._analyze_expr(st.init, scope)
                if var_type is None:
                    var_type = init_t
                elif var_type != init_t:
                    raise SemanticError(f"Type mismatch in initializer for '{st.name}': {var_type} vs {init_t}", st.line, st.col)
                # Arrays have no value form: there is no array literal and
                # copying one would need a slot-wise copy the backend can't express.
                if is_array_type(var_type):
                    raise SemanticError(
                        f"Array variable '{st.name}' cannot have an initializer; "
                        f"arrays are zeroed at declaration and filled element by element",
                        st.line, st.col,
                    )
            if var_type is None:
                raise SemanticError(f"Cannot infer type for '{st.name}' without initializer", st.line, st.col)
            scope.define(Symbol(st.name, var_type), st.line, st.col)
        elif isinstance(st, A.Assign):
            # Generalized assignment target
            if isinstance(st.target, A.Identifier):
                sym = scope.resolve(st.target.name)
                if sym is None:
                    raise SemanticError(f"Undeclared variable '{st.target.name}'", st.target.line, st.target.col)
                if is_array_type(sym.type):
                    raise SemanticError(
                        f"Cannot assign to array variable '{st.target.name}' as a whole; "
                        f"assign to its elements instead",
                        st.target.line, st.target.col,
                    )
                val_t = self._analyze_expr(st.value, scope)
                if sym.type != val_t:
                    raise SemanticError(f"Cannot assign {val_t} to {sym.type} variable '{st.target.name}'", st.target.line, st.target.col)
            elif isinstance(st.target, A.Index):
                arr_t = self._analyze_expr(st.target.array, scope)
                if not is_array_type(arr_t):
                    raise SemanticError("Index target must be an int[N] array", st.target.line, st.target.col)
                idx_t = self._analyze_expr(st.target.index, scope)
                if idx_t != Int:
                    raise SemanticError("Array index must be int", st.target.line, st.target.col)
                val_t = self._analyze_expr(st.value, scope)
                if val_t != Int:
                    raise SemanticError("Array elements must be int", st.line, st.col)
            else:
                raise SemanticError("Invalid assignment target", st.line, st.col)
        elif isinstance(st, A.Print) or isinstance(st, A.PrintLn):
            val_t = self._analyze_expr(st.value, scope)
            # bool prints as "true"/"false"; the VM backend lowers it via a
            # branch into the string table.
            if val_t not in (Int, Str, Bool):
                raise SemanticError(
                    f"print/println expect int, str, or bool, got {val_t}", st.line, st.col
                )
        elif isinstance(st, A.Return):
            if ret_type == Void and st.value is not None:
                raise SemanticError("Void function cannot return a value", st.line, st.col)
            if ret_type != Void and st.value is None:
                raise SemanticError(f"Expected return value of type {ret_type}", st.line, st.col)
            if st.value is not None:
                val_t = self._analyze_expr(st.value, scope)
                if val_t != ret_type:
                    raise SemanticError(f"Return type mismatch: expected {ret_type}, got {val_t}", st.line, st.col)
        elif isinstance(st, A.If):
            cond_t = self._analyze_expr(st.cond, scope)
            if cond_t != Bool:
                raise SemanticError("If condition must be bool", st.line, st.col)
            then_scope = Scope(scope)
            for s in st.then_block:
                self._analyze_stmt(s, then_scope, ret_type)
            if st.else_block:
                else_scope = Scope(scope)
                for s in st.else_block:
                    self._analyze_stmt(s, else_scope, ret_type)
        elif isinstance(st, A.While):
            cond_t = self._analyze_expr(st.cond, scope)
            if cond_t != Bool:
                raise SemanticError("While condition must be bool", st.line, st.col)
            body_scope = Scope(scope)
            for s in st.body:
                self._analyze_stmt(s, body_scope, ret_type)
        elif isinstance(st, A.ExprStmt):
            self._analyze_expr(st.expr, scope)
        else:
            # Ignore blocks etc.
            pass

    def _always_returns(self, st: A.Stmt, scope: Scope, ret_type: Type) -> bool:
        """Return True if statement always returns (i.e., execution cannot continue past it)."""
        if isinstance(st, A.Return):
            return True
        if isinstance(st, A.Block):
            # A block always returns if any statement in it always returns
            for s in st.stmts:
                if self._always_returns(s, scope, ret_type):
                    return True
            return False
        if isinstance(st, A.If):
            # If with both branches: returns only if both branches always return
            then_always = any(self._always_returns(s, scope, ret_type) for s in st.then_block)
            if st.else_block:
                else_always = any(self._always_returns(s, scope, ret_type) for s in st.else_block)
                return then_always and else_always
            else:
                # No else branch: not guaranteed
                return False
        if isinstance(st, A.While):
            # While loop may not execute, so never guaranteed
            return False
        # All other statements (VarDecl, Assign, ExprStmt, Print, PrintLn, etc.) do not guarantee return
        return False

    def _analyze_expr(self, e: A.Expr, scope: Scope) -> Type:
        if isinstance(e, A.Literal):
            if isinstance(e.value, bool):
                self.ctx.set_type(e, Bool)
                return Bool
            if isinstance(e.value, int):
                self.ctx.set_type(e, Int)
                return Int
            if isinstance(e.value, str):
                self.ctx.set_type(e, Str)
                return Str
            self.ctx.set_type(e, Void)
            return Void
        if isinstance(e, A.Identifier):
            sym = scope.resolve(e.name)
            if sym is None:
                raise SemanticError(f"Undeclared variable '{e.name}'", e.line, e.col)
            self.ctx.set_type(e, sym.type)
            return sym.type
        if isinstance(e, A.Unary):
            t = self._analyze_expr(e.right, scope)
            if e.op == '-' and t == Int:
                self.ctx.set_type(e, Int)
                return Int
            if e.op == '!' and t == Bool:
                self.ctx.set_type(e, Bool)
                return Bool
            raise SemanticError(f"Invalid unary op {e.op} for type {t}", e.line, e.col)
        if isinstance(e, A.Binary):
            lt = self._analyze_expr(e.left, scope)
            rt = self._analyze_expr(e.right, scope)
            if e.op in ('+', '-', '*', '/'):
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                raise SemanticError("Arithmetic operators require int operands", e.line, e.col)
            if e.op == '%':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                raise SemanticError("Modulo operator requires int operands", e.line, e.col)
            if e.op in ('==', '!=', '<', '<=', '>', '>='):
                if lt == rt:
                    self.ctx.set_type(e, Bool)
                    return Bool
                raise SemanticError("Comparison requires operands of same type", e.line, e.col)
            if e.op in ('&&', '||'):
                if lt == Bool and rt == Bool:
                    self.ctx.set_type(e, Bool)
                    return Bool
                raise SemanticError("Logical && and || require bool operands", e.line, e.col)
            raise SemanticError(f"Unknown operator {e.op}", e.line, e.col)
        if isinstance(e, A.Index):
            arr_t = self._analyze_expr(e.array, scope)
            if not is_array_type(arr_t):
                raise SemanticError("Indexing requires int[N] array", e.line, e.col)
            idx_t = self._analyze_expr(e.index, scope)
            if idx_t != Int:
                raise SemanticError("Array index must be int", e.line, e.col)
            self.ctx.set_type(e, Int)
            return Int
        if isinstance(e, A.AddressOf):
            if isinstance(e.target, A.Identifier):
                sym = scope.resolve(e.target.name)
                if sym is None:
                    raise SemanticError(f"Undeclared variable '{e.target.name}'", e.target.line, e.target.col)
                self.ctx.set_type(e, Ptr)
                return Ptr
            if isinstance(e.target, A.Index):
                arr_t = self._analyze_expr(e.target.array, scope)
                if not is_array_type(arr_t):
                    raise SemanticError("Can only take address of int[N] array elements", e.target.line, e.target.col)
                idx_t = self._analyze_expr(e.target.index, scope)
                if idx_t != Int:
                    raise SemanticError("Array index must be int", e.target.line, e.target.col)
                self.ctx.set_type(e, Ptr)
                return Ptr
            raise SemanticError("Can only take address of variables or array elements", e.line, e.col)
        if isinstance(e, A.Call):
            # Special handling for array helpers
            if e.callee == "array_push":
                if len(e.args) != 3:
                    raise SemanticError("array_push expects 3 arguments", e.line, e.col)
                arr_t = self._analyze_expr(e.args[0], scope)
                if not is_array_type(arr_t):
                    raise SemanticError("array_push first argument must be int[N] array", e.line, e.col)
                len_t = self._analyze_expr(e.args[1], scope)
                if len_t != Int:
                    raise SemanticError("array_push length must be int", e.line, e.col)
                val_t = self._analyze_expr(e.args[2], scope)
                if val_t != Int:
                    raise SemanticError("array_push value must be int", e.line, e.col)
                self.ctx.set_type(e, Int)
                return Int
            if e.callee == "array_pop":
                if len(e.args) != 2:
                    raise SemanticError("array_pop expects 2 arguments", e.line, e.col)
                arr_t = self._analyze_expr(e.args[0], scope)
                if not is_array_type(arr_t):
                    raise SemanticError("array_pop first argument must be int[N] array", e.line, e.col)
                len_t = self._analyze_expr(e.args[1], scope)
                if len_t != Int:
                    raise SemanticError("array_pop length must be int", e.line, e.col)
                self.ctx.set_type(e, Int)
                return Int
            if e.callee not in self.ctx.functions:
                raise SemanticError(f"Call to undeclared function '{e.callee}'", e.line, e.col)
            sig = self.ctx.functions[e.callee]
            if len(e.args) != len(sig.params):
                raise SemanticError(f"Function '{e.callee}' expects {len(sig.params)} args, got {len(e.args)}", e.line, e.col)
            for a, pt in zip(e.args, sig.params):
                at = self._analyze_expr(a, scope)
                if at != pt:
                    raise SemanticError(f"Argument type mismatch: expected {pt}, got {at}", e.line, e.col)
            self.ctx.set_type(e, sig.ret)
            return sig.ret
        raise SemanticError("Unhandled expression type", e.line, e.col)
