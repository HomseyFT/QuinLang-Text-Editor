"""
Fuzzy finder for file navigation.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional, Callable, List, Tuple
import os

from .highlighter import highlight_text_widget
from .theme import COLORS, FONTS


# File extensions to include (empty = all files)
INCLUDED_EXTENSIONS = {'.ql', '.py', '.txt', '.md', '.json', '.yaml', '.yml', '.toml'}

# Directories to exclude
EXCLUDED_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules', 
    'venv', '.venv', 'env', '.env', 'dist', 'build', '.idea', '.vscode'
}

# Maximum files to scan
MAX_FILES = 1000


def fuzzy_match(query: str, text: str) -> Tuple[bool, int]:
    """
    Fuzzy match query against text.
    Returns (matches, score) where higher score = better match.
    """
    if not query:
        return True, 0
    
    query = query.lower()
    text_lower = text.lower()
    
    # Exact substring match gets highest score
    if query in text_lower:
        # Bonus for prefix match
        if text_lower.startswith(query):
            return True, 1000 + len(query)
        return True, 500 + len(query)
    
    # Fuzzy character matching
    query_idx = 0
    score = 0
    last_match_idx = -1
    consecutive_bonus = 0
    
    for i, char in enumerate(text_lower):
        if query_idx < len(query) and char == query[query_idx]:
            query_idx += 1
            
            # Bonus for consecutive matches
            if last_match_idx == i - 1:
                consecutive_bonus += 10
            else:
                consecutive_bonus = 0
            
            score += 10 + consecutive_bonus
            
            # Bonus for matching at word boundaries
            if i == 0 or text[i-1] in '._-/ ':
                score += 20
            
            last_match_idx = i
    
    # All query characters must match
    if query_idx == len(query):
        return True, score
    
    return False, 0


def scan_files(root_dir: Path) -> List[Path]:
    """
    Recursively scan directory for files.
    Returns list of file paths relative to root_dir.
    """
    files = []
    
    try:
        for entry in os.scandir(root_dir):
            if len(files) >= MAX_FILES:
                break
            
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in EXCLUDED_DIRS and not entry.name.startswith('.'):
                    files.extend(scan_files(Path(entry.path)))
            elif entry.is_file():
                path = Path(entry.path)
                # Include all files or filter by extension
                if not INCLUDED_EXTENSIONS or path.suffix.lower() in INCLUDED_EXTENSIONS:
                    files.append(path)
    except PermissionError:
        pass
    
    return files


class FinderDialog(tk.Toplevel):
    """Modal fuzzy finder dialog."""
    
    def __init__(
        self,
        parent: tk.Widget,
        root_dir: Path,
        on_select: Callable[[Path], None],
    ):
        super().__init__(parent)
        self._root_dir = root_dir
        self._on_select = on_select
        self._files: List[Path] = []
        self._filtered_files: List[Tuple[Path, int]] = []  # (path, score)
        self._selected_index = 0
        
        # Configure window
        self.title("Find File")
        self.geometry("800x500")
        self.transient(parent)
        self.grab_set()
        
        # Center on parent
        self.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        w = self.winfo_width()
        h = self.winfo_height()
        x = parent_x + (parent_w - w) // 2
        y = parent_y + (parent_h - h) // 2
        self.geometry(f"+{x}+{y}")
        
        # Dark theme
        self.configure(bg=COLORS['bg_medium'])
        
        self._build_ui()
        self._scan_files()
        
        # Bind keys
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", self._on_enter)
        self.bind("<Up>", self._on_up)
        self.bind("<Down>", self._on_down)
        
        # Focus search entry
        self._search_entry.focus_set()
    
    def _build_ui(self):
        """Build the finder UI."""
        # Search bar at top
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(
            search_frame, 
            text="Search:", 
            background=COLORS['bg_medium'], 
            foreground=COLORS['text_primary']
        ).pack(side=tk.LEFT)
        
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_change)
        
        self._search_entry = ttk.Entry(
            search_frame,
            textvariable=self._search_var,
            font=FONTS['code'],
        )
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        # Main content area with file list and preview
        content_frame = ttk.Frame(self)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Use PanedWindow for resizable split
        paned = ttk.PanedWindow(content_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # File list (left side)
        list_frame = ttk.Frame(paned)
        
        self._file_listbox = tk.Listbox(
            list_frame,
            font=FONTS['code_small'],
            bg=COLORS['bg_dark'],
            fg=COLORS['text_primary'],
            selectbackground=COLORS['accent'],
            selectforeground=COLORS['bg_dark'],
            highlightthickness=0,
            borderwidth=0,
        )
        self._file_listbox.pack(fill=tk.BOTH, expand=True)
        self._file_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self._file_listbox.bind("<Double-Button-1>", self._on_enter)
        
        paned.add(list_frame, weight=1)
        
        # Preview pane (right side)
        preview_frame = ttk.Frame(paned)
        
        preview_label = ttk.Label(
            preview_frame,
            text="Preview",
            background=COLORS['bg_medium'],
            foreground=COLORS['text_muted'],
        )
        preview_label.pack(anchor=tk.W)
        
        self._preview_text = tk.Text(
            preview_frame,
            font=FONTS['code_small'],
            bg=COLORS['bg_dark'],
            fg=COLORS['text_primary'],
            wrap=tk.NONE,
            state=tk.DISABLED,
            highlightthickness=0,
            borderwidth=0,
        )
        self._preview_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure syntax highlighting tags (from highlighter)
        from .highlighter import SYNTAX_COLORS
        for name, color in SYNTAX_COLORS.items():
            self._preview_text.tag_configure(name, foreground=color)
        
        paned.add(preview_frame, weight=2)
        
        # Status bar
        self._status_var = tk.StringVar(value="Scanning...")
        status = ttk.Label(
            self,
            textvariable=self._status_var,
            background=COLORS['bg_medium'],
            foreground=COLORS['text_muted'],
        )
        status.pack(fill=tk.X, padx=10, pady=(0, 5))
    
    def _scan_files(self):
        """Scan directory for files."""
        self._files = scan_files(self._root_dir)
        self._filter_files()
        self._status_var.set(f"{len(self._files)} files indexed from {self._root_dir}")
    
    def _filter_files(self):
        """Filter files based on search query."""
        query = self._search_var.get().strip()
        
        if not query:
            # Show all files, sorted alphabetically
            self._filtered_files = [(f, 0) for f in sorted(self._files, key=lambda p: p.name.lower())]
        else:
            # Fuzzy match and sort by score
            matches = []
            for file_path in self._files:
                # Match against filename
                is_match, score = fuzzy_match(query, file_path.name)
                if is_match:
                    matches.append((file_path, score))
            
            # Sort by score (descending)
            matches.sort(key=lambda x: x[1], reverse=True)
            self._filtered_files = matches
        
        # Update listbox
        self._file_listbox.delete(0, tk.END)
        for file_path, _ in self._filtered_files[:100]:  # Limit display
            # Show relative path
            try:
                rel_path = file_path.relative_to(self._root_dir)
            except ValueError:
                rel_path = file_path
            self._file_listbox.insert(tk.END, str(rel_path))
        
        # Select first item
        if self._filtered_files:
            self._selected_index = 0
            self._file_listbox.selection_set(0)
            self._file_listbox.see(0)
            self._update_preview()
    
    def _on_search_change(self, *args):
        """Handle search text change."""
        self._filter_files()
    
    def _on_listbox_select(self, event):
        """Handle listbox selection."""
        selection = self._file_listbox.curselection()
        if selection:
            self._selected_index = selection[0]
            self._update_preview()
    
    def _on_up(self, event):
        """Handle up arrow."""
        if self._selected_index > 0:
            self._selected_index -= 1
            self._file_listbox.selection_clear(0, tk.END)
            self._file_listbox.selection_set(self._selected_index)
            self._file_listbox.see(self._selected_index)
            self._update_preview()
        return "break"
    
    def _on_down(self, event):
        """Handle down arrow."""
        if self._selected_index < len(self._filtered_files) - 1:
            self._selected_index += 1
            self._file_listbox.selection_clear(0, tk.END)
            self._file_listbox.selection_set(self._selected_index)
            self._file_listbox.see(self._selected_index)
            self._update_preview()
        return "break"
    
    def _on_enter(self, event=None):
        """Handle Enter key - select file."""
        if self._filtered_files and self._selected_index < len(self._filtered_files):
            selected_path = self._filtered_files[self._selected_index][0]
            self.destroy()
            self._on_select(selected_path)
        return "break"
    
    def _update_preview(self):
        """Update the preview pane with selected file content."""
        if not self._filtered_files or self._selected_index >= len(self._filtered_files):
            self._preview_text.config(state=tk.NORMAL)
            self._preview_text.delete("1.0", tk.END)
            self._preview_text.config(state=tk.DISABLED)
            return
        
        file_path = self._filtered_files[self._selected_index][0]
        
        try:
            content = file_path.read_text(encoding="utf-8")
            # Limit preview to first 200 lines
            lines = content.split('\n')[:200]
            content = '\n'.join(lines)
            
            # Apply syntax highlighting for .ql files
            if file_path.suffix.lower() == '.ql':
                highlight_text_widget(self._preview_text, content)
            else:
                self._preview_text.config(state=tk.NORMAL)
                self._preview_text.delete("1.0", tk.END)
                self._preview_text.insert("1.0", content)
                self._preview_text.config(state=tk.DISABLED)
        except Exception as e:
            self._preview_text.config(state=tk.NORMAL)
            self._preview_text.delete("1.0", tk.END)
            self._preview_text.insert("1.0", f"Error reading file:\n{e}")
            self._preview_text.config(state=tk.DISABLED)


def open_finder(parent: tk.Widget, root_dir: Path, on_select: Callable[[Path], None]):
    """Open the fuzzy finder dialog."""
    FinderDialog(parent, root_dir, on_select)
