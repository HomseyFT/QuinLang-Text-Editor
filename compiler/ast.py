from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Union

# Expressions
@dataclass
class Expr:
    pass

@dataclass
class Literal(Expr):
    value: Union[int, str, bool, None]

@dataclass
class Identifier(Expr):
    name: str

@dataclass
class Unary(Expr):
    op: str
    right: Expr

@dataclass
class Binary(Expr):
    left: Expr
    op: str
    right: Expr

@dataclass
class Call(Expr):
    callee: str
    args: List[Expr]

@dataclass
class Index(Expr):
    array: Expr
    index: Expr

@dataclass
class AddressOf(Expr):
    target: Expr  # Identifier or Index

# Statements
@dataclass
class Stmt:
    pass

@dataclass
class ExprStmt(Stmt):
    expr: Expr

@dataclass
class VarDecl(Stmt):
    name: str
    type_name: Optional[str]
    init: Optional[Expr]

@dataclass
class Assign(Stmt):
    target: Expr  # Identifier or Index
    value: Expr

@dataclass
class Print(Stmt):
    value: Expr

@dataclass
class PrintLn(Stmt):
    value: Expr

@dataclass
class Return(Stmt):
    value: Optional[Expr]

@dataclass
class InlineAsm(Stmt):
    # Raw assembly text to be spliced into the 8086 backend output.
    code: str

@dataclass
class VmAsm(Stmt):
    # VM-level inline IR to be lowered directly to VM bytecode.
    # The code is a small, line-based DSL understood by the VM backend.
    code: str

@dataclass
class If(Stmt):
    cond: Expr
    then_block: List[Stmt]
    else_block: Optional[List[Stmt]] = None

@dataclass
class While(Stmt):
    cond: Expr
    body: List[Stmt]

@dataclass
class Block(Stmt):
    stmts: List[Stmt] = field(default_factory=list)

@dataclass
class Param:
    name: str
    type_name: str

@dataclass
class Function:
    name: str
    params: List[Param]
    return_type: Optional[str]
    body: List[Stmt]

@dataclass
class Program:
    functions: List[Function]