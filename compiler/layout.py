from dataclasses import dataclass
from typing import Dict, List, Tuple
from . import ast as A
from .types import type_from_name, Int

@dataclass
class StackLayout:
    size: int
    offsets: Dict[str, int]

    def offset_of(self, name: str) -> int:
        return self.offsets[name]

class LayoutBuilder:
    def build_for_function(self, fn: A.Function) -> StackLayout:
        # Collect all local var decls (no shadowing handling for now)
        names: List[Tuple[str, int]] = []  # (name, size)
        seen: Dict[str, bool] = {}
        def visit(st: A.Stmt):
            if isinstance(st, A.VarDecl):
                if st.name not in seen:
                    seen[st.name] = True
                    t = type_from_name(st.type_name) if st.type_name else None
                    if t is None and st.init is not None:
                        # Fallback to 2-byte slot if unknown at layout time
                        sz = 2
                    else:
                        sz = t.size if t is not None else 2
                    # allocate at least 2 bytes for simplicity
                    if sz == 1:
                        sz = 2
                    names.append((st.name, sz))
            elif isinstance(st, A.If):
                for s in st.then_block:
                    visit(s)
                if st.else_block:
                    for s in st.else_block:
                        visit(s)
            elif isinstance(st, A.While):
                for s in st.body:
                    visit(s)
            elif isinstance(st, A.Block):
                for s in st.stmts:
                    visit(s)
        for st in fn.body:
            visit(st)
        # Assign offsets from BP downward
        offsets: Dict[str, int] = {}
        offset = 0
        for name, sz in names:
            offset += sz
            offsets[name] = offset  # [bp - offset]
        # Align to 2 bytes already enforced
        return StackLayout(size=offset, offsets=offsets)
