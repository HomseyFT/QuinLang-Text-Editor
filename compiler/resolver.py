"""Include resolution: parse included files recursively and merge them into
one Program. Each file is resolved once, so a repeat or a cycle collapses to a
single copy rather than being reported as an error."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Dict, Optional

from . import ast as A
from .lexer import Lexer, LexError
from .parser import Parser, ParseError


class ResolveError(Exception):
    pass


@dataclass
class ResolvedProgram:
    program: A.Program
    source_files: List[Path]  # in inclusion order, for error reporting


class ImportResolver:
    def __init__(self, std_path: Path):
        self.std_path = std_path
        self.included: Set[Path] = set()  # absolute paths; collapses cycles and repeats
        self.source_files: List[Path] = []
        self.all_functions: List[A.Function] = []
        self.function_origins: Dict[str, Path] = {}
        self.all_structs: List[A.StructDef] = []
        self.struct_origins: Dict[str, Path] = {}

    def resolve(self, entry_file: Path) -> ResolvedProgram:
        self.included.clear()
        self.source_files.clear()
        self.all_functions.clear()
        self.function_origins.clear()
        self.all_structs.clear()
        self.struct_origins.clear()

        self._resolve_file(entry_file.resolve())

        merged = A.Program(includes=[], functions=self.all_functions,
                           structs=self.all_structs)
        return ResolvedProgram(program=merged, source_files=self.source_files)

    def _resolve_file(self, file_path: Path) -> None:
        if file_path in self.included:
            return
        self.included.add(file_path)
        self.source_files.append(file_path)

        if not file_path.exists():
            raise ResolveError(f"Cannot find file: {file_path}")

        try:
            src_text = file_path.read_text(encoding="utf-8")
        except IOError as e:
            raise ResolveError(f"Cannot read file {file_path}: {e}")

        try:
            tokens = Lexer(src_text).tokenize()
            program = Parser(tokens).parse()
        except (LexError, ParseError) as e:
            raise ResolveError(f"Syntax error in {file_path}:{e.line}:{e.col}: {e}")

        # Depth-first, so a file's dependencies land in the merged program
        # ahead of the file itself.
        for inc in program.includes:
            inc_path = self._resolve_path(inc.path, file_path)
            self._resolve_file(inc_path)

        # Structs and functions share one rule: a name may only be defined
        # once across the whole merged program.
        for sd in program.structs:
            if sd.name in self.struct_origins:
                orig = self.struct_origins[sd.name]
                raise ResolveError(
                    f"Redefinition of struct '{sd.name}' in {file_path} "
                    f"(previously defined in {orig})"
                )
            self.struct_origins[sd.name] = file_path
            self.all_structs.append(sd)

        for fn in program.functions:
            if fn.name in self.function_origins:
                orig = self.function_origins[fn.name]
                raise ResolveError(
                    f"Redefinition of function '{fn.name}' in {file_path} "
                    f"(previously defined in {orig})"
                )
            self.function_origins[fn.name] = file_path
            self.all_functions.append(fn)

    def _resolve_path(self, include_path: str, relative_to: Path) -> Path:
        """A 'std/' prefix resolves against the standard library; every other
        path resolves relative to the file containing the include."""
        if include_path.startswith("std/"):
            return (self.std_path / include_path[4:]).resolve()

        base_dir = relative_to.parent
        return (base_dir / include_path).resolve()
