from dataclasses import dataclass, field
from typing import List, Union, Optional
from . import ast as A

# A very simple linear IR for 16-bit codegen

@dataclass
class Instr:
    op: str
    a: Optional[Union[str, int]] = None
    b: Optional[Union[str, int]] = None

@dataclass
class IRFunction:
    name: str
    instrs: List[Instr] = field(default_factory=list)

@dataclass
class IRProgram:
    functions: List[IRFunction]

class IRBuilder:
    def build(self, program: A.Program) -> IRProgram:
        funcs: List[IRFunction] = []
        for fn in program.functions:
            funcs.append(self._build_fn(fn))
        return IRProgram(funcs)

    def _build_fn(self, fn: A.Function) -> IRFunction:
        irf = IRFunction(fn.name)
        for st in fn.body:
            self._emit_stmt(irf, st)
        # Ensure function ends with RET
        irf.instrs.append(Instr('RET'))
        return irf

    def _emit_stmt(self, irf: IRFunction, st: A.Stmt):
        if isinstance(st, A.Print):
            # Emit evaluation into AX then runtime print
            # For strings, we expect a label; we'll let codegen lower literals
            irf.instrs.append(Instr('EVAL', st.value))
            irf.instrs.append(Instr('PRINT'))
        elif isinstance(st, A.Return):
            if st.value:
                irf.instrs.append(Instr('EVAL', st.value))
            irf.instrs.append(Instr('RET'))
        elif isinstance(st, A.VarDecl):
            # Variables will be stack-allocated later; ignore in IR for now
            if st.init:
                irf.instrs.append(Instr('EVAL', st.init))
                irf.instrs.append(Instr('STORE', st.name))
        elif isinstance(st, A.Assign):
            irf.instrs.append(Instr('EVAL', st.value))
            irf.instrs.append(Instr('STORE', st.name))
        elif isinstance(st, A.ExprStmt):
            irf.instrs.append(Instr('EVAL', st.expr))
        elif isinstance(st, A.If) or isinstance(st, A.While):
            # Control flow omitted for brevity in this initial IR
            pass
        else:
            pass