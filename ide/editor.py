"""
Text editor widget with line numbers.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk


class LineNumbers(tk.Canvas):
    """Canvas widget displaying line numbers."""

    def __init__(self, parent: tk.Widget, text_widget: tk.Text, **kwargs):
        super().__init__(parent, width=50, **kwargs)
        self.text_widget = text_widget
        self.config(bg="#2b2b2b", highlightthickness=0)

    def redraw(self):
        """Redraw line numbers to match the text widget."""
        self.delete("all")

        # Get the visible line range
        first_visible = self.text_widget.index("@0,0")
        last_visible = self.text_widget.index(f"@0,{self.text_widget.winfo_height()}")

        first_line = int(first_visible.split(".")[0])
        last_line = int(last_visible.split(".")[0])

        # Draw line numbers
        for line_num in range(first_line, last_line + 1):
            # Get y-coordinate of this line in the text widget
            dline_info = self.text_widget.dlineinfo(f"{line_num}.0")
            if dline_info:
                y = dline_info[1]
                self.create_text(
                    45, y,
                    anchor="ne",
                    text=str(line_num),
                    fill="#6b6b6b",
                    font=("Consolas", 11)
                )


class CodeEditor(ttk.Frame):
    """Text editor with line numbers for QuinLang code."""

    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, **kwargs)

        # Configure grid
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Create text widget first (needed by LineNumbers)
        self.text = tk.Text(
            self,
            wrap=tk.NONE,
            font=("Consolas", 11),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#ffffff",
            selectbackground="#264f78",
            selectforeground="#ffffff",
            undo=True,
            padx=5,
            pady=5,
        )

        # Create line numbers
        self.line_numbers = LineNumbers(self, self.text, bg="#2b2b2b")
        self.line_numbers.grid(row=0, column=0, sticky="ns")

        # Grid the text widget
        self.text.grid(row=0, column=1, sticky="nsew")

        # Scrollbars
        self.v_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._on_vscroll)
        self.v_scroll.grid(row=0, column=2, sticky="ns")

        self.h_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self.h_scroll.grid(row=1, column=1, sticky="ew")

        self.text.config(
            yscrollcommand=self._on_text_yscroll,
            xscrollcommand=self.h_scroll.set
        )

        # Bind events for line number updates
        self.text.bind("<KeyRelease>", self._on_change)
        self.text.bind("<MouseWheel>", self._on_change)
        self.text.bind("<Configure>", self._on_change)

        # Initial line number draw
        self.after(10, self.line_numbers.redraw)

    def _on_vscroll(self, *args):
        """Handle vertical scrollbar movement."""
        self.text.yview(*args)
        self.line_numbers.redraw()

    def _on_text_yscroll(self, first, last):
        """Handle text widget scroll."""
        self.v_scroll.set(first, last)
        self.line_numbers.redraw()

    def _on_change(self, event=None):
        """Handle text changes."""
        self.line_numbers.redraw()

    def get_code(self) -> str:
        """Get the current code from the editor."""
        return self.text.get("1.0", tk.END).rstrip("\n")

    def set_code(self, code: str):
        """Set the code in the editor."""
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", code)
        self.line_numbers.redraw()

    def clear(self):
        """Clear the editor."""
        self.text.delete("1.0", tk.END)
        self.line_numbers.redraw()
