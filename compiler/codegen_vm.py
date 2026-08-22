from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import Dict, List
from . import ast as A
from .bytecode import OpCode, Instruction, Bytecode
from .sema import Context, Symbol
from .compiler_types import (
    Int, Str, Bool, Float, Void, array_length, is_reference_type, word_count,
)


COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


class CodegenError(Exception):
    """Usually a hole in semantic analysis rather than a user error: by the
    time codegen runs, names and types are supposed to be resolved. Failing
    loudly beats emitting code that quietly computes the wrong answer."""


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
    # How many scopes were open when this loop began, so a break or continue
    # knows how many it is jumping out of and must release first.
    scope_depth: int = 0


@dataclass
class FunctionLayout:
    name: str
    num_locals: int
    # Arguments, which is also how many operand-stack entries CALL pops: a
    # float is one entry there even though it is two slots once stored.
    num_params: int
    # Slots each parameter occupies, in order. CALL needs it to scatter one
    # entry per argument into leading locals of differing width.
    param_words: tuple = ()
    entry_pc: int = 0
    # Slots in this frame that hold heap references, for the GC stack map.
    ref_slots: List[int] = field(default_factory=list)
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
        self.func_name_to_index: Dict[str, int] = {}
        # Enclosing loops, innermost last: break/continue bind to the last one.
        self._loops: List[LoopContext] = []
        # Scopes currently open, outermost first. Used to release a scope's
        # references when a break or continue leaves it early.
        self._scopes: List[object] = []

    # -- string table ----------------------------------------------------

    def _add_string(self, value: str) -> int:
        """Intern a string literal, returning its id, so the table does not
        grow per call site."""
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

    @staticmethod
    def _is_float(node, ctx: Context) -> bool:
        """Whether codegen should use the float form of an opcode here.

        Sema typed every expression, so this is a lookup rather than a guess.
        A node sema never typed (an assignment target, say) is not a float.
        """
        return ctx.node_type.get(id(node)) == Float

    @staticmethod
    def _float_bits(value: float) -> int:
        """A Python float as the 32-bit IEEE 754 pattern the VM stores.

        The lexer already rejected a literal too large for a float, so the
        pack cannot overflow here.
        """
        return struct.unpack("<I", struct.pack("<f", value))[0]

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

        from runtime.vm import FunctionInfo, StructLayout
        fns = [
            FunctionInfo(fl.name, fl.entry_pc, fl.num_locals, fl.num_params,
                         tuple(fl.ref_slots), fl.param_words)
            for fl in self.functions
        ]
        # The struct table doubles as the collector's object map: it gives an
        # object's size and which of its words are references.
        layouts = [None] * len(ctx.structs)
        for info in ctx.structs.values():
            layouts[info.type_id] = StructLayout(
                name=info.name,
                word_size=info.word_size,
                ref_offsets=tuple(f.offset for f in info.fields if is_reference_type(f.type)),
            )
        return self.code, fns, self.strings, layouts

    def _build_layout(self, fn: A.Function, ctx: Context) -> FunctionLayout:
        """Give every symbol sema found in this frame its own slot.

        Parameters come first because CALL drops arguments into the callee's
        leading locals. Slots are never reused across sibling scopes, so two
        declarations of the same name cannot collide.
        """
        symbols = ctx.frame_symbols.get(fn.name)
        if symbols is None:
            raise CodegenError(
                f"[{fn.line}:{fn.col}] No frame recorded for function '{fn.name}'"
            )

        slots: Dict[Symbol, LocalSlot] = {}
        ref_slots: List[int] = []
        next_idx = 0
        for sym in symbols:
            length = array_length(sym.type) or 0
            slots[sym] = LocalSlot(next_idx, length)
            if is_reference_type(sym.type):
                ref_slots.append(next_idx)
            # An array is `length` int slots; anything else is as wide as its
            # type, which is one slot for everything but float.
            next_idx += length if length else word_count(sym.type)

        return FunctionLayout(
            name=fn.name,
            num_locals=next_idx,
            num_params=len(fn.params),
            param_words=tuple(word_count(sym.type) for sym in symbols[:len(fn.params)]),
            slots=slots,
            ref_slots=ref_slots,
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
                sym = ctx.binding_of(st)
                declared_float = sym is not None and sym.type == Float
                if st.init is not None:
                    self._emit_expr(st.init, layout, ctx)
                elif sym is not None and sym.type == Str:
                    # Zero would be the null address. A str has no null, so an
                    # uninitialised one is the empty string.
                    self.code.append(Instruction(OpCode.LOAD_STR, self._add_string("")))
                elif declared_float:
                    # All-zero bits are 0.0, but PUSH_INT would leave a 16-bit
                    # zero where a 32-bit pattern belongs.
                    self.code.append(Instruction(OpCode.PUSH_FLOAT, 0))
                else:
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                self.code.append(Instruction(
                    OpCode.STORE_LOCAL_F if declared_float else OpCode.STORE_LOCAL,
                    slot.index))
        elif isinstance(st, A.Assign):
            if isinstance(st.target, A.Identifier):
                slot = self._slot(st.target, layout, ctx)
                if slot.is_array:
                    raise CodegenError(
                        f"[{st.target.line}:{st.target.col}] Cannot assign to array '{st.target.name}' as a whole"
                    )
                self._emit_expr(st.value, layout, ctx)
                self.code.append(Instruction(
                    OpCode.STORE_LOCAL_F if self._is_float(st.value, ctx) else OpCode.STORE_LOCAL,
                    slot.index))
            elif isinstance(st.target, A.Index):
                slot = self._array_slot(st.target.array, layout, ctx)
                # STORE_LOCAL_IDX pops the index, then the value.
                self._emit_expr(st.value, layout, ctx)
                self._emit_expr(st.target.index, layout, ctx)
                self.code.append(Instruction(OpCode.BOUNDS_CHECK, slot.length))
                self.code.append(Instruction(OpCode.STORE_LOCAL_IDX, slot.index))
            elif isinstance(st.target, A.FieldAccess):
                # HEAP_STORE_FIELD pops the value, then the object reference.
                fld = self._field_of(st.target, ctx)
                self._emit_expr(st.target.obj, layout, ctx)
                self._emit_expr(st.value, layout, ctx)
                self.code.append(Instruction(
                    OpCode.HEAP_STORE_FIELD_F if fld.type == Float else OpCode.HEAP_STORE_FIELD,
                    fld.offset))
            else:
                raise CodegenError(f"[{st.line}:{st.col}] Invalid assignment target")
        elif isinstance(st, A.Print):
            self._emit_expr(st.value, layout, ctx)
            t = ctx.get_type(st.value)
            if t == Str:
                self.code.append(Instruction(OpCode.PRINT_STR))
            elif t == Float:
                self.code.append(Instruction(OpCode.PRINT_FLOAT))
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
            elif t == Float:
                self.code.append(Instruction(OpCode.PRINTLN_FLOAT))
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
            # A block is only a scope: sema already gave its declarations their
            # own symbols, so all that is left is emitting and releasing.
            self._emit_scoped_block(st.stmts, layout, ctx)
        elif isinstance(st, A.Break):
            self._emit_loop_jump(st, "break", layout, ctx)
        elif isinstance(st, A.Continue):
            self._emit_loop_jump(st, "continue", layout, ctx)
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
        self._emit_scoped_block(st.then_block, layout, ctx)
        jmp_index = len(self.code)
        self.code.append(Instruction(OpCode.JMP, 0))
        self.code[jz_index].arg = len(self.code)
        if st.else_block:
            self._emit_scoped_block(st.else_block, layout, ctx)
        self.code[jmp_index].arg = len(self.code)

    def _release_scope(self, key, layout: FunctionLayout, ctx: Context):
        """Store null into the reference slots a scope declared, so a name that
        has gone out of scope stops rooting whatever it named. Without this a
        loop body's last object outlives the loop entirely.

        This only removes one root; an object reachable another way is
        unaffected.
        """
        for sym in ctx.scope_refs.get(id(key), ()):
            slot = layout.slots.get(sym)
            if slot is None:
                continue
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            self.code.append(Instruction(OpCode.STORE_LOCAL, slot.index))

    def _emit_scoped_block(self, stmts: List[A.Stmt], layout: FunctionLayout, ctx: Context):
        """Emit a block's statements, then release the references it declared."""
        self._scopes.append(stmts)
        for s in stmts:
            self._emit_stmt(s, layout, ctx)
        self._scopes.pop()
        self._release_scope(stmts, layout, ctx)

    def _release_scopes_to(self, depth: int, layout: FunctionLayout, ctx: Context):
        """Release every scope open beyond `depth`, innermost first."""
        for key in reversed(self._scopes[depth:]):
            self._release_scope(key, layout, ctx)

    def _emit_loop_jump(self, st: A.Stmt, kind: str, layout: FunctionLayout, ctx: Context):
        """Emit the JMP for a break or continue, to be patched by its loop."""
        if not self._loops:
            # Sema rejects this already; reaching it means the two passes
            # disagree about what encloses this statement.
            raise CodegenError(f"[{st.line}:{st.col}] '{kind}' outside of a loop")
        loop = self._loops[-1]
        # The jump skips the ends of every scope between here and the loop, so
        # their references have to be released on the way out.
        self._release_scopes_to(loop.scope_depth, layout, ctx)
        sites = loop.break_sites if kind == "break" else loop.continue_sites
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
        loop = LoopContext(scope_depth=len(self._scopes))
        self._loops.append(loop)
        self._emit_scoped_block(st.body, layout, ctx)
        self._loops.pop()
        self.code.append(Instruction(OpCode.JMP, loop_start))
        end_pc = len(self.code)
        self.code[jz_index].arg = end_pc
        # `continue` re-tests the condition, which is where the loop starts.
        self._patch_loop(loop, break_pc=end_pc, continue_pc=loop_start)

    def _emit_for(self, st: A.For, layout: FunctionLayout, ctx: Context):
        # The init clause declares into a scope wrapping the whole loop.
        self._scopes.append(st)
        if st.init is not None:
            self._emit_stmt(st.init, layout, ctx)
        loop_start = len(self.code)
        jz_index = None
        if st.cond is not None:
            self._emit_expr(st.cond, layout, ctx)
            jz_index = len(self.code)
            self.code.append(Instruction(OpCode.JZ, 0))
        loop = LoopContext(scope_depth=len(self._scopes))
        self._loops.append(loop)
        self._emit_scoped_block(st.body, layout, ctx)
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
        # The init clause's scope wraps the whole loop, so it is released once
        # here rather than on each iteration. Both the condition-false path and
        # every break land on end_pc, just above this.
        self._scopes.pop()
        self._release_scope(st, layout, ctx)

    def _emit_vm_asm(self, vm_asm: A.VmAsm, layout: FunctionLayout, ctx: Context) -> None:
        """Lower a vm_asm block to bytecode. The accepted instructions are
        `push_int` plus the simple_ops and local_ops tables below; anything
        else is an error.

        The body is raw text, so sema cannot resolve its names while walking
        expressions. It records the scope in effect at this block instead, and
        NAME is looked up there.

        A block is straight-line -- there are no jumps in the instruction set --
        so its effect on the operand stack is exactly the sum of its parts, and
        both underflow and leftover residue are decided here rather than
        surfacing as 'Unbalanced operand stack at RET' at run time. Each table
        below therefore carries the opcode's stack effect next to the opcode,
        so the two cannot drift apart.
        """
        visible = ctx.asm_scope.get(id(vm_asm))
        if visible is None:
            raise CodegenError(
                f"[{vm_asm.line}:{vm_asm.col}] No scope recorded for this vm_asm block"
            )
        # name -> (opcode, operands popped, results pushed). Both halves
        # matter: `add` nets -1 but needs two operands present, so tracking
        # only the net effect would let a block with one value on the stack
        # reach past its own start.
        simple_ops = {
            "add": (OpCode.ADD, 2, 1),
            "sub": (OpCode.SUB, 2, 1),
            "mul": (OpCode.MUL, 2, 1),
            "div": (OpCode.DIV, 2, 1),
            "neg": (OpCode.NEG, 1, 1),
            "not": (OpCode.NOT, 1, 1),
            "cmp_eq": (OpCode.CMP_EQ, 2, 1),
            "cmp_ne": (OpCode.CMP_NE, 2, 1),
            "cmp_lt": (OpCode.CMP_LT, 2, 1),
            "cmp_le": (OpCode.CMP_LE, 2, 1),
            "cmp_gt": (OpCode.CMP_GT, 2, 1),
            "cmp_ge": (OpCode.CMP_GE, 2, 1),
        }
        local_ops = {
            "load_local": (OpCode.LOAD_LOCAL, 0, 1),
            "store_local": (OpCode.STORE_LOCAL, 1, 0),
        }
        depth = 0

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
                pops, pushes = 0, 1
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
                if sym.type == Float:
                    # load_local moves one slot, and a float is two. There is
                    # no float instruction in this table, so the block would
                    # silently work on half the value.
                    raise CodegenError(
                        f"[{vm_asm.line}:{vm_asm.col}] vm_asm {op}: '{name}' is a float, "
                        f"which is two slots wide; vm_asm only moves one"
                    )
                opcode, pops, pushes = local_ops[op]
                self.code.append(Instruction(opcode, slot.index))
            elif op in simple_ops and not args:
                opcode, pops, pushes = simple_ops[op]
                self.code.append(Instruction(opcode))
            else:
                raise CodegenError(
                    f"[{vm_asm.line}:{vm_asm.col}] Unknown or malformed vm_asm instruction: '{raw.strip()}'"
                )

            # Consuming more than the block itself pushed would reach into
            # whatever the enclosing frame left on the stack.
            if pops > depth:
                raise CodegenError(
                    f"[{vm_asm.line}:{vm_asm.col}] vm_asm '{line}' needs {pops} "
                    f"value(s) on the operand stack but the block has {depth}"
                )
            depth += pushes - pops

        if depth != 0:
            raise CodegenError(
                f"[{vm_asm.line}:{vm_asm.col}] vm_asm block leaves {depth} "
                f"value(s) on the operand stack; it must end balanced"
            )

    def _emit_bool_to_str(self) -> None:
        """Replace a 0/1 on top of the stack with the string id for 'false'/'true'."""
        true_sid = self._add_string("true")
        false_sid = self._add_string("false")
        jz_idx = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))  # placeholder
        self.code.append(Instruction(OpCode.LOAD_STR, true_sid))
        jmp_idx = len(self.code)
        self.code.append(Instruction(OpCode.JMP, 0))  # placeholder
        false_pc = len(self.code)
        self.code.append(Instruction(OpCode.LOAD_STR, false_sid))
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
            elif isinstance(e.value, float):
                self.code.append(Instruction(OpCode.PUSH_FLOAT, self._float_bits(e.value)))
            elif isinstance(e.value, str):
                # A str value is the heap address of a string object, which
                # only exists once the VM has materialised the literal table.
                self.code.append(Instruction(OpCode.LOAD_STR, self._add_string(e.value)))
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
            self.code.append(Instruction(
                OpCode.LOAD_LOCAL_F if self._is_float(e, ctx) else OpCode.LOAD_LOCAL,
                slot.index))
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
                self.code.append(Instruction(
                    OpCode.FNEG if self._is_float(e, ctx) else OpCode.NEG))
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
        elif isinstance(e, A.FieldAccess):
            fld = self._field_of(e, ctx)
            self._emit_expr(e.obj, layout, ctx)
            self.code.append(Instruction(
                OpCode.HEAP_LOAD_FIELD_F if fld.type == Float else OpCode.HEAP_LOAD_FIELD,
                fld.offset))
        elif isinstance(e, A.StructLit):
            self._emit_struct_lit(e, layout, ctx)
        elif isinstance(e, A.Call):
            self._emit_call(e, layout, ctx)
        else:
            raise CodegenError(
                f"[{e.line}:{e.col}] Unsupported expression type {type(e).__name__}"
            )

    def _field_of(self, e: A.FieldAccess, ctx: Context):
        """The StructField that sema resolved this access to."""
        obj_t = ctx.get_type(e.obj)
        info = ctx.structs.get(obj_t.name)
        if info is None:
            raise CodegenError(
                f"[{e.line}:{e.col}] '{obj_t}' is not a struct type"
            )
        fld = info.field_named(e.field)
        if fld is None:
            raise CodegenError(
                f"[{e.line}:{e.col}] Struct '{info.name}' has no field '{e.field}'"
            )
        return fld

    def _emit_struct_lit(self, e: A.StructLit, layout: FunctionLayout, ctx: Context):
        info = ctx.structs.get(e.struct_name)
        if info is None:
            raise CodegenError(f"[{e.line}:{e.col}] Unknown struct '{e.struct_name}'")
        # ALLOC_TYPED leaves the new object's address on the stack; each field
        # store consumes a copy of it, so the address survives to be the value
        # of the whole expression.
        self.code.append(Instruction(OpCode.ALLOC_TYPED, info.type_id))
        for fi in e.fields:  # written order, so side effects run left to right
            fld = info.field_named(fi.name)
            if fld is None:
                raise CodegenError(
                    f"[{fi.line}:{fi.col}] Struct '{info.name}' has no field '{fi.name}'"
                )
            self.code.append(Instruction(OpCode.DUP))
            self._emit_expr(fi.value, layout, ctx)
            self.code.append(Instruction(
                OpCode.HEAP_STORE_FIELD_F if fld.type == Float else OpCode.HEAP_STORE_FIELD,
                fld.offset))

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
        float_ops = {
            '+': OpCode.FADD,
            '-': OpCode.FSUB,
            '*': OpCode.FMUL,
            '/': OpCode.FDIV,
        }
        self._emit_expr(e.left, layout, ctx)
        self._emit_expr(e.right, layout, ctx)
        if e.op == '+' and ctx.get_type(e.left) == Str:
            self.code.append(Instruction(OpCode.STR_CONCAT))
            return
        if e.op in float_ops and ctx.get_type(e.left) == Float:
            self.code.append(Instruction(float_ops[e.op]))
            return
        if e.op in COMPARISONS and ctx.get_type(e.left) == Float:
            # Same shape as the str comparison below, and for the same reason:
            # FCMP reduces the pair to -1/0/1 and the integer comparison opcode
            # tests that against zero, so all six operators come from one new
            # opcode. The operand stack is untyped, so codegen must decide this.
            self.code.append(Instruction(OpCode.FCMP))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            self.code.append(Instruction(binary_ops[e.op]))
            return
        if e.op in COMPARISONS and ctx.get_type(e.left) == Str:
            # Comparing interned ids would order strings by whichever literal
            # the compiler saw first. STR_CMP reduces the pair to -1/0/1, which
            # the ordinary comparison opcode tests against zero, so all six
            # operators compare content for one extra instruction.
            #
            # Codegen has to emit this rather than the VM inferring it: the
            # operand stack is untyped words, so at run time a string id is
            # indistinguishable from an int.
            self.code.append(Instruction(OpCode.STR_CMP))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
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
            # BOUNDS_CHECK reads the index without popping it, so it drops in
            # ahead of the store the same way it does for `xs[i] = v`.
            self.code.append(Instruction(OpCode.BOUNDS_CHECK, slot.length))
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
            # Popping an empty array reaches index -1, which this rejects along
            # with an over-long length.
            self.code.append(Instruction(OpCode.BOUNDS_CHECK, slot.length))
            self.code.append(Instruction(OpCode.LOAD_LOCAL_IDX, slot.index))
            return

        # int <-> float, the only conversions between them.
        if name == "int_to_float" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.F_FROM_INT))
            return
        if name == "float_to_int" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.F_TO_INT))
            return
        if name == "float_to_str" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.STR_FROM_FLOAT))
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
        string_ops = {
            ("str_len", 1): OpCode.STR_LEN,
            ("str_char_at", 2): OpCode.STR_CHAR_AT,
            ("str_slice", 3): OpCode.STR_SLICE,
            ("int_to_str", 1): OpCode.STR_FROM_INT,
            ("char_to_str", 1): OpCode.STR_FROM_CHAR,
        }
        op = string_ops.get((name, len(e.args)))
        if op is not None:
            for arg_expr in e.args:
                self._emit_expr(arg_expr, layout, ctx)
            self.code.append(Instruction(op))
            return
        if name == "panic" and len(e.args) == 1:
            self._emit_expr(e.args[0], layout, ctx)
            self.code.append(Instruction(OpCode.PANIC))
            # PANIC never falls through, but the calling convention says every
            # expression leaves one value, and the statement that wraps this
            # will pop it.
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
            return
        if name == "gc" and not e.args:
            self.code.append(Instruction(OpCode.GC))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))  # void result
            return
        if name == "heap_store" and len(e.args) == 2:
            self._emit_expr(e.args[0], layout, ctx)   # addr
            self._emit_expr(e.args[1], layout, ctx)   # value
            self.code.append(Instruction(OpCode.HEAP_STORE))
            self.code.append(Instruction(OpCode.PUSH_INT, 0))  # void result
            return

        if name not in self.func_name_to_index:
            raise CodegenError(f"[{e.line}:{e.col}] Call to unknown function '{name}'")
        for arg_expr in e.args:
            self._emit_expr(arg_expr, layout, ctx)
        self.code.append(Instruction(OpCode.CALL, self.func_name_to_index[name]))
