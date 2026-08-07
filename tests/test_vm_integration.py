"""
tests/test_vm_integration.py

Regression tests for the IDE <-> compiler/runtime boundary.

History: earlier versions of these tests asserted that runtime/vm.py exposed
IDE-specific hooks (output_callback, request_stop, ExecutionStopped). Those
hooks were hand-patched into the IDE's copy of runtime/vm.py, and
.github/workflows/sync-compiler.yml overwrites compiler/, runtime/ and
examples/ wholesale on every sync from QuinLang - so each sync deleted them and
broke the IDE at import time. The 1.0.5 sync did it once; a later sync did it
again.

The contract tested here is therefore the inverted one: the IDE must work
against a STOCK, unmodified upstream QuinVM, keeping output capture and
cancellation on the ide/ side where the sync cannot reach them.

Run from the project root:
    python -m pytest tests/test_vm_integration.py -v
"""

from __future__ import annotations

import inspect
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
# Imports must resolve from the project root
# =============================================================================

class TestImports:
    def test_runtime_vm_importable(self):
        """runtime.vm must import cleanly from the project root."""
        from runtime.vm import QuinVM, VMError  # noqa: F401

    def test_driver_vm_importable(self):
        """compiler.driver_vm must not raise ModuleNotFoundError for runtime."""
        import importlib
        mod = importlib.import_module("compiler.driver_vm")
        assert hasattr(mod, "main")

    def test_runner_importable(self):
        """
        ide.runner must import without errors.

        This is the exact failure a bad sync produces: runner.py importing a
        name that upstream vm.py does not define, making the whole IDE
        unlaunchable.
        """
        from ide.runner import Runner, ExecutionStopped, RunState  # noqa: F401


# =============================================================================
# The IDE must not require IDE-specific hooks inside synced files
# =============================================================================

class TestNoHooksInSyncedFiles:
    """
    These guard the architectural rule that keeps breaking:
    runtime/ is upstream territory and gets replaced on every sync.
    """

    def test_execution_stopped_is_owned_by_the_ide(self):
        """
        ExecutionStopped must live in ide/, not runtime/.

        If someone moves it back into runtime/vm.py, the next compiler sync
        deletes it and the IDE stops launching.
        """
        from ide.runner import ExecutionStopped
        assert issubclass(ExecutionStopped, Exception)
        assert ExecutionStopped.__module__ == "ide.runner", (
            "ExecutionStopped must be defined in ide/runner.py so the compiler "
            "sync cannot delete it"
        )

    def test_quinvm_constructed_with_stock_signature(self):
        """
        The IDE must only use QuinVM's upstream constructor.

        Upstream takes (code, functions, strings). Depending on an extra
        output_callback parameter is what broke the IDE previously.
        """
        from runtime.vm import QuinVM
        params = list(inspect.signature(QuinVM.__init__).parameters)
        assert params == ["self", "code", "functions", "strings"], (
            f"QuinVM.__init__ signature changed: {params}. If the IDE needs "
            f"more, adapt ide/runner.py rather than patching runtime/vm.py."
        )

    def test_runner_imports_only_upstream_names(self):
        """ide/runner.py must import only names upstream vm.py really defines."""
        import runtime.vm as vm
        source = (PROJECT_ROOT / "ide" / "runner.py").read_text(encoding="utf-8")

        for line in source.splitlines():
            line = line.strip()
            if line.startswith("from runtime.vm import"):
                names = line.split("import", 1)[1]
                for name in (n.strip() for n in names.split(",")):
                    assert hasattr(vm, name), (
                        f"ide/runner.py imports '{name}' from runtime.vm, which "
                        f"upstream does not define. The next sync will break it."
                    )


# =============================================================================
# compiler.compiler_types must exist (spec once had the wrong name)
# =============================================================================

