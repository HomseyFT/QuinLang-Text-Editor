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
from .tabs import TabManager, EditorBuffer
from .finder import open_finder
from .terminal import CommandLine
from .theme import COLORS, FONTS, apply_theme, get_text_widget_config
from .updater import UpdateChecker, ReleaseInfo, download_update, apply_update, get_current_version, is_frozen


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
        self.root.geometry("1100x800")
        self.root.minsize(700, 500)

        # Current working directory for finder/terminal
        self._cwd = Path.cwd()

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

        # Create initial tab with default code
        self.tab_manager.new_buffer(content=self.DEFAULT_CODE)

        # Track modifications
        self.editor.text.bind("<<Modified>>", self._on_text_modified)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Check for updates in background
        self._check_for_updates()

    def _setup_theme(self):
        """Configure theme for ttk widgets."""
        style = ttk.Style()
        apply_theme(self.root, style)

    def _build_menu(self):
        """Build the menu bar."""
        menubar = tk.Menu(self.root, bg=COLORS['bg_medium'], fg=COLORS['text_primary'])
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0, bg=COLORS['bg_medium'], fg=COLORS['text_primary'])
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New Tab", command=self._new_tab, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self._open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Find File...", command=self._open_finder, accelerator="Ctrl+Shift+F")
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self._save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self._save_file_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Close Tab", command=self._close_tab, accelerator="Ctrl+W")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        # Run menu
        run_menu = tk.Menu(menubar, tearoff=0, bg=COLORS['bg_medium'], fg=COLORS['text_primary'])
        menubar.add_cascade(label="Run", menu=run_menu)
        run_menu.add_command(label="Run", command=self._run_code, accelerator="F5")
        run_menu.add_command(label="Stop", command=self._stop_code, accelerator="Shift+F5")

        # Bind keyboard shortcuts
        self.root.bind("<Control-n>", lambda e: self._new_tab())
        self.root.bind("<Control-o>", lambda e: self._open_file())
        self.root.bind("<Control-s>", lambda e: self._save_file())
        self.root.bind("<Control-S>", lambda e: self._save_file_as())
        self.root.bind("<Control-w>", lambda e: self._close_tab())
        self.root.bind("<Control-Shift-F>", lambda e: self._open_finder())
        self.root.bind("<Control-Shift-f>", lambda e: self._open_finder())
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

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(toolbar, text="Find File", command=self._open_finder, width=12).pack(side=tk.LEFT, padx=2)

        ttk.Button(toolbar, text="Clear Output", command=self._clear_output, width=12).pack(side=tk.LEFT, padx=2)

    def _build_main_area(self):
        """Build the main editor, output, and terminal area."""
        # Main vertical paned window
        main_paned = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Top section: Editor with tabs
        editor_container = ttk.Frame(main_paned)
        
        # Create editor first (TabManager needs it)
        self.editor = CodeEditor(editor_container)
        
        # Create tab manager
        self.tab_manager = TabManager(
            editor_container,
            self.editor,
            on_buffer_change=self._on_buffer_change,
        )
        
        # Pack tab bar and editor
        self.tab_manager.tab_bar.pack(fill=tk.X)
        self.editor.pack(fill=tk.BOTH, expand=True)
        
        main_paned.add(editor_container, weight=3)

        # Bottom section: Output and Terminal in horizontal split
        bottom_paned = ttk.PanedWindow(main_paned, orient=tk.HORIZONTAL)
        
        # Output panel (left)
        output_frame = ttk.Frame(bottom_paned)

        output_label = ttk.Label(output_frame, text="Output")
        output_label.pack(anchor=tk.W)

        text_config = get_text_widget_config()
        self.output_text = tk.Text(
            output_frame,
            height=10,
            wrap=tk.WORD,
            font=FONTS['code_small'],
            state=tk.DISABLED,
            **text_config
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # Configure tags for colored output
        self.output_text.tag_configure("error", foreground=COLORS['error'])
        self.output_text.tag_configure("info", foreground=COLORS['info'])
        self.output_text.tag_configure("warning", foreground=COLORS['warning'])

        bottom_paned.add(output_frame, weight=1)

        # Terminal panel (right)
        terminal_frame = ttk.Frame(bottom_paned)
        
        terminal_label = ttk.Label(terminal_frame, text="Terminal")
        terminal_label.pack(anchor=tk.W)
        
        self.terminal = CommandLine(
            terminal_frame,
            initial_cwd=self._cwd,
            on_cwd_change=self._on_cwd_change,
        )
        self.terminal.pack(fill=tk.BOTH, expand=True)
        
        bottom_paned.add(terminal_frame, weight=1)

        main_paned.add(bottom_paned, weight=1)

    def _build_status_bar(self):
        """Build the status bar."""
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)
        
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W)
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Show current working directory
        self.cwd_var = tk.StringVar(value=str(self._cwd))
        cwd_label = ttk.Label(status_frame, textvariable=self.cwd_var, anchor=tk.E, foreground=COLORS['text_muted'])
        cwd_label.pack(side=tk.RIGHT)

    def _update_title(self):
        """Update window title with file name and modified indicator."""
        buffer = self.tab_manager.active_buffer
        if buffer:
            name = buffer.display_name
            modified = " *" if buffer.modified else ""
            self.root.title(f"{name}{modified} - {self.TITLE}")
        else:
            self.root.title(self.TITLE)

    def _on_buffer_change(self, buffer: EditorBuffer):
        """Handle buffer/tab change."""
        self._update_title()
        if buffer.file_path:
            self.status_var.set(f"Opened: {buffer.file_path}")
        else:
            self.status_var.set("Ready")

    def _on_text_modified(self, event=None):
        """Handle text modification."""
        if self.editor.text.edit_modified():
            self.tab_manager.mark_modified()
            self._update_title()
            self.editor.text.edit_modified(False)

    def _on_cwd_change(self, new_cwd: Path):
        """Handle terminal cwd change."""
        self._cwd = new_cwd
        self.cwd_var.set(str(new_cwd))

    # File operations
    def _new_tab(self):
        """Create a new empty tab."""
        self.tab_manager.new_buffer()
        self._update_title()

    def _open_file(self):
        """Open a file via dialog."""
        path = filedialog.askopenfilename(
            title="Open QuinLang File",
            filetypes=[("QuinLang files", "*.ql"), ("All files", "*.*")],
            initialdir=str(self._cwd),
        )
        if path:
            self.tab_manager.open_file_in_current_tab(Path(path))
            self._update_title()

    def _open_finder(self):
        """Open the fuzzy finder."""
        open_finder(
            self.root,
            self._cwd,
            on_select=self._on_finder_select,
        )

    def _on_finder_select(self, file_path: Path):
        """Handle file selection from finder."""
        self.tab_manager.open_file_in_current_tab(file_path)
        self._update_title()
        self.status_var.set(f"Opened: {file_path}")

    def _save_file(self):
        """Save the current file."""
        if self.tab_manager.save_current_buffer():
            self._update_title()
            buffer = self.tab_manager.active_buffer
            if buffer and buffer.file_path:
                self.status_var.set(f"Saved: {buffer.file_path}")

    def _save_file_as(self):
        """Save to a new file."""
        if self.tab_manager.save_current_buffer_as():
            self._update_title()
            buffer = self.tab_manager.active_buffer
            if buffer and buffer.file_path:
                self.status_var.set(f"Saved: {buffer.file_path}")

    def _close_tab(self):
        """Close the current tab."""
        self.tab_manager.close_current_tab()
        self._update_title()

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

        code = self.tab_manager.get_current_code()
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
        if self.tab_manager.check_all_saved():
            self.root.destroy()

    def _check_for_updates(self):
        """Check for updates in background."""
        checker = UpdateChecker(
            on_update_available=lambda r: self.root.after(0, lambda: self._show_update_dialog(r))
        )
        checker.check_async()

    def _show_update_dialog(self, release: ReleaseInfo):
        """Show update available dialog."""
        result = messagebox.askyesno(
            "Update Available",
            f"A new version of QuinLang IDE is available!\n\n"
            f"Current: v{get_current_version()}\n"
            f"New: v{release.version}\n\n"
            f"Would you like to update now?",
        )
        
        if result:
            self._download_and_apply_update(release)

    def _download_and_apply_update(self, release: ReleaseInfo):
        """Download and apply the update."""
        if not is_frozen():
            messagebox.showinfo(
                "Update",
                "Auto-update is only available for the standalone executable.\n\n"
                "Please download the latest version from GitHub."
            )
            return
        
        self.status_var.set("Downloading update...")
        
        def do_update():
            downloaded = download_update(release)
            if downloaded:
                self.root.after(0, lambda: self._apply_update(downloaded))
            else:
                self.root.after(0, lambda: messagebox.showerror(
                    "Update Failed",
                    "Failed to download the update. Please try again later."
                ))
                self.root.after(0, lambda: self.status_var.set("Ready"))
        
        import threading
        threading.Thread(target=do_update, daemon=True).start()

    def _apply_update(self, downloaded_path):
        """Apply the downloaded update."""
        result = messagebox.askyesno(
            "Apply Update",
            "Update downloaded successfully!\n\n"
            "The application will restart to apply the update.\n"
            "Continue?"
        )
        
        if result:
            if apply_update(downloaded_path):
                self.root.destroy()
            else:
                messagebox.showerror(
                    "Update Failed",
                    "Failed to apply the update. Please try again."
                )
                self.status_var.set("Ready")

    def run(self):
        """Start the application."""
        self.root.mainloop()


def main():
    """Entry point."""
    app = QuinLangIDE()
    app.run()


if __name__ == "__main__":
    main()
