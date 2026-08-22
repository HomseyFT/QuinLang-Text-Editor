from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from . import ast as A
from .compiler_types import (
    Type, Int, Str, Float, Void, Bool, Ptr, HeapPtr, Null, StructInfo, StructField,
    type_from_name, is_array_type, array_length, is_struct_type, is_reference_type,
    assignable, comparable, word_count, BUILTIN_TYPES, UnknownTypeError,
)
from .builtins import get_builtins

# A process exit code carries one byte, so only these values survive intact.
EXIT_CODE_MAX = 255


def wrap16(value: int) -> int:
    """Narrow to a 16-bit signed int, as the VM's arithmetic does."""
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def const_int(e: A.Expr):
    """Evaluate an expression built only from int literals, else return None.

    Only enough folding to recognise what people write for an exit code,
    including the `0 - 1` idiom the language requires in place of a negative
    literal. Wraps at 16 bits so the reported value is the one really returned.
    """
    if isinstance(e, A.Literal):
        if isinstance(e.value, int) and not isinstance(e.value, bool):
            return wrap16(e.value)
        return None
    if isinstance(e, A.Unary):
        v = const_int(e.right)
        if v is None:
            return None
        if e.op == '-':
            return wrap16(-v)
        if e.op == '~':
            return wrap16(~v)
        return None
    if isinstance(e, A.Binary):
        a, b = const_int(e.left), const_int(e.right)
        if a is None or b is None:
            return None
        if e.op == '+':
            return wrap16(a + b)
        if e.op == '-':
            return wrap16(a - b)
        if e.op == '*':
            return wrap16(a * b)
        return None
    return None


@dataclass
class Diagnostic:
    """Something worth telling the programmer that is not an error."""
    message: str
    line: int = 0
    col: int = 0

    def __str__(self) -> str:
        if self.line or self.col:
            return f"[{self.line}:{self.col}] {self.message}"
        return self.message


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

# eq=False so that two same-named variables in sibling scopes are distinct
# symbols, and so that Symbol stays hashable by identity: codegen keys frame
# slots off these objects.
@dataclass(eq=False)
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

    def define(self, sym: Symbol, line: int = 0, col: int = 0) -> Symbol:
        if sym.name in self.vars:
            raise SemanticError(f"Redeclaration of variable '{sym.name}'", line, col)
        self.vars[sym.name] = sym
        return sym

    def resolve(self, name: str) -> Optional[Symbol]:
        scope: Optional[Scope] = self
        while scope is not None:
            if name in scope.vars:
                return scope.vars[name]
            scope = scope.parent
        return None

    def visible(self) -> Dict[str, Symbol]:
        """Every name visible from here, with inner bindings shadowing outer ones."""
        chain: List[Scope] = []
        scope: Optional[Scope] = self
        while scope is not None:
            chain.append(scope)
            scope = scope.parent
        names: Dict[str, Symbol] = {}
        for s in reversed(chain):
            names.update(s.vars)
        return names

class Context:
    """Everything the front end learned, for the backend to consume.

    Name resolution and typing happen here exactly once; a backend reads these
    tables rather than walking scopes again, so there is a single implementation
    of what an identifier refers to.
    """

    def __init__(self):
        self.functions: Dict[str, FunctionSig] = {}
        # Struct name -> its layout and heap type id. Codegen turns this into
        # the table the VM carries, which is also what a collector needs to
        # learn an object's size and which of its fields are references.
        self.structs: Dict[str, StructInfo] = {}
        self.node_type: Dict[int, Type] = {}
        # id(Identifier | VarDecl | Param) -> the Symbol it refers to or declares.
        self.binding: Dict[int, Symbol] = {}
        # Function name -> every symbol in its frame, parameters first (the
        # calling convention requires them to lead) and then declarations in
        # source order. Codegen turns this list straight into slots.
        self.frame_symbols: Dict[str, List[Symbol]] = {}
        # id(VmAsm) -> names visible at that block, since its body is raw text
        # that no other pass resolves.
        self.asm_scope: Dict[int, Dict[str, Symbol]] = {}
        # Statement list (or For node) -> the reference-typed symbols its scope
        # declares directly. Codegen releases these slots when the scope ends,
        # so an out-of-scope variable stops rooting its object.
        self.scope_refs: Dict[int, List[Symbol]] = {}
        # Sema is the only pass that raises one today, but codegen receives
        # this Context too and could add its own.
        self.warnings: List[Diagnostic] = []

    def set_type(self, node: A.Expr, t: Type):
        self.node_type[id(node)] = t

    def get_type(self, node: A.Expr) -> Type:
        return self.node_type[id(node)]

    def bind(self, node: A.Node, sym: Symbol):
        self.binding[id(node)] = sym

    def binding_of(self, node: A.Node) -> Optional[Symbol]:
        return self.binding.get(id(node))

