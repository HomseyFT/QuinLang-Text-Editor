"""
tests/test_vm_integration.py

Regression tests covering three bugs introduced with the 1.0.5 compiler sync:

  Bug 1 — runtime.vm import path (ModuleNotFoundError)
  Bug 2 — QuinVM API mismatch: missing output_callback, ExecutionStopped, request_stop
  Bug 3 — quinlang_ide.spec hiddenimport 'compiler.types' (wrong name)

Run from the project root:
    python -m pytest tests/test_vm_integration.py -v
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

# ── project root on path ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


# =============================================================================
# Bug 1 — runtime.vm must be importable from the project root
# =============================================================================

class TestRuntimeImport:
    def test_runtime_vm_importable(self):
        """runtime.vm must import cleanly from the project root."""
        from runtime.vm import QuinVM, ExecutionStopped  # noqa: F401

    def test_driver_vm_importable(self):
        """compiler.driver_vm must not raise ModuleNotFoundError for runtime."""
        # Importing as a package member exercises the sys.path injection.
        import importlib
        mod = importlib.import_module("compiler.driver_vm")
        assert hasattr(mod, "main")

    def test_runner_importable(self):
        """ide.runner must import without errors."""
        from ide.runner import Runner, ExecutionStopped, RunState  # noqa: F401


# =============================================================================
# Bug 2 — QuinVM API surface expected by ide/runner.py
# =============================================================================

class TestQuinVMAPI:
    """Verify the API contract that runner.py depends on."""

    # Bytecode is a type alias (List[Instruction]), not a class.
    # Build instruction lists directly as plain lists.

    def _make_empty_vm(self, callback=None):
        from runtime.vm import QuinVM
        return QuinVM(code=[], functions=[], strings={},
                      output_callback=callback)

    def test_constructor_accepts_output_callback(self):
        """QuinVM.__init__ must accept an output_callback keyword argument."""
        collected: list[str] = []
        vm = self._make_empty_vm(callback=collected.append)
        assert vm is not None

    def test_request_stop_exists(self):
        """QuinVM must expose a request_stop() method."""
        vm = self._make_empty_vm()
        assert callable(getattr(vm, "request_stop", None)), \
            "QuinVM is missing request_stop()"

    def test_execution_stopped_importable(self):
        """ExecutionStopped must be exported from runtime.vm."""
        from runtime.vm import ExecutionStopped
        assert issubclass(ExecutionStopped, Exception)

    def test_output_callback_receives_print_output(self):
        """PRINT_INT/STR opcodes must route output through the callback."""
        from runtime.vm import QuinVM, FunctionInfo
        from compiler.bytecode import OpCode, Instruction

        collected: list[str] = []

        # Minimal program: PUSH_INT 42, PRINTLN_INT, PUSH_INT 0, RET
        code = [
            Instruction(OpCode.PUSH_INT, 42),
            Instruction(OpCode.PRINTLN_INT),
            Instruction(OpCode.PUSH_INT, 0),
            Instruction(OpCode.RET),
        ]
        fn = FunctionInfo(name="main", entry_pc=0, num_locals=1, num_params=0)
        vm = QuinVM(code=code, functions=[fn], strings={},
                    output_callback=lambda s: collected.append(s))
        exit_code = vm.run_main()

        assert exit_code == 0
        assert "".join(collected).strip() == "42", \
            f"Expected '42' in output, got {collected!r}"

    def test_request_stop_raises_execution_stopped(self):
        """request_stop() must cause _run to raise ExecutionStopped."""
        from runtime.vm import QuinVM, FunctionInfo, ExecutionStopped
        from compiler.bytecode import OpCode, Instruction

        # Infinite loop at the bytecode level: JMP 0
        code = [Instruction(OpCode.JMP, 0)]
        fn = FunctionInfo(name="main", entry_pc=0, num_locals=0, num_params=0)
        vm = QuinVM(code=code, functions=[fn], strings={})

        result: list = []

        def _run():
            try:
                vm.run_main()
                result.append("no_exception")
            except ExecutionStopped:
                result.append("stopped")
            except Exception as e:
                result.append(f"other:{e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.05)          # let the VM spin a bit
        vm.request_stop()
        t.join(timeout=2.0)

        assert result == ["stopped"], \
            f"Expected ExecutionStopped, got {result}"


# =============================================================================
# Bug 3 — compiler.compiler_types must exist (spec had wrong name)
# =============================================================================

class TestCompilerTypes:
    def test_compiler_types_module_exists(self):
        """compiler.compiler_types must import; compiler.types must not exist."""
        from compiler.compiler_types import type_from_name, Int  # noqa: F401

    def test_wrong_module_name_absent(self):
        """compiler.types should NOT exist — the spec had it wrong."""
        with pytest.raises(ModuleNotFoundError):
            import compiler.types  # noqa: F401

    def test_layout_imports_correctly(self):
        """layout.py must import without NameError or ModuleNotFoundError."""
        from compiler.layout import LayoutBuilder  # noqa: F401
        assert callable(LayoutBuilder)


# =============================================================================
# Runner integration smoke test
# =============================================================================

class TestRunnerSmoke:
    """End-to-end: Runner compiles and executes a trivial QuinLang program."""

    HELLO_SRC = """\
fn main(): int {
    println("hello");
    return 0;
}
"""

    def test_runner_executes_and_captures_output(self):
        from ide.runner import Runner, RunResult, RunState

        output: list[str] = []
        result_box: list[RunResult] = []
        done = threading.Event()

        def on_output(s: str):
            output.append(s)

        def on_complete(r: RunResult):
            result_box.append(r)
            done.set()

        runner = Runner(on_output=on_output, on_complete=on_complete)
        started = runner.run(self.HELLO_SRC)
        assert started, "Runner.run() returned False (already running?)"

        done.wait(timeout=5.0)
        assert result_box, "on_complete was never called"
        r = result_box[0]
        assert r.state == RunState.FINISHED, \
            f"Expected FINISHED, got {r.state}: {r.error_message}"
        assert r.exit_code == 0
        assert "hello" in "".join(output), \
            f"Expected 'hello' in output, got {output!r}"

    def test_runner_stop_transitions_to_stopped(self):
        """Stopping a running program must yield RunState.STOPPED."""
        from ide.runner import Runner, RunResult, RunState

        # while (x == x) is always-true but satisfies the bool-condition
        # requirement of the semantic analyser (1 == 1 is a bool expression).
        inf_src = """\
fn main(): int {
    let x: int = 0;
    while (x == x) { }
    return 0;
}
"""
        result_box: list[RunResult] = []
        done = threading.Event()

        runner = Runner(on_output=lambda s: None, on_complete=lambda r: (result_box.append(r), done.set()))
        runner.run(inf_src)
        time.sleep(0.05)
        runner.stop()
        done.wait(timeout=5.0)

        assert result_box, "on_complete was never called after stop()"
        assert result_box[0].state == RunState.STOPPED, \
            f"Expected STOPPED, got {result_box[0].state}"
