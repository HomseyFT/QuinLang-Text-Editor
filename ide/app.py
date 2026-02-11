"""
Main QuinLang IDE application.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional

from .editor import CodeEditor
from .runner import Runner, RunResult, RunState


class QuinLangIDE:
    """Main IDE window."""

    TITLE = "QuinLang IDE"
    DEFAULT_CODE = '''fn main(): int {
    println(42);
    return 0;
}
'''

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(self.TITLE)
        self.root.geometry("1000x700")
        self.root.minsize(600, 400)

        # Current file path
        self._current_file: Optional[Path] = None
        self._modified = False

        # Configure dark theme
        self._setup_theme()

        # Build UI
        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()

        # Setup runner
        self.runner = Runner(
            on_output=self._on_output,
            on_complete=self._on_run_complete,
        )

        # Load default code
        self.editor.set_code(self.DEFAULT_CODE)

        # Track modifications
        self.editor.text.bind("<<Modified>>", self._on_text_modified)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_theme(self):
        """Configure dark theme for ttk widgets."""
        style = ttk.Style()
        style.theme_use("clam")

        # Configure colors
        style.configure(".", background="#2b2b2b", foreground="#d4d4d4")
        style.configure("TFrame", background="#2b2b2b")
        style.configure("TLabel", background="#2b2b2b", foreground="#d4d4d4")
        style.configure("TButton", background="#3c3c3c", foreground="#d4d4d4")
        style.map("TButton",
                  background=[("active", "#505050"), ("pressed", "#606060")])

        # Configure root window
        self.root.configure(bg="#2b2b2b")

    def _build_menu(self):
        """Build the menu bar."""
        menubar = tk.Menu(self.root, bg="#2b2b2b", fg="#d4d4d4")
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0, bg="#2b2b2b", fg="#d4d4d4")
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New", command=self._new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self._open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self._save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self._save_file_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        # Run menu
        run_menu = tk.Menu(menubar, tearoff=0, bg="#2b2b2b", fg="#d4d4d4")
        menubar.add_cascade(label="Run", menu=run_menu)
        run_menu.add_command(label="Run", command=self._run_code, accelerator="F5")
        run_menu.add_command(label="Stop", command=self._stop_code, accelerator="Shift+F5")

        # Bind keyboard shortcuts
        self.root.bind("<Control-n>", lambda e: self._new_file())
        self.root.bind("<Control-o>", lambda e: self._open_file())
        self.root.bind("<Control-s>", lambda e: self._save_file())
        self.root.bind("<Control-S>", lambda e: self._save_file_as())
        self.root.bind("<F5>", lambda e: self._run_code())
        self.root.bind("<Shift-F5>", lambda e: self._stop_code())

    def _build_toolbar(self):
        """Build the toolbar."""
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        self.run_btn = ttk.Button(toolbar, text="▶ Run", command=self._run_code, width=10)
        self.run_btn.pack(side=tk.LEFT, padx=2)

        self.stop_btn = ttk.Button(toolbar, text="■ Stop", command=self._stop_code, width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(toolbar, text="Clear Output", command=self._clear_output, width=12).pack(side=tk.LEFT, padx=2)

    def _build_main_area(self):
        """Build the main editor and output area."""
        # Use PanedWindow for resizable split
        paned = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Editor
        editor_frame = ttk.Frame(paned)
        self.editor = CodeEditor(editor_frame)
        self.editor.pack(fill=tk.BOTH, expand=True)
        paned.add(editor_frame, weight=3)

        # Output panel
        output_frame = ttk.Frame(paned)

        output_label = ttk.Label(output_frame, text="Output")
        output_label.pack(anchor=tk.W)

        self.output_text = tk.Text(
            output_frame,
            height=10,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg="#1e1e1e",
            fg="#d4d4d4",
            state=tk.DISABLED,
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # Configure tags for colored output
        self.output_text.tag_configure("error", foreground="#f44747")
        self.output_text.tag_configure("info", foreground="#4ec9b0")
        self.output_text.tag_configure("warning", foreground="#dcdcaa")

        paned.add(output_frame, weight=1)

    def _build_status_bar(self):
        """Build the status bar."""
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

    def _update_title(self):
        """Update window title with file name and modified indicator."""
        name = self._current_file.name if self._current_file else "Untitled"
        modified = " *" if self._modified else ""
        self.root.title(f"{name}{modified} - {self.TITLE}")

    def _on_text_modified(self, event=None):
        """Handle text modification."""
        if self.editor.text.edit_modified():
            self._modified = True
            self._update_title()
            self.editor.text.edit_modified(False)

    # File operations
    def _new_file(self):
        """Create a new file."""
        if self._check_save():
            self.editor.clear()
            self._current_file = None
            self._modified = False
            self._update_title()

    def _open_file(self):
        """Open a file."""
        if not self._check_save():
            return

        path = filedialog.askopenfilename(
            title="Open QuinLang File",
            filetypes=[("QuinLang files", "*.ql"), ("All files", "*.*")],
        )
        if path:
            try:
                content = Path(path).read_text(encoding="utf-8")
                self.editor.set_code(content)
                self._current_file = Path(path)
                self._modified = False
                self._update_title()
                self.status_var.set(f"Opened: {path}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file:\n{e}")

    def _save_file(self):
        """Save the current file."""
        if self._current_file:
            self._do_save(self._current_file)
        else:
            self._save_file_as()

    def _save_file_as(self):
        """Save to a new file."""
        path = filedialog.asksaveasfilename(
            title="Save QuinLang File",
            defaultextension=".ql",
            filetypes=[("QuinLang files", "*.ql"), ("All files", "*.*")],
        )
        if path:
            self._do_save(Path(path))

    def _do_save(self, path: Path):
        """Actually save the file."""
        try:
            path.write_text(self.editor.get_code(), encoding="utf-8")
            self._current_file = path
            self._modified = False
            self._update_title()
            self.status_var.set(f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}")

    def _check_save(self) -> bool:
        """Check if unsaved changes should be saved. Returns True to proceed."""
        if not self._modified:
            return True

        result = messagebox.askyesnocancel(
            "Unsaved Changes",
            "You have unsaved changes. Do you want to save them?",
        )
        if result is None:  # Cancel
            return False
        if result:  # Yes
            self._save_file()
        return True

    # Run operations
    def _run_code(self):
        """Run the current code."""
        if self.runner.is_running:
            return

        self._clear_output()
        self._append_output("Running...\n", "info")
        self.status_var.set("Running...")

        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        code = self.editor.get_code()
        self.runner.run(code)

    def _stop_code(self):
        """Stop the running code."""
        if self.runner.is_running:
            self.runner.stop()
            self._append_output("\n[Stopping...]\n", "warning")

    def _on_output(self, text: str):
        """Handle output from the running program (called from worker thread)."""
        # Schedule UI update on main thread
        self.root.after(0, lambda: self._append_output(text))

    def _on_run_complete(self, result: RunResult):
        """Handle run completion (called from worker thread)."""
        def update():
            self.run_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

            if result.state == RunState.FINISHED:
                self._append_output(f"\n[Program finished with exit code {result.exit_code}]\n", "info")
                self.status_var.set(f"Finished (exit code {result.exit_code})")
            elif result.state == RunState.ERROR:
                self._append_output(f"\n[Error: {result.error_message}]\n", "error")
                self.status_var.set("Error")
            elif result.state == RunState.STOPPED:
                self._append_output("\n[Execution stopped]\n", "warning")
                self.status_var.set("Stopped")

        self.root.after(0, update)

    def _append_output(self, text: str, tag: Optional[str] = None):
        """Append text to output panel."""
        self.output_text.config(state=tk.NORMAL)
        if tag:
            self.output_text.insert(tk.END, text, tag)
        else:
            self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def _clear_output(self):
        """Clear the output panel."""
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state=tk.DISABLED)

    def _on_close(self):
        """Handle window close."""
        if self._check_save():
            self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()


def main():
    """Entry point."""
    app = QuinLangIDE()
    app.run()


if __name__ == "__main__":
    main()
