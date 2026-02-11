import argparse
from pathlib import Path
from .lexer import Lexer
from .parser import Parser, ParseError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_vm import CodeGenVM
from runtime.vm import QuinVM
import sys


def main():
    ap = argparse.ArgumentParser(description="QuinLang VM compiler/executor")
    ap.add_argument("source", type=Path, help="Source .ql file")
    args = ap.parse_args()

    src_text = args.source.read_text(encoding="utf-8")

    try:
        tokens = Lexer(src_text).tokenize()
        ast = Parser(tokens).parse()
        ctx = SemanticAnalyzer().analyze(ast)
        codegen = CodeGenVM()
        code, functions, strings = codegen.generate(ast, ctx)
    except ParseError as e:
        print(f"Syntax error at {args.source}:{e.line}:{e.col}: {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        print(f"Semantic error in {args.source}: {e}", file=sys.stderr)
        sys.exit(1)

    vm = QuinVM(code, functions, strings)
    exit_code = vm.run_main()
    # For now, just print exit code on a newline to separate from program output
    # print(f"\n[exit code {exit_code}]")


if __name__ == "__main__":
    main()
