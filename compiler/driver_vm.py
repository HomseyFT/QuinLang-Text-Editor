import argparse
import sys
from pathlib import Path

# Ensure the project root (parent of compiler/) is on sys.path so that
# `runtime` can be imported as a top-level package regardless of how this
# module is invoked (python -m compiler.driver_vm, direct script, or frozen).
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_vm import CodeGenVM
from runtime.vm import QuinVM


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
