import argparse
from pathlib import Path
from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_vm import CodeGenVM, CodegenError
from runtime.vm import QuinVM, VMError
import sys


def process_exit_code(value: int) -> int:
    """Narrow main's return value to what a process exit status can carry.

    int is 16-bit and signed; an exit status is 8 bits. The low byte is what
    survives, exactly as in C: 256 exits 0 and -1 exits 255.

    POSIX truncates this way regardless, but Windows exit codes are 32 bits
    wide and would otherwise report -1 as 4294967295. Doing it here keeps the
    result the same everywhere.
    """
    return value & 0xFF


def main():
    ap = argparse.ArgumentParser(description="QuinLang VM compiler/executor")
    ap.add_argument("source", type=Path, help="Source .ql file")
    args = ap.parse_args()

    # Determine std library path (relative to compiler package)
    std_path = Path(__file__).parent.parent / "std"

    try:
        # Resolve all includes and merge into a single program
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

    vm = QuinVM(code, functions, strings, structs)
    try:
        exit_value = vm.run_main()
    except VMError as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(1)

    # main's return value becomes the process exit status, so a QuinLang
    # program can be tested from a shell.
    sys.exit(process_exit_code(exit_value))


if __name__ == "__main__":
    main()
