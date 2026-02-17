"""
Tab bar and buffer management for multi-file editing.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, List
import uuid

from .theme import COLORS


@dataclass
class EditorBuffer:
    """Represents a single editor buffer/tab."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file_path: Optional[Path] = None
    content: str = ""
    modified: bool = False
    cursor_pos: str = "1.0"  # Tkinter text index
    
    @property
    def display_name(self) -> str:
        """Get display name for tab."""
        if self.file_path:
            return self.file_path.name
        return "Untitled"
    
    @property
    def tab_title(self) -> str:
        """Get tab title with modified indicator."""
        name = self.display_name
        if self.modified:
            name += " *"
        return name


class TabBar(ttk.Frame):
    """Horizontal tab bar widget."""
    
    def __init__(
        self,
        parent: tk.Widget,
        on_tab_select: Callable[[str], None],
        on_tab_close: Callable[[str], None],
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self._on_tab_select = on_tab_select
        self._on_tab_close = on_tab_close
        self._tabs: dict[str, ttk.Frame] = {}  # buffer_id -> tab frame
        self._active_id: Optional[str] = None
        
        # Tab styles are configured in theme.py via apply_theme()
        self.configure(style="Tab.TFrame")
    
    def add_tab(self, buffer: EditorBuffer):
        """Add a new tab."""
        tab_frame = ttk.Frame(self, style="Tab.TFrame")
        tab_frame.pack(side=tk.LEFT, padx=(0, 1))
        
        # Tab label (clickable)
        label = ttk.Label(tab_frame, text=buffer.tab_title, style="Tab.TLabel")
        label.pack(side=tk.LEFT)
        label.bind("<Button-1>", lambda e, bid=buffer.id: self._on_tab_select(bid))
        
        # Close button
        close_btn = ttk.Label(tab_frame, text="×", style="TabClose.TLabel", cursor="hand2")
        close_btn.pack(side=tk.LEFT)
        close_btn.bind("<Button-1>", lambda e, bid=buffer.id: self._on_tab_close(bid))
        
        # Store references
        tab_frame._label = label
        tab_frame._close_btn = close_btn
        self._tabs[buffer.id] = tab_frame
    
    def remove_tab(self, buffer_id: str):
        """Remove a tab."""
        if buffer_id in self._tabs:
            self._tabs[buffer_id].destroy()
            del self._tabs[buffer_id]
    
    def update_tab(self, buffer: EditorBuffer):
        """Update tab title."""
        if buffer.id in self._tabs:
            tab_frame = self._tabs[buffer.id]
            tab_frame._label.configure(text=buffer.tab_title)
    
    def set_active(self, buffer_id: str):
        """Set the active tab."""
        # Deactivate previous
        if self._active_id and self._active_id in self._tabs:
            old_tab = self._tabs[self._active_id]
            old_tab.configure(style="Tab.TFrame")
            old_tab._label.configure(style="Tab.TLabel")
            old_tab._close_btn.configure(style="TabClose.TLabel")
        
        # Activate new
        if buffer_id in self._tabs:
            new_tab = self._tabs[buffer_id]
            new_tab.configure(style="TabActive.TFrame")
            new_tab._label.configure(style="TabActive.TLabel")
            new_tab._close_btn.configure(style="TabCloseActive.TLabel")
            self._active_id = buffer_id


class TabManager:
    """Manages multiple editor buffers and tabs."""
    
    def __init__(
        self,
        parent: tk.Widget,
        editor_widget: tk.Widget,
        on_buffer_change: Optional[Callable[[EditorBuffer], None]] = None,
    ):
        self._parent = parent
        self._editor = editor_widget
        self._on_buffer_change = on_buffer_change
        
        self._buffers: dict[str, EditorBuffer] = {}
        self._active_id: Optional[str] = None
        
        # Create tab bar
        self.tab_bar = TabBar(
            parent,
            on_tab_select=self._select_tab,
            on_tab_close=self._close_tab,
        )
    
    @property
    def active_buffer(self) -> Optional[EditorBuffer]:
        """Get the currently active buffer."""
        if self._active_id:
            return self._buffers.get(self._active_id)
        return None
    
    @property
    def all_buffers(self) -> List[EditorBuffer]:
        """Get all buffers."""
        return list(self._buffers.values())
    
    def new_buffer(self, content: str = "", file_path: Optional[Path] = None) -> EditorBuffer:
        """Create a new buffer and tab."""
        buffer = EditorBuffer(
            content=content,
            file_path=file_path,
            modified=False,
        )
        self._buffers[buffer.id] = buffer
        self.tab_bar.add_tab(buffer)
        self._select_tab(buffer.id)
        return buffer
    
    def open_file_in_current_tab(self, file_path: Path) -> bool:
        """
        Open a file in the current tab, replacing its content.
        Returns True if successful, False if cancelled.
        """
        if not self._active_id:
            self.new_buffer()
        
        current = self.active_buffer
        
        # Check for unsaved changes
        if current and current.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                f"Save changes to '{current.display_name}' before opening '{file_path.name}'?",
            )
            if result is None:  # Cancel
                return False
            if result:  # Yes - save first
                if not self._save_buffer(current):
                    return False
        
        # Load new file
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file:\n{e}")
            return False
        
        # Update buffer
        current.file_path = file_path
        current.content = content
        current.modified = False
        current.cursor_pos = "1.0"
        
        # Update UI
        self._load_buffer_to_editor(current)
        self.tab_bar.update_tab(current)
        
        if self._on_buffer_change:
            self._on_buffer_change(current)
        
        return True
    
    def save_current_buffer(self) -> bool:
        """Save the current buffer. Returns True if saved."""
        if self.active_buffer:
            return self._save_buffer(self.active_buffer)
        return False
    
    def save_current_buffer_as(self) -> bool:
        """Save the current buffer with a new name. Returns True if saved."""
        if not self.active_buffer:
            return False
        
        path = filedialog.asksaveasfilename(
            title="Save QuinLang File",
            defaultextension=".ql",
            filetypes=[("QuinLang files", "*.ql"), ("All files", "*.*")],
        )
        if path:
            self.active_buffer.file_path = Path(path)
            return self._save_buffer(self.active_buffer)
        return False
    
    def _save_buffer(self, buffer: EditorBuffer) -> bool:
        """Save a buffer to its file. Returns True if saved."""
        if not buffer.file_path:
            # Need to prompt for path
            path = filedialog.asksaveasfilename(
                title="Save QuinLang File",
                defaultextension=".ql",
                filetypes=[("QuinLang files", "*.ql"), ("All files", "*.*")],
            )
            if not path:
                return False
            buffer.file_path = Path(path)
        
        try:
            # Get current content from editor if this is active buffer
            if buffer.id == self._active_id:
                buffer.content = self._editor.get_code()
            
            buffer.file_path.write_text(buffer.content, encoding="utf-8")
            buffer.modified = False
            self.tab_bar.update_tab(buffer)
            
            if self._on_buffer_change:
                self._on_buffer_change(buffer)
            
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}")
            return False
    
    def close_current_tab(self) -> bool:
        """Close the current tab. Returns True if closed."""
        if not self._active_id:
            return False
        return self._close_tab(self._active_id)
    
    def _close_tab(self, buffer_id: str) -> bool:
        """Close a specific tab. Returns True if closed."""
        if buffer_id not in self._buffers:
            return False
        
        buffer = self._buffers[buffer_id]
        
        # Check for unsaved changes
        if buffer.modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                f"Save changes to '{buffer.display_name}'?",
            )
            if result is None:  # Cancel
                return False
            if result:  # Yes - save first
                if not self._save_buffer(buffer):
                    return False
        
        # Remove tab and buffer
        self.tab_bar.remove_tab(buffer_id)
        del self._buffers[buffer_id]
        
        # Select another tab or create new one
        if self._active_id == buffer_id:
            self._active_id = None
            if self._buffers:
                # Select first remaining buffer
                next_id = next(iter(self._buffers))
                self._select_tab(next_id)
            else:
                # No buffers left, create new one
                self.new_buffer()
        
        return True
    
    def _select_tab(self, buffer_id: str):
        """Select a tab and load its content."""
        if buffer_id not in self._buffers:
            return
        
        # Save current buffer state
        if self._active_id and self._active_id in self._buffers:
            current = self._buffers[self._active_id]
            current.content = self._editor.get_code()
            current.cursor_pos = self._editor.text.index(tk.INSERT)
        
        # Switch to new buffer
        self._active_id = buffer_id
        buffer = self._buffers[buffer_id]
        
        # Load content
        self._load_buffer_to_editor(buffer)
        self.tab_bar.set_active(buffer_id)
        
        if self._on_buffer_change:
            self._on_buffer_change(buffer)
    
    def _load_buffer_to_editor(self, buffer: EditorBuffer):
        """Load buffer content into the editor."""
        self._editor.set_code(buffer.content)
        self._editor.text.mark_set(tk.INSERT, buffer.cursor_pos)
        self._editor.text.see(buffer.cursor_pos)
        self._editor.text.edit_modified(False)
    
    def mark_modified(self):
        """Mark the current buffer as modified."""
        if self.active_buffer:
            self.active_buffer.modified = True
            self.tab_bar.update_tab(self.active_buffer)
    
    def check_all_saved(self) -> bool:
        """
        Check all buffers for unsaved changes.
        Returns True if all saved or user chose to discard.
        """
        # First, sync current editor to buffer
        if self._active_id and self._active_id in self._buffers:
            self._buffers[self._active_id].content = self._editor.get_code()
        
        for buffer in self._buffers.values():
            if buffer.modified:
                result = messagebox.askyesnocancel(
                    "Unsaved Changes",
                    f"Save changes to '{buffer.display_name}'?",
                )
                if result is None:  # Cancel
                    return False
                if result:  # Yes - save
                    if not self._save_buffer(buffer):
                        return False
        
        return True
    
    def get_current_code(self) -> str:
        """Get code from the current editor."""
        return self._editor.get_code()