class SemanticAnalyzer:
    def __init__(self):
        self.ctx = Context()
        # Symbols declared by the function currently being analyzed, in the
        # order they will occupy frame slots.
        self._frame: List[Symbol] = []
        # How many loops enclose the statement being analyzed, so that a
        # 'break' or 'continue' with nothing to jump to is rejected here
        # rather than becoming a dangling jump in codegen.
        self._loop_depth = 0
        # The function being analyzed, so a return in main can be recognised.
        self._current_function = None

    def _resolve_type(self, name: str, line: int, col: int) -> Type:
        """Map a source-level type name onto a concrete Type, with location on failure."""
        try:
            return type_from_name(name, self.ctx.structs)
        except UnknownTypeError as e:
            raise SemanticError(str(e), line, col)

    def _register_structs(self, program: A.Program):
        """Resolve struct declarations in two phases.

        Every name is registered before any field type is resolved, so a struct
        may name itself or a struct declared later in the file. That is what
        makes `struct Node { next: Node }` — and therefore any linked structure
        — expressible.
        """
        for sd in program.structs:
            if sd.name in self.ctx.structs:
                raise SemanticError(f"Redefinition of struct '{sd.name}'", sd.line, sd.col)
            if sd.name in BUILTIN_TYPES:
                raise SemanticError(
                    f"Struct '{sd.name}' shadows the built-in type '{sd.name}'", sd.line, sd.col
                )
            if not sd.fields:
                raise SemanticError(
                    f"Struct '{sd.name}' must declare at least one field", sd.line, sd.col
                )
            self.ctx.structs[sd.name] = StructInfo(sd.name, type_id=len(self.ctx.structs))

        for sd in program.structs:
            info = self.ctx.structs[sd.name]
            fields: List[StructField] = []
            seen: Dict[str, bool] = {}
            offset = 0
            for f in sd.fields:
                if f.name in seen:
                    raise SemanticError(
                        f"Duplicate field '{f.name}' in struct '{sd.name}'", f.line, f.col
                    )
                seen[f.name] = True
                ft = self._resolve_type(f.type_name, f.line, f.col)
                if is_array_type(ft):
                    raise SemanticError(
                        f"Field '{f.name}' cannot be an array; arrays live in a frame, "
                        f"not in a heap object",
                        f.line, f.col,
                    )
                if ft == Void:
                    raise SemanticError(
                        f"Field '{f.name}' cannot have type void", f.line, f.col
                    )
                fields.append(StructField(f.name, ft, offset))
                # Offsets are word offsets, and a float field is two words
                # wide, so this is a running total rather than the field index.
                offset += word_count(ft)
            info.fields = fields

    def analyze(self, program: A.Program) -> Context:
        # Structs first: function signatures may mention struct types.
        self._register_structs(program)

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
        self._frame = []
        self._loop_depth = 0
        self._current_function = fn.name
        for p, t in zip(fn.params, sig.params):
            sym = scope.define(Symbol(p.name, t), p.line, p.col)
            self.ctx.bind(p, sym)
            self._frame.append(sym)
        always_returns = any(self._always_returns(st, scope, sig.ret) for st in fn.body)
        for st in fn.body:
            self._analyze_stmt(st, scope, sig.ret)
        if sig.ret != Void and not always_returns:
            raise SemanticError(f"Function '{fn.name}' missing return statement", fn.line, fn.col)
        self.ctx.frame_symbols[fn.name] = self._frame
        self._frame = []

    def _analyze_stmt(self, st: A.Stmt, scope: Scope, ret_type: Type = Void):
        if isinstance(st, A.VarDecl):
            var_type = self._resolve_type(st.type_name, st.line, st.col) if st.type_name else None
            if st.init is not None:
                init_t = self._analyze_expr(st.init, scope)
                if var_type is None:
                    if init_t == Null:
                        raise SemanticError(
                            f"Cannot infer type for '{st.name}' from 'null'; "
                            f"annotate it with the reference type you mean",
                            st.line, st.col,
                        )
                    var_type = init_t
                elif not assignable(var_type, init_t):
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
            sym = scope.define(Symbol(st.name, var_type), st.line, st.col)
            self.ctx.bind(st, sym)
            self._frame.append(sym)
        elif isinstance(st, A.Assign):
            if isinstance(st.target, A.Identifier):
                sym = scope.resolve(st.target.name)
                if sym is None:
                    raise SemanticError(f"Undeclared variable '{st.target.name}'", st.target.line, st.target.col)
                self.ctx.bind(st.target, sym)
                if is_array_type(sym.type):
                    raise SemanticError(
                        f"Cannot assign to array variable '{st.target.name}' as a whole; "
                        f"assign to its elements instead",
                        st.target.line, st.target.col,
                    )
                val_t = self._analyze_expr(st.value, scope)
                if not assignable(sym.type, val_t):
                    raise SemanticError(f"Cannot assign {val_t} to {sym.type} variable '{st.target.name}'", st.target.line, st.target.col)
            elif isinstance(st.target, A.Index):
                arr_t = self._analyze_expr(st.target.array, scope)
                self._validate_index(
                    arr_t, st.target.index, scope,
                    "Index target must be an int[N] array",
                    st.target.line, st.target.col,
                )
                val_t = self._analyze_expr(st.value, scope)
                if val_t != Int:
                    raise SemanticError("Array elements must be int", st.line, st.col)
            elif isinstance(st.target, A.FieldAccess):
                # Typing the target validates the struct and the field name.
                field_t = self._analyze_expr(st.target, scope)
                val_t = self._analyze_expr(st.value, scope)
                if not assignable(field_t, val_t):
                    raise SemanticError(
                        f"Cannot assign {val_t} to field '{st.target.field}' of type {field_t}",
                        st.target.line, st.target.col,
                    )
            else:
                raise SemanticError("Invalid assignment target", st.line, st.col)
        elif isinstance(st, A.Print) or isinstance(st, A.PrintLn):
            val_t = self._analyze_expr(st.value, scope)
            # bool prints as "true"/"false"; the VM backend lowers it via a
            # branch into the string table.
            if val_t not in (Int, Str, Bool, Float):
                raise SemanticError(
                    f"print/println expect int, float, str, or bool, got {val_t}",
                    st.line, st.col
                )
        elif isinstance(st, A.Return):
            if ret_type == Void and st.value is not None:
                raise SemanticError("Void function cannot return a value", st.line, st.col)
            if ret_type != Void and st.value is None:
                raise SemanticError(f"Expected return value of type {ret_type}", st.line, st.col)
            if st.value is not None:
                val_t = self._analyze_expr(st.value, scope)
                if not assignable(ret_type, val_t):
                    raise SemanticError(f"Return type mismatch: expected {ret_type}, got {val_t}", st.line, st.col)
                if self._current_function == "main" and ret_type == Int:
                    self._check_exit_code(st.value)
        elif isinstance(st, A.If):
            cond_t = self._analyze_expr(st.cond, scope)
            if cond_t != Bool:
                raise SemanticError("If condition must be bool", st.line, st.col)
            then_scope = Scope(scope)
            for s in st.then_block:
                self._analyze_stmt(s, then_scope, ret_type)
            self._record_scope_refs(st.then_block, then_scope)
            if st.else_block:
                else_scope = Scope(scope)
                for s in st.else_block:
                    self._analyze_stmt(s, else_scope, ret_type)
                self._record_scope_refs(st.else_block, else_scope)
        elif isinstance(st, A.While):
            cond_t = self._analyze_expr(st.cond, scope)
            if cond_t != Bool:
                raise SemanticError("While condition must be bool", st.line, st.col)
            body_scope = Scope(scope)
            self._loop_depth += 1
            for s in st.body:
                self._analyze_stmt(s, body_scope, ret_type)
            self._loop_depth -= 1
            self._record_scope_refs(st.body, body_scope)
        elif isinstance(st, A.For):
            # The init clause declares into a scope wrapping the loop, so the
            # loop variable is visible to cond/step/body and nowhere else.
            loop_scope = Scope(scope)
            if st.init is not None:
                self._analyze_stmt(st.init, loop_scope, ret_type)
            if st.cond is not None:
                cond_t = self._analyze_expr(st.cond, loop_scope)
                if cond_t != Bool:
                    raise SemanticError("For condition must be bool", st.line, st.col)
            if st.step is not None:
                self._analyze_stmt(st.step, loop_scope, ret_type)
            body_scope = Scope(loop_scope)
            self._loop_depth += 1
            for s in st.body:
                self._analyze_stmt(s, body_scope, ret_type)
            self._loop_depth -= 1
            self._record_scope_refs(st.body, body_scope)
            # The init clause's scope wraps the whole loop, so it is released
            # once the loop is done rather than on each iteration.
            self._record_scope_refs(st, loop_scope)
        elif isinstance(st, A.Block):
            block_scope = Scope(scope)
            for s in st.stmts:
                self._analyze_stmt(s, block_scope, ret_type)
            self._record_scope_refs(st.stmts, block_scope)
        elif isinstance(st, A.Break):
            if self._loop_depth == 0:
                raise SemanticError("'break' outside of a loop", st.line, st.col)
        elif isinstance(st, A.Continue):
            if self._loop_depth == 0:
                raise SemanticError("'continue' outside of a loop", st.line, st.col)
        elif isinstance(st, A.ExprStmt):
            self._analyze_expr(st.expr, scope)
        elif isinstance(st, A.VmAsm):
            # The block's body is raw text, so the only thing to resolve here is
            # which names it can reach. Its stack effect is still unchecked; an
            # imbalance surfaces as a VM error at RET.
            self.ctx.asm_scope[id(st)] = scope.visible()
        else:
            pass

    def _record_scope_refs(self, key, scope: Scope):
        """Note the references a scope declares, for codegen to release.

        A scope declaring no references records nothing, so ordinary code costs
        no instructions.
        """
        refs = [sym for sym in scope.vars.values() if is_reference_type(sym.type)]
        if refs:
            self.ctx.scope_refs[id(key)] = refs

    def _check_exit_code(self, value: A.Expr):
        """Warn when main returns a constant the exit code cannot represent, so
        that `return 256` does not quietly exit 0 and read as success.
        `return f()` cannot be judged and is left alone."""
        result = const_int(value)
        if result is None or 0 <= result <= EXIT_CODE_MAX:
            return
        self.ctx.warnings.append(Diagnostic(
            f"main returns {result}, but a process exit code carries only the "
            f"low byte, so this exits {result & 0xFF}. Return a value in "
            f"0..{EXIT_CODE_MAX} to say what you mean.",
            value.line, value.col,
        ))

    def _always_returns(self, st: A.Stmt, scope: Scope, ret_type: Type) -> bool:
        """Return True if statement always returns (i.e., execution cannot continue past it)."""
        if isinstance(st, A.Return):
            return True
        if (isinstance(st, A.ExprStmt) and isinstance(st.expr, A.Call)
                and st.expr.callee == "panic"):
            # panic stops the program, so nothing after it can run. Without
            # this, every panic in a non-void function would need a dummy
            # return after it to satisfy the return check.
            return True
        if isinstance(st, A.Block):
            for s in st.stmts:
                if self._always_returns(s, scope, ret_type):
                    return True
            return False
        if isinstance(st, A.If):
            then_always = any(self._always_returns(s, scope, ret_type) for s in st.then_block)
            if st.else_block:
                else_always = any(self._always_returns(s, scope, ret_type) for s in st.else_block)
                return then_always and else_always
            else:
                return False
        if isinstance(st, (A.While, A.For)):
            # A loop body may not run, so it never guarantees a return. An
            # unconditional loop that only exits by 'return' is rejected too;
            # the check is deliberately conservative.
            return False
        return False

    @staticmethod
    def _const_int(e: A.Expr):
        """The value of `e` if it is an int literal, else None.

        `bool` is excluded because it is an int subclass in Python and would
        otherwise let `true` pass as the index 1.
        """
        if isinstance(e, A.Literal) and isinstance(e.value, int) and not isinstance(e.value, bool):
            return e.value
        return None

    def _check_const_length(self, arr_t: Type, len_expr: A.Expr, what: str,
                            offset: int, line: int, col: int):
        """Reject an array_push/array_pop whose length is a literal that puts
        the access outside the array. `offset` is what the builtin adds to the
        length to reach the element it touches: 0 for push, -1 for pop.
        """
        len_val = self._const_int(len_expr)
        length = array_length(arr_t)
        if len_val is None or length is None:
            return
        idx = len_val + offset
        if idx < 0 or idx >= length:
            raise SemanticError(
                f"{what} at length {len_val} accesses index {idx}, "
                f"out of bounds for length {length}",
                line, col,
            )

    def _validate_index(self, arr_t: Type, idx_expr: A.Expr, scope: Scope, not_array_msg: str, line: int, col: int):
        """Shared by reads, assignment targets and address-of, so a literal
        index out of range is caught the same way in all three."""
        if not is_array_type(arr_t):
            raise SemanticError(not_array_msg, line, col)
        idx_t = self._analyze_expr(idx_expr, scope)
        if idx_t != Int:
            raise SemanticError("Array index must be int", line, col)
        idx_val = self._const_int(idx_expr)
        if idx_val is not None:
            length = array_length(arr_t)
            if length is not None and (idx_val < 0 or idx_val >= length):
                raise SemanticError(
                    f"Array index {idx_val} out of bounds for length {length}",
                    line, col,
                )

    def _analyze_expr(self, e: A.Expr, scope: Scope) -> Type:
        if isinstance(e, A.Literal):
            if e.value is None:
                self.ctx.set_type(e, Null)
                return Null
            if isinstance(e.value, bool):
                self.ctx.set_type(e, Bool)
                return Bool
            if isinstance(e.value, int):
                self.ctx.set_type(e, Int)
                return Int
            if isinstance(e.value, float):
                self.ctx.set_type(e, Float)
                return Float
            if isinstance(e.value, str):
                self.ctx.set_type(e, Str)
                return Str
            self.ctx.set_type(e, Void)
            return Void
        if isinstance(e, A.Identifier):
            sym = scope.resolve(e.name)
            if sym is None:
                raise SemanticError(f"Undeclared variable '{e.name}'", e.line, e.col)
            self.ctx.bind(e, sym)
            self.ctx.set_type(e, sym.type)
            return sym.type
        if isinstance(e, A.Unary):
            t = self._analyze_expr(e.right, scope)
            if e.op == '-' and t == Int:
                self.ctx.set_type(e, Int)
                return Int
            if e.op == '-' and t == Float:
                self.ctx.set_type(e, Float)
                return Float
            if e.op == '!' and t == Bool:
                self.ctx.set_type(e, Bool)
                return Bool
            if e.op == '~' and t == Int:
                self.ctx.set_type(e, Int)
                return Int
            raise SemanticError(f"Invalid unary op {e.op} for type {t}", e.line, e.col)
        if isinstance(e, A.Binary):
            lt = self._analyze_expr(e.left, scope)
            rt = self._analyze_expr(e.right, scope)
            if e.op in ('+', '-', '*', '/'):
                if e.op == '+' and lt == Str and rt == Str:
                    self.ctx.set_type(e, Str)
                    return Str
                if e.op == '+':
                    if (lt == HeapPtr and rt == Int) or (lt == Int and rt == HeapPtr):
                        self.ctx.set_type(e, HeapPtr)
                        return HeapPtr
                elif e.op == '-':
                    if lt == HeapPtr and rt == Int:
                        self.ctx.set_type(e, HeapPtr)
                        return HeapPtr
                    # heapptr - heapptr is deliberately absent. It was the only
                    # expression that yielded a reference's numeric value as an
                    # int, which would let a program stash an address somewhere
                    # a collector does not look and then reconstruct it.
                    if lt == HeapPtr and rt == HeapPtr:
                        raise SemanticError(
                            "Cannot subtract two heapptr values; a reference cannot be "
                            "converted to an int",
                            e.line, e.col,
                        )
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float and rt == Float:
                    self.ctx.set_type(e, Float)
                    return Float
                # int and float do not mix implicitly. A silent widening would
                # make `n / 2` mean different things depending on a declaration
                # elsewhere; int_to_float makes the choice visible.
                if {lt, rt} == {Int, Float}:
                    raise SemanticError(
                        "Cannot mix int and float; convert explicitly with "
                        "int_to_float or float_to_int",
                        e.line, e.col,
                    )
                raise SemanticError("Arithmetic operators require int or float operands", e.line, e.col)
            if e.op == '%':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float or rt == Float:
                    raise SemanticError(
                        "'%' does not apply to float; convert with float_to_int first",
                        e.line, e.col,
                    )
                raise SemanticError("Modulo operator requires int operands", e.line, e.col)
            if e.op == '^':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float or rt == Float:
                    raise SemanticError(
                        "'^' does not apply to float; convert with float_to_int first",
                        e.line, e.col,
                    )
                raise SemanticError("Bitwise XOR operator requires int operands", e.line, e.col)
            if e.op == '&':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float or rt == Float:
                    raise SemanticError(
                        "'&' does not apply to float; convert with float_to_int first",
                        e.line, e.col,
                    )
                raise SemanticError("Bitwise AND operator requires int operands", e.line, e.col)
            if e.op == '|':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float or rt == Float:
                    raise SemanticError(
                        "'|' does not apply to float; convert with float_to_int first",
                        e.line, e.col,
                    )
                raise SemanticError("Bitwise OR operator requires int operands", e.line, e.col)
            if e.op == '<<':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float or rt == Float:
                    raise SemanticError(
                        "'<<' does not apply to float; convert with float_to_int first",
                        e.line, e.col,
                    )
                raise SemanticError("Left shift operator requires int operands", e.line, e.col)
            if e.op == '>>':
                if lt == Int and rt == Int:
                    self.ctx.set_type(e, Int)
                    return Int
                if lt == Float or rt == Float:
                    raise SemanticError(
                        "'>>' does not apply to float; convert with float_to_int first",
                        e.line, e.col,
                    )
                raise SemanticError("Right shift operator requires int operands", e.line, e.col)
            if e.op in ('==', '!='):
                # Equality is the one place null may meet a reference type.
                if comparable(lt, rt):
                    self.ctx.set_type(e, Bool)
                    return Bool
                raise SemanticError("Comparison requires operands of same type", e.line, e.col)
            if e.op in ('<', '<=', '>', '>='):
                if is_struct_type(lt) or is_struct_type(rt) or lt == Null or rt == Null:
                    raise SemanticError(
                        "Relational operators do not apply to struct references or null",
                        e.line, e.col,
                    )
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
            self._validate_index(arr_t, e.index, scope, "Indexing requires int[N] array", e.line, e.col)
            self.ctx.set_type(e, Int)
            return Int
        if isinstance(e, A.AddressOf):
            if isinstance(e.target, A.Identifier):
                sym = scope.resolve(e.target.name)
                if sym is None:
                    raise SemanticError(f"Undeclared variable '{e.target.name}'", e.target.line, e.target.col)
                # A frame pointer to a reference slot would let load16 read the
                # address out as an int and store16 put one back, which is the
                # last way to hide a reference from the collector or to keep a
                # stale one. Address-of stays available for ints and arrays.
                if is_reference_type(sym.type):
                    raise SemanticError(
                        f"Cannot take the address of '{e.target.name}': it holds a "
                        f"{sym.type} reference, and a reference cannot be converted "
                        f"to an int",
                        e.target.line, e.target.col,
                    )
                # A ptr addresses one slot, and a float is two. The pointer
                # would silently name the low half, so load16 would read half a
                # value and store16 would corrupt one. Nothing about the ptr
                # type can express the difference, so the address is refused.
                if sym.type == Float:
                    raise SemanticError(
                        f"Cannot take the address of '{e.target.name}': a float is "
                        f"two slots wide and a ptr addresses one",
                        e.target.line, e.target.col,
                    )
                self.ctx.bind(e.target, sym)
                self.ctx.set_type(e, Ptr)
                return Ptr
            if isinstance(e.target, A.Index):
                arr_t = self._analyze_expr(e.target.array, scope)
                self._validate_index(arr_t, e.target.index, scope, "Can only take address of int[N] array elements", e.target.line, e.target.col)
                self.ctx.set_type(e, Ptr)
                return Ptr
            raise SemanticError("Can only take address of variables or array elements", e.line, e.col)
        if isinstance(e, A.FieldAccess):
            obj_t = self._analyze_expr(e.obj, scope)
            if not is_struct_type(obj_t):
                raise SemanticError(
                    f"Field access requires a struct value, got {obj_t}", e.line, e.col
                )
            info = self.ctx.structs[obj_t.name]
            fld = info.field_named(e.field)
            if fld is None:
                raise SemanticError(
                    f"Struct '{info.name}' has no field '{e.field}'", e.line, e.col
                )
            self.ctx.set_type(e, fld.type)
            return fld.type
        if isinstance(e, A.StructLit):
            info = self.ctx.structs.get(e.struct_name)
            if info is None:
                raise SemanticError(f"Unknown struct '{e.struct_name}'", e.line, e.col)
            seen: Dict[str, bool] = {}
            for fi in e.fields:
                if fi.name in seen:
                    raise SemanticError(
                        f"Field '{fi.name}' given twice in literal for '{info.name}'",
                        fi.line, fi.col,
                    )
                fld = info.field_named(fi.name)
                if fld is None:
                    raise SemanticError(
                        f"Struct '{info.name}' has no field '{fi.name}'", fi.line, fi.col
                    )
                seen[fi.name] = True
                val_t = self._analyze_expr(fi.value, scope)
                if not assignable(fld.type, val_t):
                    raise SemanticError(
                        f"Field '{fi.name}' expects {fld.type}, got {val_t}", fi.line, fi.col
                    )
            missing = [f.name for f in info.fields if f.name not in seen]
            if missing:
                raise SemanticError(
                    f"Struct literal for '{info.name}' is missing field(s): "
                    f"{', '.join(missing)}",
                    e.line, e.col,
                )
            t = info.type()
            self.ctx.set_type(e, t)
            return t
        if isinstance(e, A.Call):
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
                # A push writes at index `len`, so a literal length is the same
                # thing as a literal index and gets caught here rather than at
                # run time. Anything computed is checked by BOUNDS_CHECK.
                self._check_const_length(arr_t, e.args[1], "array_push", 0, e.line, e.col)
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
                # A pop reads at index `len - 1`, so popping an empty array is
                # index -1 and is rejected the same way as an overrun.
                self._check_const_length(arr_t, e.args[1], "array_pop", -1, e.line, e.col)
                self.ctx.set_type(e, Int)
                return Int
            if e.callee not in self.ctx.functions:
                raise SemanticError(f"Call to undeclared function '{e.callee}'", e.line, e.col)
            sig = self.ctx.functions[e.callee]
            if len(e.args) != len(sig.params):
                raise SemanticError(f"Function '{e.callee}' expects {len(sig.params)} args, got {len(e.args)}", e.line, e.col)
            for a, pt in zip(e.args, sig.params):
                at = self._analyze_expr(a, scope)
                if not assignable(pt, at):
                    raise SemanticError(f"Argument type mismatch: expected {pt}, got {at}", e.line, e.col)
            self.ctx.set_type(e, sig.ret)
            return sig.ret
        raise SemanticError("Unhandled expression type", e.line, e.col)
