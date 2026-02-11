from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from . import ast as A
from .types import Type, Int, Str, Void, Bool, Ptr, type_from_name, is_array_type
from .builtins import get_builtins, BuiltinSig

class SemanticError(Exception):
    pass

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

    def define(self, sym: Symbol):
        if sym.name in self.vars:
            raise SemanticError(f"Redeclaration of variable '{sym.name}'")
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
            param_types = [type_from_name(p.type_name) for p in fn.params]
            ret_type = type_from_name(fn.return_type) if fn.return_type else Void
            if fn.name in self.ctx.functions:
                raise SemanticError(f"Redefinition of function '{fn.name}'")
            self.ctx.functions[fn.name] = FunctionSig(fn.name, param_types, ret_type)
        if 'main' not in self.ctx.functions:
            raise SemanticError("Missing entry point 'main'")
        # Second pass: analyze function bodies
        for fn in program.functions:
            self._analyze_function(fn)
        return self.ctx

    def _analyze_function(self, fn: A.Function):
        sig = self.ctx.functions[fn.name]
        scope = Scope()
        for p, t in zip(fn.params, sig.params):
            scope.define(Symbol(p.name, t))
        saw_return = False
        for st in fn.body:
            self._analyze_stmt(st, scope)
            if isinstance(st, A.Return):
                saw_return = True
        # For non-void functions, require at least one return
        if sig.ret != Void and not saw_return:
            raise SemanticError(f"Function '{fn.name}' missing return statement")

    def _analyze_stmt(self, st: A.Stmt, scope: Scope):
        if isinstance(st, A.VarDecl):
            var_type = type_from_name(st.type_name) if st.type_name else None
            if st.init is not None:
                init_t = self._analyze_expr(st.init, scope)
                if var_type is None:
                    var_type = init_t
                elif var_type != init_t:
                    raise SemanticError(f"Type mismatch in initializer for '{st.name}': {var_type} vs {init_t}")
            if var_type is None:
                raise SemanticError(f"Cannot infer type for '{st.name}' without initializer")
            scope.define(Symbol(st.name, var_type))
        elif isinstance(st, A.Assign):
            # Generalized assignment target
            if isinstance(st.target, A.Identifier):
                sym = scope.resolve(st.target.name)
                if sym is None:
                    raise SemanticError(f"Undeclared variable '{st.target.name}'")
                val_t = self._analyze_expr(st.value, scope)
                if sym.type != val_t:
                    raise SemanticError(f"Cannot assign {val_t} to {sym.type} variable '{st.target.name}'")
            elif isinstance(st.target, A.Index):
                arr_t = self._analyze_expr(st.target.array, scope)
                if not is_array_type(arr_t):
                    raise SemanticError("Index target must be an int[N] array")
                idx_t = self._analyze_expr(st.target.index, scope)
                if idx_t != Int:
                    raise SemanticError("Array index must be int")
                val_t = self._analyze_expr(st.value, scope)
                if val_t != Int:
                    raise SemanticError("Array elements must be int")
            else:
                raise SemanticError("Invalid assignment target")
        elif isinstance(st, A.Print) or isinstance(st, A.PrintLn):
            val_t = self._analyze_expr(st.value, scope)
            if val_t not in (Int, Str):
                raise SemanticError("print/println expect int or str")
        elif isinstance(st, A.Return):
            # We can't access function return type easily here without passing it; for simplicity, allow any
            if st.value is not None:
                self._analyze_expr(st.value, scope)
        elif isinstance(st, A.If):
            self._analyze_expr(st.cond, scope)
            then_scope = Scope(scope)
            for s in st.then_block:
                self._analyze_stmt(s, then_scope)
            if st.else_block:
                else_scope = Scope(scope)
                for s in st.else_block:
                    self._analyze_stmt(s, else_scope)
        elif isinstance(st, A.While):
            self._analyze_expr(st.cond, scope)
            body_scope = Scope(scope)
            for s in st.body:
                self._analyze_stmt(s, body_scope)
        elif isinstance(st, A.ExprStmt):
            self._analyze_expr(st.expr, scope)
        else:
            # Ignore blocks etc.
            pass

    def _analyze_expr(self, e: A.Expr, scope: Scope) -> Type:
        if isinstance(e, A.Literal):
            # Order matters: in Python, bool is a subclass of int, so check bool first.
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
                raise SemanticError(f"Undeclared variable '{e.name}'")
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
            raise SemanticError(f"Invalid unary op {e.op} for type {t}")
        if isinstance(e, A.Binary):
            lt = self._analyze_expr(e.left, scope)
            rt = self._analyze_expr(e.right, scope)
            if e.op in ('+', '-', '*', '/'):
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                raise SemanticError("Arithmetic operators require int operands")
            if e.op in ('==', '!=', '<', '<=', '>', '>='):
                if lt == rt:
                    self.ctx.set_type(e, Bool)
                    return Bool
                raise SemanticError("Comparison requires operands of same type")
            if e.op in ('&&', '||'):
                if lt == Bool and rt == Bool:
                    self.ctx.set_type(e, Bool)
                    return Bool
                raise SemanticError("Logical && and || require bool operands")
            raise SemanticError(f"Unknown operator {e.op}")
        if isinstance(e, A.Index):
            arr_t = self._analyze_expr(e.array, scope)
            if not is_array_type(arr_t):
                raise SemanticError("Indexing requires int[N] array")
            idx_t = self._analyze_expr(e.index, scope)
            if idx_t != Int:
                raise SemanticError("Array index must be int")
            self.ctx.set_type(e, Int)
            return Int
        if isinstance(e, A.AddressOf):
            # For now, allow taking the address of local variables and array elements only.
            if isinstance(e.target, A.Identifier):
                sym = scope.resolve(e.target.name)
                if sym is None:
                    raise SemanticError(f"Undeclared variable '{e.target.name}'")
                # Any object with a stack slot can have its address taken; treat as ptr.
                self.ctx.set_type(e, Ptr)
                return Ptr
            if isinstance(e.target, A.Index):
                # Address of array element; also ptr.
                arr_t = self._analyze_expr(e.target.array, scope)
                if not is_array_type(arr_t):
                    raise SemanticError("Can only take address of int[N] array elements")
                idx_t = self._analyze_expr(e.target.index, scope)
                if idx_t != Int:
                    raise SemanticError("Array index must be int")
                self.ctx.set_type(e, Ptr)
                return Ptr
            raise SemanticError("Can only take address of variables or array elements")
        if isinstance(e, A.Call):
            # Special handling for array helpers whose first argument is an array.
            if e.callee == "array_push":
                if len(e.args) != 3:
                    raise SemanticError("array_push expects 3 arguments")
                arr_t = self._analyze_expr(e.args[0], scope)
                if not is_array_type(arr_t):
                    raise SemanticError("array_push first argument must be int[N] array")
                len_t = self._analyze_expr(e.args[1], scope)
                if len_t != Int:
                    raise SemanticError("array_push length must be int")
                val_t = self._analyze_expr(e.args[2], scope)
                if val_t != Int:
                    raise SemanticError("array_push value must be int")
                self.ctx.set_type(e, Int)
                return Int
            if e.callee == "array_pop":
                if len(e.args) != 2:
                    raise SemanticError("array_pop expects 2 arguments")
                arr_t = self._analyze_expr(e.args[0], scope)
                if not is_array_type(arr_t):
                    raise SemanticError("array_pop first argument must be int[N] array")
                len_t = self._analyze_expr(e.args[1], scope)
                if len_t != Int:
                    raise SemanticError("array_pop length must be int")
                # returns popped int
                self.ctx.set_type(e, Int)
                return Int
            if e.callee not in self.ctx.functions:
                raise SemanticError(f"Call to undeclared function '{e.callee}'")
            sig = self.ctx.functions[e.callee]
            if len(e.args) != len(sig.params):
                raise SemanticError(f"Function '{e.callee}' expects {len(sig.params)} args, got {len(e.args)}")
            for a, pt in zip(e.args, sig.params):
                at = self._analyze_expr(a, scope)
                if at != pt:
                    raise SemanticError(f"Argument type mismatch: expected {pt}, got {at}")
            self.ctx.set_type(e, sig.ret)
            return sig.ret
        raise SemanticError("Unhandled expression type")
