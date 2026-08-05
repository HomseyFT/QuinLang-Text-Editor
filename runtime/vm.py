from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict
from compiler.bytecode import OpCode, Instruction, Bytecode

WORD_MASK = 0xFFFF
SIGN_BIT = 0x8000
HEAP_SIZE = 64 * 1024


class VMError(RuntimeError):
    """Raised when the VM detects an invalid operand, address, or stack state."""


@dataclass
class FunctionInfo:
    name: str
    entry_pc: int
    num_locals: int
    num_params: int


@dataclass
class Frame:
    """A suspended caller, restored on RET."""
    return_pc: int
    locals: List[int]
    stack_base: int


def to_signed(v: int) -> int:
    """Reinterpret a 16-bit word as a signed integer."""
    v &= WORD_MASK
    return v - 0x10000 if v & SIGN_BIT else v


def trunc_div(a: int, b: int) -> int:
    """Integer division truncating toward zero, matching C semantics.

    Python's // floors, which differs for mixed signs, so the sign is
    applied separately rather than relying on float division.
    """
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


class QuinVM:
    """A stack machine for QuinLang bytecode.

    Values are 16-bit words held as ints masked to 0..0xFFFF; anything that
    cares about sign converts explicitly via to_signed().

    Calling convention: arguments are pushed left to right and consumed by
    CALL into the callee's leading locals. Every function pushes exactly one
    return value. Each frame records the operand-stack height at entry, so a
    function that leaves the stack unbalanced is caught at RET rather than
    silently corrupting its caller.
    """

    def __init__(self, code: Bytecode, functions: List[FunctionInfo], strings: Dict[int, str]):
        self.code = code
        self.functions = functions
        # map name -> index for convenience
        self.func_index: Dict[str, int] = {f.name: i for i, f in enumerate(functions)}
        self.strings = strings

        self.stack: List[int] = []          # value stack
        self.call_stack: List[Frame] = []
        self.pc: int = 0
        self.locals: List[int] = []         # current frame locals
        self.frame_base: int = 0            # stack height when current frame started
        self.heap: bytearray = bytearray(HEAP_SIZE)
        self.heap_ptr: int = 0

    def run_main(self) -> int:
        if "main" not in self.func_index:
            raise VMError("No 'main' function defined")
        fn = self.functions[self.func_index["main"]]
        self.locals = [0] * fn.num_locals
        self.pc = fn.entry_pc
        self.frame_base = 0
        return self._run()

    # -- helpers ---------------------------------------------------------

    def _pop(self) -> int:
        """Pop one value, refusing to reach below the current frame's base."""
        if len(self.stack) <= self.frame_base:
            raise VMError(f"Operand stack underflow at pc={self.pc - 1}")
        return self.stack.pop()

    def _local(self, index: int) -> int:
        if index < 0 or index >= len(self.locals):
            raise VMError(
                f"Local index out of range at pc={self.pc - 1}: "
                f"index={index}, num_locals={len(self.locals)}"
            )
        return self.locals[index]

    def _set_local(self, index: int, value: int):
        if index < 0 or index >= len(self.locals):
            raise VMError(
                f"Local index out of range at pc={self.pc - 1}: "
                f"index={index}, num_locals={len(self.locals)}"
            )
        self.locals[index] = value & WORD_MASK

    def _string(self, sid: int) -> str:
        if sid not in self.strings:
            raise VMError(f"Unknown string id {sid} at pc={self.pc - 1}")
        return self.strings[sid]

    def _alloc(self, size: int) -> int:
        if size < 0:
            raise VMError(f"Cannot allocate a negative size ({size})")
        # Align to 2 bytes so word access stays aligned.
        if size & 1:
            size += 1
        addr = self.heap_ptr
        if addr + size > len(self.heap):
            raise VMError("Heap out of memory")
        self.heap_ptr = addr + size
        return addr

    def _check_heap_word(self, addr: int, what: str):
        # A word access touches heap[addr] and heap[addr + 1].
        if addr < 0 or addr + 2 > len(self.heap):
            raise VMError(f"{what} out of range: addr={addr}, heap_size={len(self.heap)}")

    # -- interpreter -----------------------------------------------------

    def _run(self) -> int:
        code = self.code
        while self.pc < len(code):
            instr = code[self.pc]
            op = instr.op
            arg = instr.arg
            self.pc += 1

            if op is OpCode.PUSH_INT:
                self.stack.append(int(arg) & WORD_MASK)

            elif op is OpCode.LOAD_LOCAL:
                self.stack.append(self._local(int(arg)))

            elif op is OpCode.STORE_LOCAL:
                self._set_local(int(arg), self._pop())

            elif op is OpCode.ADD:
                b = self._pop(); a = self._pop()
                self.stack.append((a + b) & WORD_MASK)

            elif op is OpCode.SUB:
                b = self._pop(); a = self._pop()
                self.stack.append((a - b) & WORD_MASK)

            elif op is OpCode.MUL:
                b = self._pop(); a = self._pop()
                self.stack.append((a * b) & WORD_MASK)

            elif op is OpCode.DIV:
                b = to_signed(self._pop())
                a = to_signed(self._pop())
                if b == 0:
                    raise VMError("Division by zero")
                self.stack.append(trunc_div(a, b) & WORD_MASK)

            elif op is OpCode.MOD:
                b = to_signed(self._pop())
                a = to_signed(self._pop())
                if b == 0:
                    raise VMError("Modulo by zero")
                self.stack.append((a - trunc_div(a, b) * b) & WORD_MASK)

            elif op is OpCode.XOR:
                b = self._pop()
                a = self._pop()
                self.stack.append((a ^ b) & WORD_MASK)

            elif op is OpCode.AND:
                b = self._pop()
                a = self._pop()
                self.stack.append((a & b) & WORD_MASK)

            elif op is OpCode.OR:
                b = self._pop()
                a = self._pop()
                self.stack.append((a | b) & WORD_MASK)

            elif op is OpCode.SHL:
                count = to_signed(self._pop())
                value = self._pop()
                if count < 0 or count > 15:
                    raise VMError(f"Shift count out of range for SHL: {count}")
                self.stack.append((value << count) & WORD_MASK)

            elif op is OpCode.SHR:
                count = to_signed(self._pop())
                value = to_signed(self._pop())
                if count < 0 or count > 15:
                    raise VMError(f"Shift count out of range for SHR: {count}")
                self.stack.append((value >> count) & WORD_MASK)

            elif op is OpCode.NEG:
                self.stack.append((-self._pop()) & WORD_MASK)

            elif op in (OpCode.CMP_EQ, OpCode.CMP_NE, OpCode.CMP_LT,
                        OpCode.CMP_LE, OpCode.CMP_GT, OpCode.CMP_GE):
                # int is signed, so ordering must compare sign-extended values;
                # comparing the raw words would make -1 (0xFFFF) the largest int.
                b = to_signed(self._pop())
                a = to_signed(self._pop())
                if op is OpCode.CMP_EQ:
                    res = a == b
                elif op is OpCode.CMP_NE:
                    res = a != b
                elif op is OpCode.CMP_LT:
                    res = a < b
                elif op is OpCode.CMP_LE:
                    res = a <= b
                elif op is OpCode.CMP_GT:
                    res = a > b
                else:  # CMP_GE
                    res = a >= b
                self.stack.append(int(res))

            elif op is OpCode.NOT:
                self.stack.append(0 if self._pop() else 1)

            elif op is OpCode.BITNOT:
                self.stack.append((~self._pop()) & WORD_MASK)

            elif op is OpCode.JMP:
                self.pc = int(arg)

            elif op is OpCode.JZ:
                if self._pop() == 0:
                    self.pc = int(arg)

            elif op is OpCode.JNZ:
                if self._pop() != 0:
                    self.pc = int(arg)

            elif op is OpCode.CALL:
                fn_id = int(arg)
                if fn_id < 0 or fn_id >= len(self.functions):
                    raise VMError(f"CALL to invalid function index {fn_id}")
                fn = self.functions[fn_id]
                # Arguments belong to the caller's frame, so pop them before
                # recording the new frame base.
                args: List[int] = [self._pop() for _ in range(fn.num_params)]
                args.reverse()  # args[0] is now the first parameter
                self.call_stack.append(Frame(self.pc, self.locals, self.frame_base))
                self.locals = [0] * fn.num_locals
                for i, v in enumerate(args):
                    if i < len(self.locals):
                        self.locals[i] = v & WORD_MASK
                self.frame_base = len(self.stack)
                self.pc = fn.entry_pc

            elif op is OpCode.RET:
                # Every function pushes exactly one return value.
                if len(self.stack) != self.frame_base + 1:
                    raise VMError(
                        f"Unbalanced operand stack at RET (pc={self.pc - 1}): "
                        f"expected {self.frame_base + 1} entries, found {len(self.stack)}"
                    )
                ret_val = self.stack.pop()
                if not self.call_stack:
                    # returning from main: the value is the exit code
                    return to_signed(ret_val)
                frame = self.call_stack.pop()
                self.locals = frame.locals
                self.frame_base = frame.stack_base
                self.pc = frame.return_pc
                self.stack.append(ret_val)

            elif op is OpCode.LOAD_LOCAL_IDX:
                idx = to_signed(self._pop())
                self.stack.append(self._local(int(arg) + idx))

            elif op is OpCode.STORE_LOCAL_IDX:
                # Stack order from codegen: [ ..., value, index ]
                idx = to_signed(self._pop())
                val = self._pop()
                self._set_local(int(arg) + idx, val)

            elif op is OpCode.LOAD_INDIRECT:
                self.stack.append(self._local(to_signed(self._pop())))

            elif op is OpCode.STORE_INDIRECT:
                v = self._pop()
                p = to_signed(self._pop())
                self._set_local(p, v)

            elif op is OpCode.MEMCPY_LOCALS:
                count = to_signed(self._pop())
                src = to_signed(self._pop())
                dst = to_signed(self._pop())
                if count < 0:
                    raise VMError(f"MEMCPY_LOCALS negative count ({count})")
                # Copy back to front when the ranges overlap forward, so an
                # overlapping copy doesn't read slots it has already written.
                order = range(count - 1, -1, -1) if dst > src else range(count)
                for i in order:
                    self._set_local(dst + i, self._local(src + i))

            elif op is OpCode.MEMSET_LOCALS:
                count = to_signed(self._pop())
                value = self._pop()
                dst = to_signed(self._pop())
                if count < 0:
                    raise VMError(f"MEMSET_LOCALS negative count ({count})")
                for i in range(count):
                    self._set_local(dst + i, value)

            elif op is OpCode.POP:
                self._pop()

            elif op is OpCode.DUP:
                if len(self.stack) <= self.frame_base:
                    raise VMError(f"Operand stack underflow on DUP at pc={self.pc - 1}")
                self.stack.append(self.stack[-1])

            elif op is OpCode.SWAP:
                b = self._pop(); a = self._pop()
                self.stack.append(b)
                self.stack.append(a)

            elif op is OpCode.PRINT_INT:
                print(to_signed(self._pop()), end="")

            elif op is OpCode.PRINT_STR:
                print(self._string(self._pop()), end="")

            elif op is OpCode.PRINTLN_INT:
                print(to_signed(self._pop()))

            elif op is OpCode.PRINTLN_STR:
                print(self._string(self._pop()))

            elif op is OpCode.ALLOC:
                self.stack.append(self._alloc(to_signed(self._pop())))

            elif op is OpCode.HEAP_LOAD:
                addr = to_signed(self._pop())
                self._check_heap_word(addr, "HEAP_LOAD")
                # little-endian word
                self.stack.append((self.heap[addr + 1] << 8) | self.heap[addr])

            elif op is OpCode.HEAP_STORE:
                value = self._pop()
                addr = to_signed(self._pop())
                self._check_heap_word(addr, "HEAP_STORE")
                self.heap[addr] = value & 0xFF
                self.heap[addr + 1] = (value >> 8) & 0xFF

            else:
                raise VMError(f"Unknown opcode {op}")

        # fell off the end
        return 0
