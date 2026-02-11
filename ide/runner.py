"""
Compiler/VM runner with output capture and threading support.
"""
from __future__ import annotations
import threading
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum, auto

from compiler.lexer import Lexer
from compiler.parser import Parser, ParseError
from compiler.sema import SemanticAnalyzer, SemanticError
from compiler.codegen_vm import CodeGenVM
from runtime.vm import QuinVM, ExecutionStopped


class RunState(Enum):
    IDLE = auto()
    RUNNING = auto()
    FINISHED = auto()
    ERROR = auto()
    STOPPED = auto()


@dataclass
class RunResult:
    state: RunState
    exit_code: Optional[int] = None
    error_message: Optional[str] = None


class Runner:
    """Compiles and runs QuinLang code with output capture."""

    def __init__(
        self,
        on_output: Callable[[str], None],
        on_complete: Callable[[RunResult], None],
    ):
        self._on_output = on_output
        self._on_complete = on_complete
        self._vm: Optional[QuinVM] = None
        self._thread: Optional[threading.Thread] = None
        self._state = RunState.IDLE

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == RunState.RUNNING

    def run(self, source_code: str) -> bool:
        """
        Compile and run the given source code.
        Returns True if execution started, False if already running.
        """
        if self.is_running:
            return False

        self._state = RunState.RUNNING
        self._thread = threading.Thread(target=self._run_impl, args=(source_code,), daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Request the running program to stop."""
        if self._vm and self.is_running:
            self._vm.request_stop()

    def _run_impl(self, source_code: str):
        """Internal method that runs in the worker thread."""
        try:
            # Compile
            tokens = Lexer(source_code).tokenize()
            ast = Parser(tokens).parse()
            ctx = SemanticAnalyzer().analyze(ast)
            codegen = CodeGenVM()
            code, functions, strings = codegen.generate(ast, ctx)

            # Run
            self._vm = QuinVM(code, functions, strings, output_callback=self._on_output)
            exit_code = self._vm.run_main()

            self._state = RunState.FINISHED
            self._on_complete(RunResult(RunState.FINISHED, exit_code=exit_code))

        except ParseError as e:
            self._state = RunState.ERROR
            self._on_complete(RunResult(
                RunState.ERROR,
                error_message=f"Syntax error at line {e.line}, col {e.col}: {e}"
            ))

        except SemanticError as e:
            self._state = RunState.ERROR
            self._on_complete(RunResult(
                RunState.ERROR,
                error_message=f"Semantic error: {e}"
            ))

        except ExecutionStopped:
            self._state = RunState.STOPPED
            self._on_complete(RunResult(RunState.STOPPED))

        except Exception as e:
            self._state = RunState.ERROR
            self._on_complete(RunResult(
                RunState.ERROR,
                error_message=f"Runtime error: {e}"
            ))

        finally:
            self._vm = None
