"""
Embedded command line terminal widget.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
import subprocess
import threading
import os
from pathlib import Path
from typing import Optional, List, Callable

from .theme import COLORS, FONTS


class CommandLine(ttk.Frame):
    """
    Embedded command line widget.
    Executes shell commands and displays output.
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        initial_cwd: Optional[Path] = None,
        on_cwd_change: Optional[Callable[[Path], None]] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        
        self._cwd = initial_cwd or Path.cwd()
        self._on_cwd_change = on_cwd_change
        self._history: List[str] = []
        self._history_index = 0
        self._running_process: Optional[subprocess.Popen] = None
        
        self._build_ui()
    
    @property
    def cwd(self) -> Path:
        """Get current working directory."""
        return self._cwd
    
    @cwd.setter
    def cwd(self, value: Path):
        """Set current working directory."""
        if value.is_dir():
            self._cwd = value
            self._update_prompt()
            if self._on_cwd_change:
                self._on_cwd_change(value)
    
    def _build_ui(self):
        """Build the terminal UI."""
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Output display
        output_frame = ttk.Frame(self)
        output_frame.grid(row=0, column=0, sticky="nsew")
        output_frame.grid_rowconfigure(0, weight=1)
        output_frame.grid_columnconfigure(0, weight=1)
        
        self._output_text = tk.Text(
            output_frame,
            height=8,
            wrap=tk.WORD,
            font=FONTS['code_small'],
            bg=COLORS['bg_dark'],
            fg=COLORS['text_primary'],
            insertbackground=COLORS['text_primary'],
            state=tk.DISABLED,
            highlightthickness=0,
            borderwidth=0,
            takefocus=False,  # Don't let output steal focus
            cursor="arrow",   # Show arrow cursor instead of I-beam
        )
        self._output_text.grid(row=0, column=0, sticky="nsew")
        
        # Scrollbar for output
        scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self._output_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._output_text.config(yscrollcommand=scrollbar.set)
        
        # Configure output tags
        self._output_text.tag_configure("prompt", foreground=COLORS['accent'])
        self._output_text.tag_configure("command", foreground=COLORS['text_primary'])
        self._output_text.tag_configure("error", foreground=COLORS['error'])
        self._output_text.tag_configure("info", foreground=COLORS['text_muted'])
        
        # Input frame - use tk.Frame for explicit background control
        input_frame = tk.Frame(self, bg=COLORS['bg_medium'])
        input_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        input_frame.grid_columnconfigure(1, weight=1)
        
        # Prompt label
        self._prompt_var = tk.StringVar()
        self._update_prompt()
        
        prompt_label = tk.Label(
            input_frame,
            textvariable=self._prompt_var,
            font=FONTS['code_small'],
            fg=COLORS['accent'],
            bg=COLORS['bg_medium'],
        )
        prompt_label.grid(row=0, column=0, sticky="w")
        
        # Command entry - use single-line Text widget for reliable Windows styling
        self._command_entry = tk.Text(
            input_frame,
            height=1,
            width=40,
            font=FONTS['code_small'],
            bg=COLORS['bg_dark'],
            fg="#FFFFFF",                    # White text for maximum visibility
            insertbackground=COLORS['accent_bright'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['accent_dim'],
            highlightcolor=COLORS['accent'],
            selectbackground=COLORS['accent'],
            selectforeground=COLORS['bg_dark'],
            wrap=tk.NONE,
            undo=True,
            padx=4,
            pady=4,
        )
        self._command_entry.grid(row=0, column=1, sticky="ew", padx=(5, 0), ipady=4)
        
        # Bind keys
        self._command_entry.bind("<Return>", self._on_enter)
        self._command_entry.bind("<Up>", self._on_history_up)
        self._command_entry.bind("<Down>", self._on_history_down)
        self._command_entry.bind("<Escape>", self._on_escape)
        
        # Click anywhere in terminal to focus input
        # Use ButtonRelease and after() to ensure focus happens after click processing
        def focus_entry(e=None):
            self._command_entry.focus_set()
            return "break"
        
        self._output_text.bind("<ButtonRelease-1>", lambda e: self.after(10, focus_entry))
        self._output_text.bind("<Double-Button-1>", lambda e: "break")  # Prevent text selection
        self.bind("<Button-1>", focus_entry)
        output_frame.bind("<Button-1>", focus_entry)
        
        # Initial message
        self._append_output("Terminal ready. Click here and type commands.\n", "info")
        
        # Auto-focus the entry after widget is mapped
        self._command_entry.bind("<Map>", lambda e: self.after(100, focus_entry))
    
    def _update_prompt(self):
        """Update the prompt to show current directory."""
        # Shorten path for display
        try:
            home = Path.home()
            if self._cwd.is_relative_to(home):
                display_path = "~/" + str(self._cwd.relative_to(home))
            else:
                display_path = str(self._cwd)
        except (ValueError, RuntimeError):
            display_path = str(self._cwd)
        
        # Truncate if too long
        if len(display_path) > 40:
            display_path = "..." + display_path[-37:]
        
        self._prompt_var.set(f"{display_path} $")
    
    def _get_command(self) -> str:
        """Get the current command text."""
        return self._command_entry.get("1.0", "end-1c").strip()
    
    def _set_command(self, text: str):
        """Set the command text."""
        self._command_entry.delete("1.0", tk.END)
        self._command_entry.insert("1.0", text)
    
    def _on_enter(self, event):
        """Handle Enter key - execute command."""
        command = self._get_command()
        if not command:
            return "break"
        
        # Add to history
        if not self._history or self._history[-1] != command:
            self._history.append(command)
        self._history_index = len(self._history)
        
        # Clear input
        self._set_command("")
        
        # Show command in output
        self._append_output(f"{self._prompt_var.get()} ", "prompt")
        self._append_output(f"{command}\n", "command")
        
        # Execute command
        self._execute_command(command)
        
        return "break"
    
    def _on_history_up(self, event):
        """Navigate history up."""
        if self._history and self._history_index > 0:
            self._history_index -= 1
            self._set_command(self._history[self._history_index])
            # Move cursor to end
            self._command_entry.mark_set(tk.INSERT, tk.END)
        return "break"
    
    def _on_history_down(self, event):
        """Navigate history down."""
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._set_command(self._history[self._history_index])
        elif self._history_index == len(self._history) - 1:
            self._history_index = len(self._history)
            self._set_command("")
        return "break"
    
    def _on_escape(self, event):
        """Clear current input."""
        self._set_command("")
        self._history_index = len(self._history)
        return "break"
    
    def _execute_command(self, command: str):
        """Execute a shell command."""
        # Handle built-in commands
        parts = command.split()
        if not parts:
            return
        
        cmd = parts[0].lower()
        
        # Handle 'cd' specially
        if cmd == "cd":
            self._handle_cd(parts[1] if len(parts) > 1 else None)
            return
        
        # Handle 'clear' / 'cls'
        if cmd in ("clear", "cls"):
            self._clear_output()
            return
        
        # Run external command in thread
        threading.Thread(
            target=self._run_subprocess,
            args=(command,),
            daemon=True
        ).start()
    
    def _handle_cd(self, path_str: Optional[str]):
        """Handle cd command."""
        if path_str is None:
            # cd with no args goes to home
            new_path = Path.home()
        elif path_str == "-":
            # Could implement previous directory, for now just ignore
            self._append_output("cd -: not implemented\n", "info")
            return
        else:
            # Resolve path
            if path_str.startswith("~"):
                new_path = Path.home() / path_str[2:]
            else:
                new_path = self._cwd / path_str
        
        try:
            new_path = new_path.resolve()
            if new_path.is_dir():
                self.cwd = new_path
                self._append_output(f"Changed to: {new_path}\n", "info")
            else:
                self._append_output(f"Not a directory: {new_path}\n", "error")
        except Exception as e:
            self._append_output(f"Error: {e}\n", "error")
    
    def _run_subprocess(self, command: str):
        """Run a subprocess and capture output."""
        try:
            # Use shell=True for Windows compatibility
            self._running_process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(self._cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            
            # Read output line by line
            for line in self._running_process.stdout:
                self._append_output_threadsafe(line)
            
            self._running_process.wait()
            
            if self._running_process.returncode != 0:
                self._append_output_threadsafe(
                    f"[Exit code: {self._running_process.returncode}]\n",
                    "error"
                )
        
        except Exception as e:
            self._append_output_threadsafe(f"Error: {e}\n", "error")
        
        finally:
            self._running_process = None
    
    def _append_output(self, text: str, tag: Optional[str] = None):
        """Append text to output (must be called from main thread)."""
        self._output_text.config(state=tk.NORMAL)
        if tag:
            self._output_text.insert(tk.END, text, tag)
        else:
            self._output_text.insert(tk.END, text)
        self._output_text.see(tk.END)
        self._output_text.config(state=tk.DISABLED)
    
    def _append_output_threadsafe(self, text: str, tag: Optional[str] = None):
        """Append text to output from any thread."""
        self.after(0, lambda: self._append_output(text, tag))
    
    def _clear_output(self):
        """Clear the output display."""
        self._output_text.config(state=tk.NORMAL)
        self._output_text.delete("1.0", tk.END)
        self._output_text.config(state=tk.DISABLED)
    
    def focus_input(self):
        """Focus the command input."""
        self._command_entry.focus_set()
    
    def stop_running(self):
        """Stop any running process."""
        if self._running_process:
            try:
                self._running_process.terminate()
                self._append_output("\n[Process terminated]\n", "error")
            except Exception:
                pass
