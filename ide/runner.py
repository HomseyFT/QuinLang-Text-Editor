"""
Compiler/VM runner with output capture and threading support.

Important: runtime/ and compiler/ are overwritten wholesale by
.github/workflows/sync-compiler.yml on every sync from the QuinLang repo, so
nothing here may depend on IDE-specific hooks living inside those files. Earlier
versions patched runtime/vm.py to add output_callback/request_stop/
ExecutionStopped; each sync deleted them again and broke the IDE.

Output capture and cancellation are therefore implemented entirely on this side,
against the stock upstream QuinVM:

  * output  - QuinVM's PRINT opcodes call print(), so stdout is redirected for
              the duration of the run and forwarded to the callback.
  * stopping - a thread-local trace function raises ExecutionStopped at the next
              function call the VM makes.
"""
from __future__ import annotations
import contextlib
import sys
import threading
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum, auto

from compiler.lexer import Lexer
from compiler.parser import Parser, ParseError
from compiler.sema import SemanticAnalyzer, SemanticError
from compiler.codegen_vm import CodeGenVM
from runtime.vm import QuinVM, VMError


class ExecutionStopped(Exception):
    """Raised inside the run thread when the user asks the program to stop."""


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


class _CallbackStream:
    """Minimal file-like object that forwards writes to a callback."""

    def __init__(self, on_write: Callable[[str], None]):
        self._on_write = on_write

    def write(self, text: str) -> int:
        if text:
            self._on_write(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class Runner:
    """Compiles and runs QuinLang code with output capture."""

    def __init__(
        self,
        on_output: Callable[[str], None],
        on_complete: Callable[[RunResult], None],
    ):
        self._on_output = on_output
        self._on_complete = on_complete
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = threading.Event()
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

        self._stop_requested.clear()
        self._state = RunState.RUNNING
        self._thread = threading.Thread(target=self._run_impl, args=(source_code,), daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Request the running program to stop."""
        self._stop_requested.set()

    def _trace(self, frame, event, arg):
        """
        Thread trace hook. Returning None means we're called for 'call' events
        only, which the VM triggers constantly via its _pop/_local helpers -
        frequent enough to stop promptly, far cheaper than tracing every line.
        """
        if self._stop_requested.is_set():
            raise ExecutionStopped()
        return None

    def _run_impl(self, source_code: str):
        """Internal method that runs in the worker thread."""
        try:
            # Compile
            tokens = Lexer(source_code).tokenize()
            ast = Parser(tokens).parse()
            ctx = SemanticAnalyzer().analyze(ast)
            codegen = CodeGenVM()
            code, functions, strings = codegen.generate(ast, ctx)

            # Compiling can take a moment on a large file; honour a stop
            # requested before execution even begins.
            if self._stop_requested.is_set():
                raise ExecutionStopped()

            vm = QuinVM(code, functions, strings)
            stream = _CallbackStream(self._on_output)

            sys.settrace(self._trace)
            try:
                with contextlib.redirect_stdout(stream):
                    exit_code = vm.run_main()
            finally:
                sys.settrace(None)

            self._state = RunState.FINISHED
            self._on_complete(RunResult(RunState.FINISHED, exit_code=exit_code))

        except ExecutionStopped:
            self._state = RunState.STOPPED
            self._on_complete(RunResult(RunState.STOPPED))

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

        except VMError as e:
            self._state = RunState.ERROR
            self._on_complete(RunResult(
                RunState.ERROR,
                error_message=f"VM error: {e}"
            ))

        except Exception as e:
            self._state = RunState.ERROR
            self._on_complete(RunResult(
                RunState.ERROR,
                error_message=f"Runtime error: {e}"
            ))
