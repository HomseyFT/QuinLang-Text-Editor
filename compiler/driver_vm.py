import argparse
from pathlib import Path
from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_vm import CodeGenVM, CodegenError
from runtime.vm import QuinVM, VMError
import sys


def process_exit_code(value: int) -> int:
    """Narrow main's 16-bit return value to the 8 bits an exit status carries.

    POSIX truncates this way regardless, but Windows exit codes are 32 bits
    wide and would otherwise report -1 as 4294967295.
    """
    return value & 0xFF


def main():
    ap = argparse.ArgumentParser(description="QuinLang VM compiler/executor")
    ap.add_argument("source", type=Path, help="Source .ql file")
    args = ap.parse_args()

    std_path = Path(__file__).parent.parent / "std"

    try:
        resolver = ImportResolver(std_path)
        resolved = resolver.resolve(args.source)
        ast = resolved.program

        ctx = SemanticAnalyzer().analyze(ast)
        codegen = CodeGenVM()
        code, functions, strings, structs = codegen.generate(ast, ctx)
    except ResolveError as e:
        print(f"Import error: {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        print(f"Semantic error: {e}", file=sys.stderr)
        sys.exit(1)
    except CodegenError as e:
        print(f"Codegen error: {e}", file=sys.stderr)
        sys.exit(1)

    # Warnings go to stderr so piping stdout stays clean, and change neither
    # the exit code nor whether the program runs.
    for warning in ctx.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    vm = QuinVM(code, functions, strings, structs)
    try:
        exit_value = vm.run_main()
    except VMError as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(process_exit_code(exit_value))


if __name__ == "__main__":
    main()
