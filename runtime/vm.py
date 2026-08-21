from __future__ import annotations
import bisect
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from compiler.bytecode import OpCode, Instruction, Bytecode

WORD_MASK = 0xFFFF
SIGN_BIT = 0x8000
HEAP_SIZE = 64 * 1024
NULL_ADDR = 0

# Every heap object carries a two-word header immediately below the address the
# program holds:
#
#   word 0  flags  - the object's kind, plus the collector's mark bit
#   word 1  detail - a struct type id for KIND_STRUCT, otherwise the payload
#                    size in bytes
#
# Two words rather than one packed word, so neither the size nor the type id
# competes with the flags for bits.
#
# The header makes the heap parseable: from the first object you can reach every
# other by adding its size. Sweeping, compaction, and resolving an interior
# pointer to its containing object all depend on that.
HEADER_BYTES = 4
HEAP_START = NULL_ADDR + 2  # leave address 0 reserved for null

KIND_STRUCT = 0  # detail is a struct type id; trace its reference fields
KIND_RAW = 1     # detail is a byte size; reachable, reclaimable, never traced
KIND_STRING = 2  # detail is a byte length; the bytes follow, never traced
MARK_BIT = 0x8000

# There is no free-block kind: the collector slides live objects together, so
# free space is always the single region above heap_ptr and never needs to be
# described in the heap itself.

# Blocks are kept to a whole word so that no block is zero-sized, which keeps
# every address unambiguously inside exactly one block.
MIN_PAYLOAD = 2


class VMError(RuntimeError):
    """Raised when the VM detects an invalid operand, address, or stack state."""


@dataclass
class StructLayout:
    """What a collector needs to know about one struct type."""
    name: str
    word_size: int
    ref_offsets: Tuple[int, ...] = ()  # word offsets of fields holding references


@dataclass
class FunctionInfo:
    name: str
    entry_pc: int
    num_locals: int
    num_params: int
    # The GC stack map: which of this frame's local slots hold references.
    # Sound without liveness analysis because locals start at 0, and address 0
    # is reserved for null, so a slot read before its first assignment is
    # simply skipped.
    ref_slots: Tuple[int, ...] = ()


@dataclass
class Frame:
    """A suspended caller, restored on RET."""
    return_pc: int
    locals: List[int]
    stack_base: int
    # Which function these locals belong to, so the collector can find the
    # stack map that says which of them hold references.
    fn_index: int = 0


