import argparse
from pathlib import Path
from .lexer import Lexer
from .parser import Parser, ParseError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_8086 import CodeGen8086
import sys


def main():
    ap = argparse.ArgumentParser(description="QuinLang compiler")
    ap.add_argument("source", type=Path, help="Source .ql file")
    ap.add_argument("-o", "--out", type=Path, default=Path("build/out.asm"), help="Output .asm file")
    args = ap.parse_args()

    src_text = args.source.read_text(encoding="utf-8")

    try:
        tokens = Lexer(src_text).tokenize()
        ast = Parser(tokens).parse()
        ctx = SemanticAnalyzer().analyze(ast)
        asm = CodeGen8086().generate(ast, ctx)
    except ParseError as e:
        print(f"Syntax error at {args.source}:{e.line}:{e.col}: {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        # No location-tracking yet; message should be descriptive.
        print(f"Semantic error in {args.source}: {e}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(asm, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()