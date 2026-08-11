from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
from . import ast as A
from .bytecode import OpCode, Instruction, Bytecode
from .sema import Context, Symbol
from .compiler_types import Int, Str, Bool, Void, array_length


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
class LoopContext:
    """The jump sites inside one loop that only its end knows how to patch.

    `break` and `continue` are emitted before their targets exist, so each one
    records the index of its JMP here and the enclosing loop fills in the
    address once it has finished emitting.
    """
    break_sites: List[int] = field(default_factory=list)
    continue_sites: List[int] = field(default_factory=list)


@dataclass
class FunctionLayout:
    name: str
    num_locals: int
    num_params: int
    entry_pc: int = 0
    # Symbol -> slot, for every symbol sema recorded in this frame. Keyed by
    # the Symbol object rather than by name, so shadowed and sibling-scope
    # declarations get distinct storage for free.
    slots: Dict[Symbol, LocalSlot] = field(default_factory=dict)


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
        # Enclosing loops, innermost last: break/continue bind to the last one.
        self._loops: List[LoopContext] = []

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

    # -- slot lookup -----------------------------------------------------
    #
    # Scoping lives entirely in sema. Codegen only maps the Symbol that sema
    # already resolved a node to onto a frame slot, so the two passes cannot
    # disagree about what a name refers to.

    def _slot(self, node: A.Node, layout: FunctionLayout, ctx: Context) -> LocalSlot:
        sym = ctx.binding_of(node)
        if sym is None:
            raise CodegenError(
                f"[{node.line}:{node.col}] No binding recorded for this node; "
                f"semantic analysis did not resolve it"
            )
        slot = layout.slots.get(sym)
        if slot is None:
            raise CodegenError(
                f"[{node.line}:{node.col}] Symbol '{sym.name}' has no slot in "
                f"function '{layout.name}'"
            )
        return slot

    def _array_slot(self, e: A.Expr, layout: FunctionLayout, ctx: Context) -> LocalSlot:
        if not isinstance(e, A.Identifier):
            raise CodegenError(
                f"[{e.line}:{e.col}] Only named local arrays can be indexed"
            )
        slot = self._slot(e, layout, ctx)
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
            self.functions.append(self._build_layout(fn, ctx))

        for fn, layout in zip(program.functions, self.functions):
            layout.entry_pc = len(self.code)
            self._emit_function(fn, layout, ctx)

        from runtime.vm import FunctionInfo
        fns = [
            FunctionInfo(fl.name, fl.entry_pc, fl.num_locals, fl.num_params)
            for fl in self.functions
        ]
        return self.code, fns, self.strings

    def _build_layout(self, fn: A.Function, ctx: Context) -> FunctionLayout:
        """Give every symbol sema found in this frame its own slot.

        Sema lists parameters first, which the calling convention requires:
        CALL drops arguments into the callee's leading locals. Slots are never
        reused across sibling scopes, so two declarations of the same name
        cannot collide.
        """
        symbols = ctx.frame_symbols.get(fn.name)
        if symbols is None:
            raise CodegenError(
                f"[{fn.line}:{fn.col}] No frame recorded for function '{fn.name}'"
            )

        slots: Dict[Symbol, LocalSlot] = {}
        next_idx = 0
        for sym in symbols:
            length = array_length(sym.type) or 0
            slots[sym] = LocalSlot(next_idx, length)
            next_idx += length if length else 1

        return FunctionLayout(
            name=fn.name,
            num_locals=next_idx,
            num_params=len(fn.params),
            slots=slots,
        )

    def _emit_function(self, fn: A.Function, layout: FunctionLayout, ctx: Context):
        for st in fn.body:
            self._emit_stmt(st, layout, ctx)
        # Fall-through epilogue. Every function returns exactly one value, so
        # this runs even for void functions; the caller discards it.
        self.code.append(Instruction(OpCode.PUSH_INT, 0))
        self.code.append(Instruction(OpCode.RET))

    # -- statements ------------------------------------------------------

    def _emit_stmt(self, st: A.Stmt, layout: FunctionLayout, ctx: Context):
        if isinstance(st, A.VarDecl):
            slot = self._slot(st, layout, ctx)
            if slot.is_array:
                for offset in range(slot.length):
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                    self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index + offset))
            else:
                # `let x = x + 1;` reads the outer x: sema resolved the
                # initializer's identifiers before defining this one, so they
                # already point at the outer symbol.
                if st.init is not None:
                    self._emit_expr(st.init, layout, ctx)
                else:
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index))
        elif isinstance(st, A.Assign):
            if isinstance(st.target, A.Identifier):
                slot = self._slot(st.target, layout, ctx)
                if slot.is_array:
                    raise CodegenError(
                        f"[{st.target.line}:{st.target.col}] Cannot assign to array '{st.target.name}' as a whole"
                    )
                self._emit_expr(st.value, layout, ctx)
                self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index))
            elif isinstance(st.target, A.Index):
                slot = self._array_slot(st.target.array, layout, ctx)
                # STORE_LOCAL_IDX pops the index, then the value.
                self._emit_expr(st.value, layout, ctx)
                self._emit_expr(st.target.index, layout, ctx)
                self.code.append(Instruction(OpCode.BOUNDS_CHECK, slot.length))
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
        elif isinstance(st, A.For):
            self._emit_for(st, layout, ctx)
        elif isinstance(st, A.Block):
            # A block is only a scope, and scoping is already settled: sema gave
            # its declarations their own symbols, so there is nothing to emit
            # beyond the statements themselves.
            for s in st.stmts:
                self._emit_stmt(s, layout, ctx)
        elif isinstance(st, A.Break):
            self._emit_loop_jump(st, "break")
        elif isinstance(st, A.Continue):
            self._emit_loop_jump(st, "continue")
        elif isinstance(st, A.VmAsm):
            self._emit_vm_asm(st, layout, ctx)
        else:
            raise CodegenError(
                f"[{st.line}:{st.col}] Unsupported statement type {type(st).__name__}"
            )

    def _emit_if(self, st: A.If, layout: FunctionLayout, ctx: Context):
        self._emit_expr(st.cond, layout, ctx)
        jz_index = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))  # arg to be patched
        for s in st.then_block:
            self._emit_stmt(s, layout, ctx)
        # jump over else
        jmp_index = len(self.code)
        self.code.append(Instruction(OpCode.JMP, 0))
        # patch JZ to else start
        self.code[jz_index].arg = len(self.code)
        if st.else_block:
            for s in st.else_block:
                self._emit_stmt(s, layout, ctx)
        self.code[jmp_index].arg = len(self.code)

    def _emit_loop_jump(self, st: A.Stmt, kind: str):
        """Emit the JMP for a break or continue, to be patched by its loop."""
        if not self._loops:
            # Sema rejects this already; reaching it means the two passes
            # disagree about what encloses this statement.
            raise CodegenError(f"[{st.line}:{st.col}] '{kind}' outside of a loop")
        sites = self._loops[-1].break_sites if kind == "break" else self._loops[-1].continue_sites
        sites.append(len(self.code))
        self.code.append(Instruction(OpCode.JMP, 0))  # arg to be patched

    def _patch_loop(self, loop: LoopContext, break_pc: int, continue_pc: int):
        for site in loop.break_sites:
            self.code[site].arg = break_pc
        for site in loop.continue_sites:
            self.code[site].arg = continue_pc

    def _emit_while(self, st: A.While, layout: FunctionLayout, ctx: Context):
        loop_start = len(self.code)
        self._emit_expr(st.cond, layout, ctx)
        jz_index = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))
        loop = LoopContext()
        self._loops.append(loop)
        for s in st.body:
            self._emit_stmt(s, layout, ctx)
        self._loops.pop()
        self.code.append(Instruction(OpCode.JMP, loop_start))
        end_pc = len(self.code)
        self.code[jz_index].arg = end_pc
        # `continue` re-tests the condition, which is where the loop starts.
        self._patch_loop(loop, break_pc=end_pc, continue_pc=loop_start)

    def _emit_for(self, st: A.For, layout: FunctionLayout, ctx: Context):
        if st.init is not None:
            self._emit_stmt(st.init, layout, ctx)
        loop_start = len(self.code)
        jz_index = None
        if st.cond is not None:
            self._emit_expr(st.cond, layout, ctx)
            jz_index = len(self.code)
            self.code.append(Instruction(OpCode.JZ, 0))
        loop = LoopContext()
        self._loops.append(loop)
        for s in st.body:
            self._emit_stmt(s, layout, ctx)
        self._loops.pop()
        # `continue` lands on the step, not on the condition, so skipping the
        # rest of an iteration still advances the loop.
        step_pc = len(self.code)
        if st.step is not None:
            self._emit_stmt(st.step, layout, ctx)
        self.code.append(Instruction(OpCode.JMP, loop_start))
        end_pc = len(self.code)
        if jz_index is not None:
            self.code[jz_index].arg = end_pc
        # With no condition there is no JZ to patch: the only way out is `break`.
        self._patch_loop(loop, break_pc=end_pc, continue_pc=step_pc)

    def _emit_vm_asm(self, vm_asm: A.VmAsm, layout: FunctionLayout, ctx: Context) -> None:
        """Lower a vm_asm inline block into VM bytecode.

        Supported v1 instructions (line-based, each ending with ';'):
          - push_int N;
          - load_local NAME;
          - store_local NAME;
          - add; sub; mul; div; neg; not;
          - cmp_eq; cmp_ne; cmp_lt; cmp_le; cmp_gt; cmp_ge;

        Lines are parsed by splitting on whitespace; semicolons are kept by the
        parser but are not semantically significant here.

        The body is raw text, so sema cannot resolve its names as it walks
        expressions. Instead it records the scope in effect at this block, and
        NAME is looked up there.
        """
        visible = ctx.asm_scope.get(id(vm_asm))
        if visible is None:
            raise CodegenError(
                f"[{vm_asm.line}:{vm_asm.col}] No scope recorded for this vm_asm block"
            )
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
                sym = visible.get(name)
                if sym is None:
                    raise CodegenError(
                        f"[{vm_asm.line}:{vm_asm.col}] vm_asm {op}: unknown local '{name}'"
                    )
                slot = layout.slots[sym]
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
            if e.value is None:
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
            elif isinstance(e.value, bool):
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
            slot = self._slot(e, layout, ctx)
            if slot.is_array:
                raise CodegenError(
                    f"[{e.line}:{e.col}] Array '{e.name}' has no value form; index it or take its address"
                )
            self.code.append(Instruction(OpCode.LOAD_LOCAL, slot.index))
        elif isinstance(e, A.AddressOf):
            # A pointer is a local index into the current frame.
            if isinstance(e.target, A.Identifier):
                slot = self._slot(e.target, layout, ctx)
                self.code.append(Instruction(OpCode.PUSH_INT, slot.index))
            elif isinstance(e.target, A.Index):
                slot = self._array_slot(e.target.array, layout, ctx)
                # pointer = base + index
                self._emit_expr(e.target.index, layout, ctx)
                self.code.append(Instruction(OpCode.BOUNDS_CHECK, slot.length))
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
            elif e.op == '~':
                self.code.append(Instruction(OpCode.BITNOT))
            else:
                raise CodegenError(f"[{e.line}:{e.col}] Unknown unary operator '{e.op}'")
        elif isinstance(e, A.Binary):
            self._emit_binary(e, layout, ctx)
        elif isinstance(e, A.Index):
            slot = self._array_slot(e.array, layout, ctx)
            self._emit_expr(e.index, layout, ctx)
            self.code.append(Instruction(OpCode.BOUNDS_CHECK, slot.length))
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
            '^': OpCode.XOR,
            '&': OpCode.AND,
            '|': OpCode.OR,
            '<<': OpCode.SHL,
            '>>': OpCode.SHR,
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
            slot = self._array_slot(arr_expr, layout, ctx)
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
            slot = self._array_slot(arr_expr, layout, ctx)
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
