from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

class TokenType(Enum):
    # Single-character tokens
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
    COMMA = auto()
    DOT = auto()
    MINUS = auto()
    PLUS = auto()
    SEMICOLON = auto()
    SLASH = auto()
    STAR = auto()
    COLON = auto()
    EQUAL = auto()
    AMP = auto()
    AT = auto()

    # One or two character tokens
    BANG = auto()
    TILDE = auto()
    BANG_EQUAL = auto()
    EQUAL_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()
    AND_AND = auto()
    OR_OR = auto()
    PERCENT = auto()  # New token type for modulo operator
    CARET = auto()    # New token type for bitwise XOR operator
    PIPE = auto()     # New token type for bitwise OR operator
    SHL = auto()      # New token type for left shift operator
    SHR = auto()      # New token type for right shift operator

    # Literals
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()

    # Keywords
    FN = auto()
    LET = auto()
    RETURN = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    BREAK = auto()
    CONTINUE = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    INT = auto()
    STR = auto()
    VOID = auto()
    PTR = auto()
    HEAPPTR = auto()
    PRINT = auto()
    PRINTLN = auto()
    VM_ASM = auto()
    INCLUDE = auto()

    EOF = auto()

KEYWORDS = {
    "fn": TokenType.FN,
    "let": TokenType.LET,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "int": TokenType.INT,
    "str": TokenType.STR,
    "void": TokenType.VOID,
    "print": TokenType.PRINT,
    "println": TokenType.PRINTLN,
    "ptr": TokenType.PTR,
    "heapptr": TokenType.HEAPPTR,
    "vm_asm": TokenType.VM_ASM,
    "include": TokenType.INCLUDE,
}

@dataclass
class Token:
    type: TokenType
    lexeme: str
    line: int
    col: int
    literal: Optional[object] = None

    def __repr__(self) -> str:
        lit = f" {self.literal!r}" if self.literal is not None else ""
        return f"{self.type.name} '{self.lexeme}'{lit} (@{self.line}:{self.col})"
