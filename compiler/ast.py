from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Union

# Base node with location info
@dataclass
class Node:
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)

# Expressions
@dataclass
class Expr(Node):
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

@dataclass
class FieldAccess(Expr):
    obj: Expr
    field: str

@dataclass
class FieldInit(Node):
    name: str
    value: Expr

@dataclass
class StructLit(Expr):
    struct_name: str
    fields: List[FieldInit]

# Statements
@dataclass
class Stmt(Node):
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
class For(Stmt):
    # Any of init/cond/step may be omitted; an omitted cond loops forever.
    init: Optional[Stmt]
    cond: Optional[Expr]
    step: Optional[Stmt]
    body: List[Stmt]

@dataclass
class Break(Stmt):
    pass

@dataclass
class Continue(Stmt):
    pass

@dataclass
class Block(Stmt):
    stmts: List[Stmt] = field(default_factory=list)

@dataclass
class Param(Node):
    name: str
    type_name: str

@dataclass
class Function(Node):
    name: str
    params: List[Param]
    return_type: Optional[str]
    body: List[Stmt]

@dataclass
class FieldDef(Node):
    name: str
    type_name: str

@dataclass
class StructDef(Node):
    name: str
    fields: List[FieldDef]

@dataclass
class Include(Node):
    path: str  # The string literal path from the include statement

@dataclass
class Program(Node):
    includes: List[Include]
    functions: List[Function]
    structs: List[StructDef] = field(default_factory=list)