@dataclass
class HeapStats:
    """What the collector has done, for tests and for curiosity."""
    collections: int = 0
    objects_freed: int = 0
    bytes_freed: int = 0
    objects_allocated: int = 0
    objects_moved: int = 0


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

    def __init__(self, code: Bytecode, functions: List[FunctionInfo], strings: Dict[int, str],
                 structs: List[StructLayout] = None):
        self.code = code
        self.functions = functions
        self.func_index: Dict[str, int] = {f.name: i for i, f in enumerate(functions)}
        self.strings = strings
        self.structs: List[StructLayout] = list(structs or [])

        self.stack: List[int] = []
        # Which operand-stack entries hold heap references, maintained in step
        # with self.stack. The compiler knows the type of every expression, but
        # that information does not survive into the flat operand stack, and a
        # collector cannot guess: heap addresses and ints share the whole 16-bit
        # range, so no value can be recognised as a pointer by inspection.
        self.stack_is_ref: List[bool] = []
        self.call_stack: List[Frame] = []
        self.pc: int = 0
        self.locals: List[int] = []
        self.current_fn: int = 0
        self.frame_base: int = 0            # stack height when current frame started
        self.heap: bytearray = bytearray(HEAP_SIZE)
        # Address 0 is reserved for null, so a real allocation can never be at
        # address 0 and an unassigned local reads as null.
        # Everything below heap_ptr is allocated, everything above is free.
        # Compaction is what keeps that true: there is no free list, because
        # after a collection there are no holes to describe.
        self.heap_ptr: int = HEAP_START
        self.stats = HeapStats()
        # Literal id -> the heap address of its string object, filled in by
        # _materialise_literals when the program starts.
        self.literals: List[int] = []

    def run_main(self) -> int:
        if "main" not in self.func_index:
            raise VMError("No 'main' function defined")
        self._materialise_literals()
        idx = self.func_index["main"]
        fn = self.functions[idx]
        self.locals = [0] * fn.num_locals
        self.current_fn = idx
        self.pc = fn.entry_pc
        self.frame_base = 0
        return self._run()

    # -- helpers ---------------------------------------------------------

    def _push(self, value: int, is_ref: bool = False):
        self.stack.append(value & WORD_MASK)
        self.stack_is_ref.append(is_ref)

    def _pop(self) -> int:
        """Pop one value, refusing to reach below the current frame's base."""
        if len(self.stack) <= self.frame_base:
            raise VMError(f"Operand stack underflow at pc={self.pc - 1}")
        self.stack_is_ref.pop()
        return self.stack.pop()

    def _pop_tagged(self) -> Tuple[int, bool]:
        """Pop a value together with whether it is a reference."""
        if len(self.stack) <= self.frame_base:
            raise VMError(f"Operand stack underflow at pc={self.pc - 1}")
        return self.stack.pop(), self.stack_is_ref.pop()

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

    # -- object headers --------------------------------------------------
    #
    # Addresses below are header addresses unless named `ref`. A reference the
    # program holds points at the payload, HEADER_BYTES above its header.

    def _kind(self, hdr: int) -> int:
        return self._read_word(hdr) & ~MARK_BIT

    def _is_marked(self, hdr: int) -> bool:
        return bool(self._read_word(hdr) & MARK_BIT)

    def _set_mark(self, hdr: int, marked: bool):
        flags = self._read_word(hdr)
        self._write_word(hdr, flags | MARK_BIT if marked else flags & ~MARK_BIT)

    def _detail(self, hdr: int) -> int:
        return self._read_word(hdr + 2)

    def _payload_size(self, hdr: int) -> int:
        """Payload bytes of the block whose header is at `hdr`."""
        kind = self._kind(hdr)
        if kind == KIND_STRUCT:
            type_id = self._detail(hdr)
            if type_id >= len(self.structs):
                raise VMError(f"Corrupt heap: object at {hdr} has unknown type id {type_id}")
            return max(self.structs[type_id].word_size * 2, MIN_PAYLOAD)
        if kind == KIND_STRING:
            # detail is the true character count; the block is rounded up so
            # that the next header stays word-aligned.
            n = self._detail(hdr)
            return max(n + (n & 1), MIN_PAYLOAD)
        return self._detail(hdr)

    def _block_end(self, hdr: int) -> int:
        return hdr + HEADER_BYTES + self._payload_size(hdr)

    def _write_header(self, hdr: int, kind: int, detail: int):
        self._write_word(hdr, kind)
        self._write_word(hdr + 2, detail)

    def _blocks(self):
        """Walk every block in address order. The heap is parseable by design."""
        addr = HEAP_START
        while addr < self.heap_ptr:
            yield addr
            addr = self._block_end(addr)

    # -- allocation ------------------------------------------------------

    def _reserve(self, payload: int, kind: int, detail: int) -> int:
        """Find room for a block, collecting once if the heap is full.

        Allocation is a bump and nothing more. Compaction leaves all free
        space in one run above heap_ptr, so there is never a hole to search
        for or a remainder to split.
        """
        payload = max(payload, MIN_PAYLOAD)
        if payload & 1:
            payload += 1  # keep word accesses aligned

        addr = self._bump(payload, kind, detail)
        if addr is not None:
            return addr
        self.collect()
        addr = self._bump(payload, kind, detail)
        if addr is None:
            raise VMError("Heap out of memory")
        return addr

    def _bump(self, payload: int, kind: int, detail: int):
        end = self.heap_ptr + HEADER_BYTES + payload
        if end > len(self.heap):
            return None
        hdr = self.heap_ptr
        self.heap_ptr = end
        self._write_header(hdr, kind, detail)
        self.stats.objects_allocated += 1
        return hdr + HEADER_BYTES

    def _alloc_struct(self, type_id: int) -> int:
        if type_id < 0 or type_id >= len(self.structs):
            raise VMError(f"ALLOC_TYPED with unknown struct type id {type_id}")
        payload = self.structs[type_id].word_size * 2
        addr = self._reserve(payload, KIND_STRUCT, type_id)
        # Reused memory is dirty, and a stale word in a reference field would
        # be traced as if it were live.
        for off in range(0, max(payload, MIN_PAYLOAD), 2):
            self._write_word(addr + off, 0)
        return addr

    def _alloc_raw(self, size: int) -> int:
        if size < 0:
            raise VMError(f"Cannot allocate a negative size ({size})")
        rounded = size + 1 if size & 1 else size
        payload = max(rounded, MIN_PAYLOAD)
        addr = self._reserve(payload, KIND_RAW, payload)
        for off in range(0, payload, 2):
            self._write_word(addr + off, 0)
        return addr

    # -- strings ---------------------------------------------------------
    #
    # A string is a heap object: a header carrying its length in characters,
    # then the characters themselves, one byte each. It holds no references, so
    # the collector keeps it alive but never traces into it -- the same deal as
    # a block from alloc().

    def _alloc_string(self, data: bytes) -> int:
        length = len(data)
        if length > 0x7FFF:
            raise VMError(f"String of {length} characters is too long")
        addr = self._reserve(length, KIND_STRING, length)
        self.heap[addr:addr + length] = data
        # Pad so the rounding byte is never stale.
        if length & 1:
            self.heap[addr + length] = 0
        return addr

    def _string_bytes(self, addr: int) -> bytes:
        """The characters of the string object at `addr`."""
        if addr == NULL_ADDR:
            raise VMError("Null pointer dereference on a string")
        hdr = addr - HEADER_BYTES
        if hdr < HEAP_START or self._kind(hdr) != KIND_STRING:
            raise VMError(f"Value at {addr} is not a string")
        return bytes(self.heap[addr:addr + self._detail(hdr)])

    def _string_text(self, addr: int) -> str:
        return self._string_bytes(addr).decode("latin-1")

    def _materialise_literals(self):
        """Copy every literal into the heap before the program starts.

        Their addresses are permanent roots: a literal is reachable from the
        bytecode rather than from any variable, so nothing else would keep it
        alive. Compaction rewrites this list like any other root.
        """
        count = (max(self.strings) + 1) if self.strings else 0
        self.literals = [NULL_ADDR] * count
        for sid, text in self.strings.items():
            self.literals[sid] = self._alloc_string(text.encode("latin-1"))

    def _literal(self, sid: int) -> int:
        if sid < 0 or sid >= len(self.literals):
            raise VMError(f"Unknown string id {sid} at pc={self.pc - 1}")
        return self.literals[sid]

    # -- collection ------------------------------------------------------

    def collect(self):
        """A precise, sliding mark-compact cycle.

        Mark, then work out where each survivor will sit once the gaps close,
        rewrite every reference to point there, and only then move anything.
        Building the whole plan before touching the heap makes the move a plain
        copy.

        Moving objects is safe only because the roots are exact and no QuinLang
        expression can turn a reference into an int -- neither
        `heapptr - heapptr` nor address-of on a reference exists. A program
        cannot hold a copy of an address the collector fails to update.
        """
        self.stats.collections += 1
        starts = self._object_starts()
        for ref in self._roots():
            self._mark_from(ref, starts)
        forward = self._plan_compaction()
        self._update_references(forward, starts)
        self._slide(forward)

    def _object_starts(self) -> List[int]:
        """Payload addresses of every live block, ascending.

        Used to resolve a reference that points into the middle of a block:
        heapptr arithmetic can produce one, and it still keeps its object alive.
        """
        return [hdr + HEADER_BYTES for hdr in self._blocks()]

    def _roots(self):
        """Every reference the running program can still reach."""
        frames = [(self.current_fn, self.locals)]
        frames.extend((f.fn_index, f.locals) for f in self.call_stack)
        for fn_index, local_values in frames:
            if fn_index >= len(self.functions):
                continue
            for slot in self.functions[fn_index].ref_slots:
                if slot < len(local_values) and local_values[slot] != NULL_ADDR:
                    yield local_values[slot]
        # Values in flight: a nested allocation can leave the enclosing object
        # on the operand stack and in no local at all.
        for value, is_ref in zip(self.stack, self.stack_is_ref):
            if is_ref and value != NULL_ADDR:
                yield value
        # String literals live in the heap but are named by the bytecode, not
        # by any variable, so they are roots for the whole run.
        for addr in self.literals:
            if addr != NULL_ADDR:
                yield addr

    def _containing_object(self, ref: int, starts: List[int]):
        """The payload address of the block containing `ref`, or None."""
        i = bisect.bisect_right(starts, ref) - 1
        if i < 0:
            return None
        start = starts[i]
        hdr = start - HEADER_BYTES
        return start if ref < self._block_end(hdr) else None

    def _mark_from(self, ref: int, starts: List[int]):
        """Mark everything reachable from one root, iteratively."""
        pending = [ref]
        while pending:
            addr = pending.pop()
            if addr == NULL_ADDR:
                continue
            start = self._containing_object(addr, starts)
            if start is None:
                continue  # not a heap object; nothing to keep alive
            hdr = start - HEADER_BYTES
            if self._is_marked(hdr):
                continue
            self._set_mark(hdr, True)
            # Only structs have traceable interiors. A raw block is kept alive
            # but never traced: nothing in the language can put a reference
            # inside one, which is what dropping heapptr - heapptr and
            # address-of on references buys.
            if self._kind(hdr) == KIND_STRUCT:
                layout = self.structs[self._detail(hdr)]
                for off in layout.ref_offsets:
                    pending.append(self._read_word(start + off * 2))

    def _plan_compaction(self) -> Dict[int, int]:
        """Decide where every surviving object will live once gaps are closed.

        Returns old payload address -> new payload address. A host-side dict
        rather than forwarding words written into the heap, which a collector
        running inside the heap it manages could not afford.
        """
        forward: Dict[int, int] = {}
        free = HEAP_START
        for hdr in self._blocks():
            if not self._is_marked(hdr):
                continue
            forward[hdr + HEADER_BYTES] = free + HEADER_BYTES
            free += HEADER_BYTES + self._payload_size(hdr)
        return forward

    def _update_references(self, forward: Dict[int, int], starts: List[int]):
        """Rewrite every reference to the address its object is moving to.

        This runs before anything moves, reading and writing objects where they
        still are. Once it finishes, the bytes are already correct and the move
        is a plain copy.
        """
        def moved(ref: int) -> int:
            if ref == NULL_ADDR:
                return ref
            start = self._containing_object(ref, starts)
            if start is None or start not in forward:
                return ref
            # Keep the offset: a reference may point into the middle of a
            # block, since heapptr + int is allowed.
            return forward[start] + (ref - start)

        frames = [(self.current_fn, self.locals)]
        frames.extend((f.fn_index, f.locals) for f in self.call_stack)
        for fn_index, local_values in frames:
            if fn_index >= len(self.functions):
                continue
            for slot in self.functions[fn_index].ref_slots:
                if slot < len(local_values):
                    local_values[slot] = moved(local_values[slot])

        for i, is_ref in enumerate(self.stack_is_ref):
            if is_ref:
                self.stack[i] = moved(self.stack[i])

        # Literals do not move today: they are materialised first, so they
        # occupy the bottom of the heap, and being permanent roots they never
        # die, so compaction always finds them already in place. This keeps
        # that from being a silent assumption if materialisation ever changes.
        for i, addr in enumerate(self.literals):
            self.literals[i] = moved(addr)

        for hdr in self._blocks():
            if not self._is_marked(hdr) or self._kind(hdr) != KIND_STRUCT:
                continue
            start = hdr + HEADER_BYTES
            for off in self.structs[self._detail(hdr)].ref_offsets:
                self._write_word(start + off * 2, moved(self._read_word(start + off * 2)))

    def _slide(self, forward: Dict[int, int]):
        """Move each surviving object down into the space the dead vacated.

        Blocks are copied in ascending address order and only ever downward, so
        a block's destination always lies below every block still to be moved
        and cannot overwrite one.
        """
        top = HEAP_START
        for hdr in list(self._blocks()):
            size = HEADER_BYTES + self._payload_size(hdr)
            if not self._is_marked(hdr):
                self.stats.objects_freed += 1
                self.stats.bytes_freed += size
                continue
            dest = forward[hdr + HEADER_BYTES] - HEADER_BYTES
            if dest != hdr:
                self.heap[dest:dest + size] = self.heap[hdr:hdr + size]
                self.stats.objects_moved += 1
            self._set_mark(dest, False)
            top = dest + size
        # Wipe the space the survivors vacated. Sliding an object down leaves
        # its old bytes untouched, so a reference the collector failed to
        # update would still read the stale copy and quietly return the right
        # answer -- a bug that only surfaces once that memory is handed out
        # again. Zeroing turns it into an immediate null dereference instead.
        if top < self.heap_ptr:
            self.heap[top:self.heap_ptr] = bytes(self.heap_ptr - top)
        self.heap_ptr = top

    def heap_in_use(self) -> int:
        """Bytes the heap is currently holding, headers included.

        Immediately after a collection this is exactly the live data. Before
        one it also counts objects that are unreachable but not yet collected.
        """
        return self.heap_ptr - HEAP_START

    def _read_word(self, addr: int) -> int:
        return (self.heap[addr + 1] << 8) | self.heap[addr]

    def _write_word(self, addr: int, value: int):
        self.heap[addr] = value & 0xFF
        self.heap[addr + 1] = (value >> 8) & 0xFF

    def _current_ref_slots(self) -> Tuple[int, ...]:
        if self.current_fn >= len(self.functions):
            return ()
        return self.functions[self.current_fn].ref_slots

    def _field_is_ref(self, ref: int, offset: int) -> bool:
        """Whether field `offset` of the object at `ref` holds a reference."""
        hdr = ref - HEADER_BYTES
        if hdr < HEAP_START or self._kind(hdr) != KIND_STRUCT:
            return False
        type_id = self._detail(hdr)
        if type_id >= len(self.structs):
            return False
        return offset in self.structs[type_id].ref_offsets

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
                self._push(int(arg))

            elif op is OpCode.LOAD_LOCAL:
                idx = int(arg)
                self._push(self._local(idx), idx in self._current_ref_slots())

            elif op is OpCode.STORE_LOCAL:
                self._set_local(int(arg), self._pop())

            elif op is OpCode.ADD:
                b, b_ref = self._pop_tagged(); a, a_ref = self._pop_tagged()
                # heapptr + int yields a heapptr, so a sum involving a
                # reference is still a reference (possibly an interior one).
                self._push(a + b, a_ref or b_ref)

            elif op is OpCode.SUB:
                b, b_ref = self._pop_tagged(); a, a_ref = self._pop_tagged()
                self._push(a - b, a_ref or b_ref)

            elif op is OpCode.MUL:
                b = self._pop(); a = self._pop()
                self._push(a * b)

            elif op is OpCode.DIV:
                b = to_signed(self._pop())
                a = to_signed(self._pop())
                if b == 0:
                    raise VMError("Division by zero")
                self._push(trunc_div(a, b))

            elif op is OpCode.MOD:
                b = to_signed(self._pop())
                a = to_signed(self._pop())
                if b == 0:
                    raise VMError("Modulo by zero")
                self._push(a - trunc_div(a, b) * b)

            elif op is OpCode.XOR:
                b = self._pop()
                a = self._pop()
                self._push(a ^ b)

            elif op is OpCode.AND:
                b = self._pop()
                a = self._pop()
                self._push(a & b)

            elif op is OpCode.OR:
                b = self._pop()
                a = self._pop()
                self._push(a | b)

            elif op is OpCode.SHL:
                count = to_signed(self._pop())
                value = self._pop()
                if count < 0 or count > 15:
                    raise VMError(f"Shift count out of range for SHL: {count}")
                self._push(value << count)

            elif op is OpCode.SHR:
                count = to_signed(self._pop())
                value = to_signed(self._pop())
                if count < 0 or count > 15:
                    raise VMError(f"Shift count out of range for SHR: {count}")
                self._push(value >> count)

            elif op is OpCode.NEG:
                self._push(-self._pop())

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
                self._push(int(res))

            elif op is OpCode.LOAD_STR:
                self._push(self._literal(int(arg)), True)

            elif op is OpCode.STR_CMP:
                b = self._string_bytes(self._pop())
                a = self._string_bytes(self._pop())
                # A plain int, not a reference: the collector must not treat
                # this as a heap address.
                self._push(0 if a == b else (1 if a > b else -1))

            elif op is OpCode.STR_LEN:
                self._push(len(self._string_bytes(self._pop())))

            elif op is OpCode.STR_CHAR_AT:
                index = to_signed(self._pop())
                data = self._string_bytes(self._pop())
                if index < 0 or index >= len(data):
                    raise VMError(
                        f"str_char_at index out of range: index={index}, "
                        f"length={len(data)}"
                    )
                self._push(data[index])

            elif op is OpCode.STR_CONCAT:
                # Read both before allocating: the allocation may collect and
                # move them, and these are plain host-side copies.
                right = self._string_bytes(self._pop())
                left = self._string_bytes(self._pop())
                self._push(self._alloc_string(left + right), True)

            elif op is OpCode.STR_SLICE:
                end = to_signed(self._pop())
                start = to_signed(self._pop())
                data = self._string_bytes(self._pop())
                if start < 0 or end > len(data) or start > end:
                    raise VMError(
                        f"str_slice range out of bounds: start={start}, "
                        f"end={end}, length={len(data)}"
                    )
                self._push(self._alloc_string(data[start:end]), True)

            elif op is OpCode.STR_FROM_INT:
                self._push(self._alloc_string(
                    str(to_signed(self._pop())).encode("latin-1")), True)

            elif op is OpCode.STR_FROM_CHAR:
                # Not named `code`: that is the bytecode list this loop reads.
                char_code = to_signed(self._pop())
                if char_code < 0 or char_code > 255:
                    raise VMError(
                        f"char_to_str expects a code in 0..255, got {char_code}")
                self._push(self._alloc_string(bytes([char_code])), True)

            elif op is OpCode.NOT:
                self._push(0 if self._pop() else 1)

            elif op is OpCode.BITNOT:
                self._push(~self._pop())

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
                self.call_stack.append(
                    Frame(self.pc, self.locals, self.frame_base, self.current_fn))
                self.current_fn = fn_id
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
                ret_val, ret_is_ref = self.stack.pop(), self.stack_is_ref.pop()
                if not self.call_stack:
                    # returning from main: the value is the exit code
                    return to_signed(ret_val)
                frame = self.call_stack.pop()
                self.locals = frame.locals
                self.frame_base = frame.stack_base
                self.current_fn = frame.fn_index
                self.pc = frame.return_pc
                self._push(ret_val, ret_is_ref)

            elif op is OpCode.BOUNDS_CHECK:
                if len(self.stack) <= self.frame_base:
                    raise VMError(f"Operand stack underflow on BOUNDS_CHECK at pc={self.pc - 1}")
                idx = to_signed(self.stack[-1])
                length = int(arg)
                if idx < 0 or idx >= length:
                    raise VMError(
                        f"Array index out of bounds at pc={self.pc - 1}: "
                        f"index={idx}, length={length}"
                    )

            elif op is OpCode.LOAD_LOCAL_IDX:
                idx = to_signed(self._pop())
                self._push(self._local(int(arg) + idx))  # array elements are ints

            elif op is OpCode.STORE_LOCAL_IDX:
                # Stack order from codegen: [ ..., value, index ]
                idx = to_signed(self._pop())
                val = self._pop()
                self._set_local(int(arg) + idx, val)

            elif op is OpCode.LOAD_INDIRECT:
                self._push(self._local(to_signed(self._pop())))

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
                self._push(self.stack[-1], self.stack_is_ref[-1])

            elif op is OpCode.SWAP:
                b, b_ref = self._pop_tagged(); a, a_ref = self._pop_tagged()
                self._push(b, b_ref)
                self._push(a, a_ref)

            elif op is OpCode.PRINT_INT:
                print(to_signed(self._pop()), end="")

            elif op is OpCode.PRINT_STR:
                print(self._string_text(self._pop()), end="")

            elif op is OpCode.PRINTLN_INT:
                print(to_signed(self._pop()))

            elif op is OpCode.PRINTLN_STR:
                print(self._string_text(self._pop()))

            elif op is OpCode.ALLOC:
                self._push(self._alloc_raw(to_signed(self._pop())), True)

            elif op is OpCode.GC:
                self.collect()

            elif op is OpCode.PANIC:
                raise VMError(self._string_text(self._pop()))

            elif op is OpCode.ALLOC_TYPED:
                self._push(self._alloc_struct(int(arg)), True)

            elif op is OpCode.HEAP_LOAD:
                # A heap address spans the full 0..65535 word range, so it is
                # read unsigned. Sign-extending it would put everything in the
                # upper half of the heap at a negative address.
                addr = self._pop()
                if addr == NULL_ADDR:
                    raise VMError("Null pointer dereference in HEAP_LOAD")
                self._check_heap_word(addr, "HEAP_LOAD")
                # A raw block cannot contain a reference: nothing in the language
                # can put one there, which is exactly why the collector may keep
                # such a block alive without tracing into it.
                self._push(self._read_word(addr))

            elif op is OpCode.HEAP_STORE:
                value = self._pop()
                addr = self._pop()
                if addr == NULL_ADDR:
                    raise VMError("Null pointer dereference in HEAP_STORE")
                self._check_heap_word(addr, "HEAP_STORE")
                self._write_word(addr, value)

            elif op is OpCode.HEAP_LOAD_FIELD:
                ref = self._pop()
                if ref == NULL_ADDR:
                    raise VMError("Null pointer dereference reading a field")
                addr = ref + int(arg) * 2
                self._check_heap_word(addr, "HEAP_LOAD_FIELD")
                # The object's header names its struct type, which says whether
                # this field is a reference.
                self._push(self._read_word(addr), self._field_is_ref(ref, int(arg)))

            elif op is OpCode.HEAP_STORE_FIELD:
                value = self._pop()
                ref = self._pop()
                if ref == NULL_ADDR:
                    raise VMError("Null pointer dereference writing a field")
                addr = ref + int(arg) * 2
                self._check_heap_word(addr, "HEAP_STORE_FIELD")
                self._write_word(addr, value)

            else:
                raise VMError(f"Unknown opcode {op}")

        # fell off the end
        return 0
