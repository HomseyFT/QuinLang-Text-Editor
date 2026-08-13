from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Union


class OpCode(Enum):
    # Stack and locals
    PUSH_INT = auto()      # operand: int literal
    LOAD_LOCAL = auto()    # operand: local index
    STORE_LOCAL = auto()   # operand: local index

    # Arithmetic
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    XOR = auto()
    AND = auto()
    OR = auto()
    SHL = auto()
    SHR = auto()
    NEG = auto()

    # Comparisons (push 0/1)
    CMP_EQ = auto()
    CMP_NE = auto()
    CMP_LT = auto()
    CMP_LE = auto()
    CMP_GT = auto()
    CMP_GE = auto()

    # Strings. A str value is the heap address of a string object, so these
    # read and build objects rather than indexing a host-side table.
    LOAD_STR = auto()      # operand: literal id; push that literal's address
    STR_CMP = auto()       # pop two strings, push -1, 0 or 1 by content order
    STR_LEN = auto()       # pop a string, push its length
    STR_CHAR_AT = auto()   # pop index and string, push the character code
    STR_CONCAT = auto()    # pop two strings, push a new one
    STR_SLICE = auto()     # pop end, start and string, push a new one
    STR_FROM_INT = auto()  # pop an int, push its decimal text
    STR_FROM_CHAR = auto() # pop a character code, push a one-character string

    # Logical
    NOT = auto()
    BITNOT = auto()

    # Control flow
    JMP = auto()           # operand: target pc
    JZ = auto()            # operand: target pc (pop value; jump if zero)
    JNZ = auto()           # operand: target pc (pop value; jump if nonzero)

    # Function calls
    CALL = auto()          # operand: function index
    RET = auto()

    # Arrays as locals: base index is encoded in operand
    LOAD_LOCAL_IDX = auto()    # operand: base local index
    STORE_LOCAL_IDX = auto()   # operand: base local index
    BOUNDS_CHECK = auto()      # operand: array element count; inspects index on top of stack without popping it

    # Indirect access using "pointer" as local index
    LOAD_INDIRECT = auto()     # pop p; push locals[p]
    STORE_INDIRECT = auto()    # pop v, pop p; locals[p] = v
    MEMCPY_LOCALS = auto()     # pop count, src, dst; copy locals
    MEMSET_LOCALS = auto()     # pop count, value, dst; fill locals

    # Stack management
    POP = auto()
    DUP = auto()           # push a copy of the top of stack
    SWAP = auto()          # exchange the top two stack entries

    # Builtin-style I/O
    PRINT_INT = auto()
    PRINT_STR = auto()
    PRINTLN_INT = auto()
    PRINTLN_STR = auto()

    # Heap operations
    ALLOC = auto()             # pop size in bytes; allocate an untyped block
    ALLOC_TYPED = auto()       # operand: struct type id; allocate that struct
    HEAP_LOAD = auto()
    HEAP_STORE = auto()
    # Field access. The offset is an operand rather than an ADD on the address,
    # so the null check tests the object reference itself: adding first would
    # turn a null base into a small non-zero address and read whatever is there.
    HEAP_LOAD_FIELD = auto()   # operand: word offset; pop ref, push field
    HEAP_STORE_FIELD = auto()  # operand: word offset; pop value, pop ref
    GC = auto()                # force a collection
    PANIC = auto()             # pop a message id and stop the program


Operand = Union[int, None]


@dataclass
class Instruction:
    op: OpCode
    arg: Operand = None


Bytecode = List[Instruction]
