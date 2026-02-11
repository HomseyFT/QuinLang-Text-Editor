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
    NEG = auto()

    # Comparisons (push 0/1)
    CMP_EQ = auto()
    CMP_NE = auto()
    CMP_LT = auto()
    CMP_LE = auto()
    CMP_GT = auto()
    CMP_GE = auto()

    # Logical
    NOT = auto()

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

    # Indirect access using "pointer" as local index
    LOAD_INDIRECT = auto()     # pop p; push locals[p]
    STORE_INDIRECT = auto()    # pop v, pop p; locals[p] = v
    MEMCPY_LOCALS = auto()     # pop count, src, dst; copy locals
    MEMSET_LOCALS = auto()     # pop count, value, dst; fill locals

    # Builtin-style I/O
    PRINT_INT = auto()
    PRINT_STR = auto()
    PRINTLN_INT = auto()
    PRINTLN_STR = auto()


Operand = Union[int, None]


@dataclass
class Instruction:
    op: OpCode
    arg: Operand = None


Bytecode = List[Instruction]
