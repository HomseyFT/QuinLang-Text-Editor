import argparse
from pathlib import Path
from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_vm import CodeGenVM
from runtime.vm import QuinVM
import sys


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
        code, functions, strings = codegen.generate(ast, ctx)
    except ResolveError as e:
        print(f"Import error: {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        print(f"Semantic error: {e}", file=sys.stderr)
        sys.exit(1)

    vm = QuinVM(code, functions, strings)
    exit_code = vm.run_main()
    # For now, just print exit code on a newline to separate from program output
    # print(f"\n[exit code {exit_code}]")


if __name__ == "__main__":
    main()
