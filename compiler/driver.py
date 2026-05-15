import argparse
from pathlib import Path
from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_8086 import CodeGen8086
import sys


def main():
    ap = argparse.ArgumentParser(description="QuinLang compiler")
    ap.add_argument("source", type=Path, help="Source .ql file")
    ap.add_argument("-o", "--out", type=Path, default=Path("build/out.asm"), help="Output .asm file")
    args = ap.parse_args()

    # Determine std library path (relative to compiler package)
    std_path = Path(__file__).parent.parent / "std"

    try:
        # Resolve all includes and merge into a single program
        resolver = ImportResolver(std_path)
        resolved = resolver.resolve(args.source)
        ast = resolved.program

        ctx = SemanticAnalyzer().analyze(ast)
        asm = CodeGen8086().generate(ast, ctx)
    except ResolveError as e:
        print(f"Import error: {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        print(f"Semantic error: {e}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(asm, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()