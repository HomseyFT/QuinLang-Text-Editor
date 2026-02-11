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

    # One or two character tokens
    BANG = auto()
    BANG_EQUAL = auto()
    EQUAL_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()
    AND_AND = auto()
    OR_OR = auto()

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
    TRUE = auto()
    FALSE = auto()
    INT = auto()
    STR = auto()
    VOID = auto()
    PTR = auto()
    PRINT = auto()
    PRINTLN = auto()
    ASM = auto()
    VM_ASM = auto()

    EOF = auto()

KEYWORDS = {
    "fn": TokenType.FN,
    "let": TokenType.LET,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "int": TokenType.INT,
    "str": TokenType.STR,
    "void": TokenType.VOID,
    "print": TokenType.PRINT,
    "println": TokenType.PRINTLN,
    "ptr": TokenType.PTR,
    "asm": TokenType.ASM,
    "vm_asm": TokenType.VM_ASM,
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
    PRINT = auto()
    PRINTLN = auto()

    EOF = auto()

KEYWORDS = {
    "fn": TokenType.FN,
    "let": TokenType.LET,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "int": TokenType.INT,
    "str": TokenType.STR,
    "void": TokenType.VOID,
    "print": TokenType.PRINT,
    "println": TokenType.PRINTLN,
    "ptr": TokenType.PTR,
    "asm": TokenType.ASM,
    "vm_asm": TokenType.VM_ASM,
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
