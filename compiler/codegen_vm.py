from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from . import ast as A
from .bytecode import OpCode, Instruction, Bytecode
from .sema import Context
from .compiler_types import Int, Str, Bool, Void, array_length_from_name


class CodegenError(Exception):
    """Raised when the AST cannot be lowered to bytecode.

    Most of these indicate a hole in semantic analysis rather than a user
    error: by the time codegen runs, names and types are supposed to be
    resolved. Failing loudly here beats emitting code that quietly computes
    the wrong answer.
    """


@dataclass
class LocalSlot:
    """A location in the current frame's locals array.

    Arrays occupy `length` consecutive slots starting at `index`.
    """
    index: int
    length: int = 0  # 0 => scalar, >0 => int[N] array

    @property
    def is_array(self) -> bool:
        return self.length > 0


@dataclass
class FunctionLayout:
    name: str
    num_locals: int
    num_params: int
    entry_pc: int = 0
    # Parameter name -> slot. Parameters occupy slots 0..num_params-1.
    params: Dict[str, LocalSlot] = field(default_factory=dict)
    # id(A.VarDecl) -> slot. Keyed by node identity rather than by name so
    # that shadowed and sibling-scope declarations get distinct storage.
    decl_slots: Dict[int, LocalSlot] = field(default_factory=dict)