class TestCompilerTypes:
    def test_compiler_types_module_exists(self):
        """compiler.compiler_types must import; compiler.types must not exist."""
        from compiler.compiler_types import type_from_name, Int  # noqa: F401

    def test_wrong_module_name_absent(self):
        """compiler.types should NOT exist — the spec had it wrong."""
        with pytest.raises(ModuleNotFoundError):
            import compiler.types  # noqa: F401

    def test_spec_hiddenimports_all_resolve(self):
        """
        Every hiddenimport in quinlang_ide.spec must be a real module.

        A stale name here produces an executable that crashes only at runtime,
        which is exactly the class of bug the frozen build hides until release.
        """
        import importlib
        import re

        spec_src = (PROJECT_ROOT / "quinlang_ide.spec").read_text(encoding="utf-8")
        block = re.search(r"hiddenimports=\[(.*?)\]", spec_src, re.S)
        assert block, "could not find hiddenimports in quinlang_ide.spec"

        missing = []
        for name in re.findall(r"'([\w.]+)'", block.group(1)):
            try:
                importlib.import_module(name)
            except ImportError:
                missing.append(name)

        assert not missing, f"quinlang_ide.spec lists missing modules: {missing}"


# =============================================================================
# Runner integration
# =============================================================================

class TestRunnerSmoke:
    """End-to-end: Runner compiles and executes QuinLang programs."""

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

        def on_complete(r: RunResult):
            result_box.append(r)
            done.set()

        runner = Runner(on_output=output.append, on_complete=on_complete)
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

    def test_stdout_is_restored_after_a_run(self):
        """Redirecting stdout must not leak past the run."""
        from ide.runner import Runner, RunResult

        before = sys.stdout
        done = threading.Event()
        runner = Runner(
            on_output=lambda s: None,
            on_complete=lambda r: done.set(),
        )
        runner.run(self.HELLO_SRC)
        done.wait(timeout=5.0)
        time.sleep(0.05)

        assert sys.stdout is before, "stdout was not restored after the run"

    def test_runner_reports_syntax_errors(self):
        from ide.runner import Runner, RunResult, RunState

        result_box: list[RunResult] = []
        done = threading.Event()
        runner = Runner(
            on_output=lambda s: None,
            on_complete=lambda r: (result_box.append(r), done.set()),
        )
        runner.run("fn main(): int {\n  println(42\n}\n")
        done.wait(timeout=5.0)

        assert result_box and result_box[0].state == RunState.ERROR
        assert "Syntax error" in (result_box[0].error_message or "")

    def test_runner_stop_transitions_to_stopped(self):
        """Stopping a running program must yield RunState.STOPPED."""
        from ide.runner import Runner, RunResult, RunState

        inf_src = """\
fn main(): int {
    let x: int = 0;
    while (x == x) { }
    return 0;
}
"""
        result_box: list[RunResult] = []
        done = threading.Event()

        runner = Runner(
            on_output=lambda s: None,
            on_complete=lambda r: (result_box.append(r), done.set()),
        )
        runner.run(inf_src)
        time.sleep(0.05)
        runner.stop()
        done.wait(timeout=5.0)

        assert result_box, "on_complete was never called after stop()"
        assert result_box[0].state == RunState.STOPPED, \
            f"Expected STOPPED, got {result_box[0].state}"


# =============================================================================
# Every shipped example must still compile and run
# =============================================================================

class TestExamplesStillRun:
    """
    Catches a compiler sync that changes the language out from under the
    bundled examples - the IDE ships these, so a broken one is user-visible.
    """

    @pytest.mark.parametrize(
        "example",
        sorted((PROJECT_ROOT / "examples").glob("*.ql")),
        ids=lambda p: p.name,
    )
    def test_example_runs(self, example):
        from ide.runner import Runner, RunResult, RunState

        result_box: list[RunResult] = []
        done = threading.Event()
        runner = Runner(
            on_output=lambda s: None,
            on_complete=lambda r: (result_box.append(r), done.set()),
        )
        runner.run(example.read_text(encoding="utf-8"))
        done.wait(timeout=15.0)

        assert result_box, f"{example.name} never completed"
        assert result_box[0].state == RunState.FINISHED, (
            f"{example.name} did not run: {result_box[0].error_message}"
        )
