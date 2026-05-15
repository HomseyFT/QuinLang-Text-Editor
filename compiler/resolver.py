"""
Import resolution for QuinLang.

This module handles:
1. Path resolution (relative paths, std library lookup)
2. Recursive parsing of included files
3. Cycle detection
4. AST merging
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Dict, Optional

from . import ast as A
from .lexer import Lexer
from .parser import Parser, ParseError


class ResolveError(Exception):
    """Raised when import resolution fails."""
    pass


@dataclass
class ResolvedProgram:
    """Result of resolving all includes for a program."""
    program: A.Program  # Merged program with all functions
    source_files: List[Path]  # All files that were included (for error reporting)


class ImportResolver:
    """
    Resolves include statements by recursively parsing imported files
    and merging their functions into a single program.
    """

    def __init__(self, std_path: Path):
        """
        Args:
            std_path: Path to the standard library directory (e.g., project/std/)
        """
        self.std_path = std_path
        self.included: Set[Path] = set()  # Track resolved absolute paths (prevents cycles/duplicates)
        self.source_files: List[Path] = []  # Order of inclusion
        self.all_functions: List[A.Function] = []
        self.function_origins: Dict[str, Path] = {}  # Track where each function was defined

    def resolve(self, entry_file: Path) -> ResolvedProgram:
        """
        Recursively resolve all includes starting from entry_file.

        Args:
            entry_file: The main source file to compile

        Returns:
            ResolvedProgram with all functions merged

        Raises:
            ResolveError: If a file cannot be found or there's a parsing error
        """
        self.included.clear()
        self.source_files.clear()
        self.all_functions.clear()
        self.function_origins.clear()

        self._resolve_file(entry_file.resolve())

        # Create merged program (no includes in the merged result)
        merged = A.Program(includes=[], functions=self.all_functions)
        return ResolvedProgram(program=merged, source_files=self.source_files)

    def _resolve_file(self, file_path: Path) -> None:
        """
        Parse a file and recursively resolve its includes.

        Args:
            file_path: Absolute path to the file to resolve
        """
        # Cycle/duplicate detection
        if file_path in self.included:
            return
        self.included.add(file_path)
        self.source_files.append(file_path)

        # Read and parse the file
        if not file_path.exists():
            raise ResolveError(f"Cannot find file: {file_path}")

        try:
            src_text = file_path.read_text(encoding="utf-8")
        except IOError as e:
            raise ResolveError(f"Cannot read file {file_path}: {e}")

        try:
            tokens = Lexer(src_text).tokenize()
            program = Parser(tokens).parse()
        except ParseError as e:
            raise ResolveError(f"Syntax error in {file_path}:{e.line}:{e.col}: {e}")

        # Recursively resolve includes first (depth-first)
        for inc in program.includes:
            inc_path = self._resolve_path(inc.path, file_path)
            self._resolve_file(inc_path)

        # Add functions from this file (after includes, so dependencies come first)
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
        """
        Convert an include path to an absolute path.

        Resolution rules:
        - "std/..." -> resolve from std_path
        - "./..." or "../..." -> resolve relative to the including file
        - Other paths -> resolve relative to the including file

        Args:
            include_path: The path string from the include statement
            relative_to: The absolute path of the file containing the include

        Returns:
            Absolute path to the included file
        """
        # Standard library paths
        if include_path.startswith("std/"):
            return (self.std_path / include_path[4:]).resolve()

        # Relative paths (resolve relative to the including file's directory)
        base_dir = relative_to.parent
        return (base_dir / include_path).resolve()