class CodeGenVM:
    """Lowers a type-checked AST to QuinVM bytecode.

    Calling convention: every function leaves exactly one value on the operand
    stack when it returns, and every expression leaves exactly one value. Void
    functions and void builtins return a dummy 0 that the caller discards. This
    keeps RET uniform and lets the VM verify frame balance.
    """

    def __init__(self):
        self.code: Bytecode = []
        self.functions: List[FunctionLayout] = []
        self.strings: Dict[int, str] = {}
        self._string_ids: Dict[str, int] = {}
        # map function name -> index used in CALL opcode
        self.func_name_to_index: Dict[str, int] = {}
        # Lexical scope stack for the function currently being emitted.
        self._scopes: List[Dict[str, LocalSlot]] = []

    # -- string table ----------------------------------------------------

    def _add_string(self, value: str) -> int:
        """Intern a string literal, returning its id.

        Interning keeps the table from growing per call site and makes string
        equality (which compares ids) behave sanely.
        """
        if value in self._string_ids:
            return self._string_ids[value]
        sid = len(self._string_ids)
        self._string_ids[value] = sid
        self.strings[sid] = value
        return sid

    # -- scope handling --------------------------------------------------

    def _push_scope(self):
        self._scopes.append({})

    def _pop_scope(self):
        self._scopes.pop()

    def _declare(self, name: str, slot: LocalSlot):
        self._scopes[-1][name] = slot

    def _lookup(self, name: str) -> Optional[LocalSlot]:
        for scope in reversed(self._scopes):
            slot = scope.get(name)
            if slot is not None:
                return slot
        return None

    def _lookup_or_fail(self, name: str, node: A.Node) -> LocalSlot:
        slot = self._lookup(name)
        if slot is None:
            raise CodegenError(f"[{node.line}:{node.col}] Unresolved name '{name}'")
        return slot

    def _array_slot(self, e: A.Expr) -> LocalSlot:
        if not isinstance(e, A.Identifier):
            raise CodegenError(
                f"[{e.line}:{e.col}] Only named local arrays can be indexed"
            )
        slot = self._lookup_or_fail(e.name, e)
        if not slot.is_array:
            raise CodegenError(f"[{e.line}:{e.col}] '{e.name}' is not an array")
        return slot

    # -- entry point -----------------------------------------------------

    def generate(self, program: A.Program, ctx: Context):
        # Register every function before emitting any of them, so that a call
        # to a function defined later in the file resolves correctly.
        for fn in program.functions:
            if fn.name in self.func_name_to_index:
                raise CodegenError(f"[{fn.line}:{fn.col}] Duplicate function '{fn.name}'")
            self.func_name_to_index[fn.name] = len(self.functions)
            self.functions.append(self._build_layout(fn))

        for fn, layout in zip(program.functions, self.functions):
            layout.entry_pc = len(self.code)
            self._emit_function(fn, layout, ctx)

        from runtime.vm import FunctionInfo
        fns = [
            FunctionInfo(fl.name, fl.entry_pc, fl.num_locals, fl.num_params)
            for fl in self.functions
        ]
        return self.code, fns, self.strings

    def _build_layout(self, fn: A.Function) -> FunctionLayout:
        """Assign a distinct slot to every parameter and every declaration.

        Slots are never reused across sibling scopes. That costs a few frame
        slots but guarantees two declarations of the same name can't collide.
        """
        params: Dict[str, LocalSlot] = {}
        decl_slots: Dict[int, LocalSlot] = {}
        next_idx = 0

        for p in fn.params:
            if p.name in params:
                raise CodegenError(
                    f"[{p.line}:{p.col}] Duplicate parameter '{p.name}' in function '{fn.name}'"
                )
            params[p.name] = LocalSlot(next_idx)
            next_idx += 1

        def visit(stmts: List[A.Stmt]) -> None:
            nonlocal next_idx
            for st in stmts:
                if isinstance(st, A.VarDecl):
                    length = array_length_from_name(st.type_name) or 0
                    decl_slots[id(st)] = LocalSlot(next_idx, length)
                    next_idx += length if length else 1
                elif isinstance(st, A.If):
                    visit(st.then_block)
                    if st.else_block:
                        visit(st.else_block)
                elif isinstance(st, A.While):
                    visit(st.body)

        visit(fn.body)
        return FunctionLayout(
            name=fn.name,
            num_locals=next_idx,
            num_params=len(fn.params),
            params=params,
            decl_slots=decl_slots,
        )

    def _emit_function(self, fn: A.Function, layout: FunctionLayout, ctx: Context):
        # The function body shares a scope with the parameters, matching sema.
        self._scopes = [dict(layout.params)]
        for st in fn.body:
            self._emit_stmt(st, layout, ctx)
        # Fall-through epilogue. Every function returns exactly one value, so
        # this runs even for void functions; the caller discards it.
        self.code.append(Instruction(OpCode.PUSH_INT, 0))
        self.code.append(Instruction(OpCode.RET))
        self._scopes = []

    # -- statements ------------------------------------------------------

    def _emit_stmt(self, st: A.Stmt, layout: FunctionLayout, ctx: Context):
        if isinstance(st, A.VarDecl):
            slot = layout.decl_slots[id(st)]
            if slot.is_array:
                self._declare(st.name, slot)
                for offset in range(slot.length):
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                    self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index + offset))
            else:
                # Evaluate the initializer before binding the name, so that
                # `let x = x + 1;` reads the outer x. This matches sema, which
                # analyzes the initializer before calling scope.define().
                if st.init is not None:
                    self._emit_expr(st.init, layout, ctx)
                else:
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                self._declare(st.name, slot)
                self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index))
        elif isinstance(st, A.Assign):
            if isinstance(st.target, A.Identifier):
                slot = self._lookup_or_fail(st.target.name, st.target)
                if slot.is_array:
                    raise CodegenError(
                        f"[{st.target.line}:{st.target.col}] Cannot assign to array '{st.target.name}' as a whole"
                    )
                self._emit_expr(st.value, layout, ctx)
                self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index))
            elif isinstance(st.target, A.Index):
                slot = self._array_slot(st.target.array)
                # STORE_LOCAL_IDX pops the index, then the value.
                self._emit_expr(st.value, layout, ctx)
                self._emit_expr(st.target.index, layout, ctx)
                self.code.append(Instruction(OpCode.STORE_LOCAL_IDX, slot.index))
            else:
                raise CodegenError(f"[{st.line}:{st.col}] Invalid assignment target")
        elif isinstance(st, A.Print):
            self._emit_expr(st.value, layout, ctx)
            t = ctx.get_type(st.value)
            if t == Str:
                self.code.append(Instruction(OpCode.PRINT_STR))
            elif t == Bool:
                self._emit_bool_to_str()
                self.code.append(Instruction(OpCode.PRINT_STR))
            else:
                self.code.append(Instruction(OpCode.PRINT_INT))
        elif isinstance(st, A.PrintLn):
            self._emit_expr(st.value, layout, ctx)
            t = ctx.get_type(st.value)
            if t == Str:
                self.code.append(Instruction(OpCode.PRINTLN_STR))
            elif t == Bool:
                self._emit_bool_to_str()
                self.code.append(Instruction(OpCode.PRINTLN_STR))
            else:
                self.code.append(Instruction(OpCode.PRINTLN_INT))
        elif isinstance(st, A.Return):
            if st.value is not None:
                self._emit_expr(st.value, layout, ctx)
            else:
                # Void return still yields a value, for a uniform RET.
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
            self.code.append(Instruction(OpCode.RET))
        elif isinstance(st, A.ExprStmt):
            self._emit_expr(st.expr, layout, ctx)
            # Every expression leaves exactly one value, including void calls
            # and void builtins, so the result is always discarded here.
            self.code.append(Instruction(OpCode.POP))
        elif isinstance(st, A.If):
            self._emit_if(st, layout, ctx)
        elif isinstance(st, A.While):
            self._emit_while(st, layout, ctx)
        elif isinstance(st, A.InlineAsm):
            # VM backend ignores raw 8086 inline asm; only the 8086 backend executes it.
            return
        elif isinstance(st, A.VmAsm):
            self._emit_vm_asm(st, layout)
        else:
            raise CodegenError(
                f"[{st.line}:{st.col}] Unsupported statement type {type(st).__name__}"
            )

    def _emit_if(self, st: A.If, layout: FunctionLayout, ctx: Context):
        self._emit_expr(st.cond, layout, ctx)
        jz_index = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))  # arg to be patched
        self._push_scope()
        for s in st.then_block:
            self._emit_stmt(s, layout, ctx)
        self._pop_scope()
        # jump over else
        jmp_index = len(self.code)
        self.code.append(Instruction(OpCode.JMP, 0))
        # patch JZ to else start
        self.code[jz_index].arg = len(self.code)
        if st.else_block:
            self._push_scope()
            for s in st.else_block:
                self._emit_stmt(s, layout, ctx)
            self._pop_scope()
        self.code[jmp_index].arg = len(self.code)

    def _emit_while(self, st: A.While, layout: FunctionLayout, ctx: Context):
        loop_start = len(self.code)
        self._emit_expr(st.cond, layout, ctx)
        jz_index = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))
        self._push_scope()
        for s in st.body:
            self._emit_stmt(s, layout, ctx)
        self._pop_scope()
        self.code.append(Instruction(OpCode.JMP, loop_start))
        self.code[jz_index].arg = len(self.code)

    def _emit_vm_asm(self, vm_asm: A.VmAsm, layout: FunctionLayout) -> None:
        """Lower a vm_asm inline block into VM bytecode.

        Supported v1 instructions (line-based, each ending with ';'):
          - push_int N;
          - load_local NAME;
          - store_local NAME;
          - add; sub; mul; div; neg; not;
          - cmp_eq; cmp_ne; cmp_lt; cmp_le; cmp_gt; cmp_ge;

        Lines are parsed by splitting on whitespace; semicolons are kept by the
        parser but are not semantically significant here.
        """
        simple_ops = {
            "add": OpCode.ADD,
            "sub": OpCode.SUB,
            "mul": OpCode.MUL,
            "div": OpCode.DIV,
            "neg": OpCode.NEG,
            "not": OpCode.NOT,
            "cmp_eq": OpCode.CMP_EQ,
            "cmp_ne": OpCode.CMP_NE,
            "cmp_lt": OpCode.CMP_LT,
            "cmp_le": OpCode.CMP_LE,
            "cmp_gt": OpCode.CMP_GT,
            "cmp_ge": OpCode.CMP_GE,
        }
        local_ops = {
            "load_local": OpCode.LOAD_LOCAL,
            "store_local": OpCode.STORE_LOCAL,
        }

        for raw in vm_asm.code.splitlines():
            line = raw.strip()
            if line.endswith(";"):
                line = line[:-1].strip()
            if not line:
                continue
            parts = line.split()
            op, args = parts[0], parts[1:]

            if op == "push_int" and len(args) == 1:
                try:
                    value = int(args[0], 0)
                except ValueError:
                    raise CodegenError(
                        f"[{vm_asm.line}:{vm_asm.col}] vm_asm push_int expects an integer literal, got '{args[0]}'"
                    )
                self.code.append(Instruction(OpCode.PUSH_INT, value & 0xFFFF))
            elif op in local_ops and len(args) == 1:
                name = args[0]
                slot = self._lookup(name)
                if slot is None:
                    raise CodegenError(
                        f"[{vm_asm.line}:{vm_asm.col}] vm_asm {op}: unknown local '{name}'"
                    )
                if slot.is_array:
                    raise CodegenError(
                        f"[{vm_asm.line}:{vm_asm.col}] vm_asm {op}: '{name}' is an array; index it explicitly"
                    )
                self.code.append(Instruction(local_ops[op], slot.index))
            elif op in simple_ops and not args:
                self.code.append(Instruction(simple_ops[op]))
            else:
                raise CodegenError(
                    f"[{vm_asm.line}:{vm_asm.col}] Unknown or malformed vm_asm instruction: '{raw.strip()}'"
                )

    def _emit_bool_to_str(self) -> None:
        """Replace a 0/1 on top of the stack with the string id for 'false'/'true'."""
        true_sid = self._add_string("true")
        false_sid = self._add_string("false")
        jz_idx = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))  # placeholder
        self.code.append(Instruction(OpCode.PUSH_INT, true_sid))
        jmp_idx = len(self.code)
        self.code.append(Instruction(OpCode.JMP, 0))  # placeholder
        false_pc = len(self.code)
        self.code.append(Instruction(OpCode.PUSH_INT, false_sid))
        self.code[jz_idx].arg = false_pc
        self.code[jmp_idx].arg = len(self.code)

    # -- expressions -----------------------------------------------------

    def _emit_expr(self, e: A.Expr, layout: FunctionLayout, ctx: Context):
        if isinstance(e, A.Literal):
            if isinstance(e.value, bool):
                self.code.append(Instruction(OpCode.PUSH_INT, 1 if e.value else 0))
            elif isinstance(e.value, int):
                self.code.append(Instruction(OpCode.PUSH_INT, e.value & 0xFFFF))
            elif isinstance(e.value, str):
                self.code.append(Instruction(OpCode.PUSH_INT, self._add_string(e.value)))
            else:
                raise CodegenError(
                    f"[{e.line}:{e.col}] Unsupported literal {e.value!r}"
                )
        elif isinstance(e, A.Identifier):
            slot = self._lookup_or_fail(e.name, e)
            if slot.is_array:
                raise CodegenError(
                    f"[{e.line}:{e.col}] Array '{e.name}' has no value form; index it or take its address"
                )
            self.code.append(Instruction(OpCode.LOAD_LOCAL, slot.index))
        elif isinstance(e, A.AddressOf):
            # A pointer is a local index into the current frame.
            if isinstance(e.target, A.Identifier):
                slot = self._lookup_or_fail(e.target.name, e.target)
                self.code.append(Instruction(OpCode.PUSH_INT, slot.index))
            elif isinstance(e.target, A.Index):
                slot = self._array_slot(e.target.array)
                # pointer = base + index
                self._emit_expr(e.target.index, layout, ctx)
                self.code.append(Instruction(OpCode.PUSH_INT, slot.index))
                self.code.append(Instruction(OpCode.ADD))
            else:
                raise CodegenError(
                    f"[{e.line}:{e.col}] Can only take the address of a variable or array element"
                )
        elif isinstance(e, A.Unary):
            self._emit_expr(e.right, layout, ctx)
            if e.op == '-':
                self.code.append(Instruction(OpCode.NEG))
            elif e.op == '!':
                self.code.append(Instruction(OpCode.NOT))
            else:
                raise CodegenError(f"[{e.line}:{e.col}] Unknown unary operator '{e.op}'")
        elif isinstance(e, A.Binary):
            self._emit_binary(e, layout, ctx)
        elif isinstance(e, A.Index):
            slot = self._array_slot(e.array)
            self._emit_expr(e.index, layout, ctx)
            self.code.append(Instruction(OpCode.LOAD_LOCAL_IDX, slot.index))
        elif isinstance(e, A.Call):
            self._emit_call(e, layout, ctx)
        else:
            raise CodegenError(
                f"[{e.line}:{e.col}] Unsupported expression type {type(e).__name__}"
            )

    def _emit_binary(self, e: A.Binary, layout: FunctionLayout, ctx: Context):
        if e.op == '&&':
            # Evaluate left; if false, skip right and yield 0.
            self._emit_expr(e.left, layout, ctx)
            jz_index = len(self.code)
            self.code.append(Instruction(OpCode.JZ, 0))
            self._emit_expr(e.right, layout, ctx)
            jz2_index = len(self.code)
            self.code.append(Instruction(OpCode.JZ, 0))
            self.code.append(Instruction(OpCode.PUSH_INT, 1))
            jmp_end_index = len(self.code)
            self.code.append(Instruction(OpCode.JMP, 0))
            false_pc = len(self.code)
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            self.code[jz_index].arg = false_pc
            self.code[jz2_index].arg = false_pc
            self.code[jmp_end_index].arg = len(self.code)
            return
        if e.op == '||':
            # Evaluate left; if true, skip right and yield 1.
            self._emit_expr(e.left, layout, ctx)
            jnz_index = len(self.code)
            self.code.append(Instruction(OpCode.JNZ, 0))
            self._emit_expr(e.right, layout, ctx)
            jnz2_index = len(self.code)
            self.code.append(Instruction(OpCode.JNZ, 0))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            jmp_end_index = len(self.code)
            self.code.append(Instruction(OpCode.JMP, 0))
            true_pc = len(self.code)
            self.code.append(Instruction(OpCode.PUSH_INT, 1))
            self.code[jnz_index].arg = true_pc
            self.code[jnz2_index].arg = true_pc
            self.code[jmp_end_index].arg = len(self.code)
            return

        binary_ops = {
            '+': OpCode.ADD,
            '-': OpCode.SUB,
            '*': OpCode.MUL,
            '/': OpCode.DIV,
            '%': OpCode.MOD,
            '==': OpCode.CMP_EQ,
            '!=': OpCode.CMP_NE,
            '<': OpCode.CMP_LT,
            '<=': OpCode.CMP_LE,
            '>': OpCode.CMP_GT,
            '>=': OpCode.CMP_GE,
        }
        if e.op not in binary_ops:
            raise CodegenError(f"[{e.line}:{e.col}] Unknown binary operator '{e.op}'")
        self._emit_expr(e.left, layout, ctx)
        self._emit_expr(e.right, layout, ctx)
        self.code.append(Instruction(binary_ops[e.op]))

    def _emit_call(self, e: A.Call, layout: FunctionLayout, ctx: Context):
        name = e.callee

        # array_push(xs: int[N], len: int, value: int) -> int (new len)
        if name == "array_push" and len(e.args) == 3:
            arr_expr, len_expr, val_expr = e.args
            slot = self._array_slot(arr_expr)
            # Evaluate len once and duplicate it: it is needed both as the
            # store index and as the basis for the returned new length.
            self._emit_expr(len_expr, layout, ctx)      # [len]
            self.code.append(Instruction(OpCode.DUP))   # [len, len]
            self._emit_expr(val_expr, layout, ctx)      # [len, len, value]
            self.code.append(Instruction(OpCode.SWAP))  # [len, value, len]
            self.code.append(Instruction(OpCode.STORE_LOCAL_IDX, slot.index))  # [len]
            self.code.append(Instruction(OpCode.PUSH_INT, 1))
            self.code.append(Instruction(OpCode.ADD))   # [len + 1]
            return

        # array_pop(xs: int[N], len: int) -> int (popped value)
        if name == "array_pop" and len(e.args) == 2:
            arr_expr, len_expr = e.args
            slot = self._array_slot(arr_expr)
            self._emit_expr(len_expr, layout, ctx)
            self.code.append(Instruction(OpCode.PUSH_INT, 1))
            self.code.append(Instruction(OpCode.SUB))   # len - 1
            self.code.append(Instruction(OpCode.LOAD_LOCAL_IDX, slot.index))
            return

        # Pointer/memory intrinsics operating on frame locals.
        if name == "load16" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.LOAD_INDIRECT))
            return
        if name == "store16" and len(e.args) == 2:
            # STORE_INDIRECT pops the value, then the pointer.
            self._emit_expr(e.args[0], layout, ctx)   # ptr
            self._emit_expr(e.args[1], layout, ctx)   # value
            self.code.append(Instruction(OpCode.STORE_INDIRECT))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))  # void result
            return
        if name == "memcpy" and len(e.args) == 3:
            self._emit_expr(e.args[0], layout, ctx)  # dst
            self._emit_expr(e.args[1], layout, ctx)  # src
            self._emit_expr(e.args[2], layout, ctx)  # count, in slots
            self.code.append(Instruction(OpCode.MEMCPY_LOCALS))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            return
        if name == "memset" and len(e.args) == 3:
            self._emit_expr(e.args[0], layout, ctx)  # dst
            self._emit_expr(e.args[1], layout, ctx)  # value
            self._emit_expr(e.args[2], layout, ctx)  # count, in slots
            self.code.append(Instruction(OpCode.MEMSET_LOCALS))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            return

        # Constant-time-style primitives (semantics only; timing depends on backend).
        if name == "ct_eq" and len(e.args) == 2:
            self._emit_expr(e.args[0], layout, ctx)
            self._emit_expr(e.args[1], layout, ctx)
            self.code.append(Instruction(OpCode.CMP_EQ))
            return
        if name == "ct_select" and len(e.args) == 3:
            # ct_select(mask, x, y) == y + mask * (x - y), for mask in {0, 1}.
            mask_expr, x_expr, y_expr = e.args
            self._emit_expr(x_expr, layout, ctx)
            self._emit_expr(y_expr, layout, ctx)
            self.code.append(Instruction(OpCode.SUB))   # x - y
            self._emit_expr(mask_expr, layout, ctx)
            self.code.append(Instruction(OpCode.MUL))   # (x - y) * mask
            self._emit_expr(y_expr, layout, ctx)
            self.code.append(Instruction(OpCode.ADD))
            return

        # Heap allocation and access.
        if name == "alloc" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.ALLOC))
            return
        if name == "heap_load" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.HEAP_LOAD))
            return
        if name == "heap_store" and len(e.args) == 2:
            self._emit_expr(e.args[0], layout, ctx)   # addr
            self._emit_expr(e.args[1], layout, ctx)   # value
            self.code.append(Instruction(OpCode.HEAP_STORE))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))  # void result
            return

        # Regular user-defined call: evaluate args left to right, then CALL.
        if name not in self.func_name_to_index:
            raise CodegenError(f"[{e.line}:{e.col}] Call to unknown function '{name}'")
        for arg_expr in e.args:
            self._emit_expr(arg_expr, layout, ctx)
        self.code.append(Instruction(OpCode.CALL, self.func_name_to_index[name]))
