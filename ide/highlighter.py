"""
Syntax highlighting for QuinLang code.
"""
from __future__ import annotations
import re
import tkinter as tk
from typing import List, Tuple


# QuinLang syntax definitions
KEYWORDS = {
    'fn', 'let', 'if', 'else', 'while', 'return', 'true', 'false',
}

TYPES = {
    'int', 'bool', 'str', 'ptr', 'void',
}

BUILTINS = {
    'print', 'println', 'load16', 'store16', 'memcpy', 'memset',
    'array_push', 'array_pop',
}

# Import colors from theme
from .theme import COLORS as THEME_COLORS

# Syntax highlighting colors (exported for finder preview)
SYNTAX_COLORS = {
    'keyword': THEME_COLORS['syntax_keyword'],
    'type': THEME_COLORS['syntax_type'],
    'builtin': THEME_COLORS['syntax_builtin'],
    'string': THEME_COLORS['syntax_string'],
    'number': THEME_COLORS['syntax_number'],
    'comment': THEME_COLORS['syntax_comment'],
    'operator': THEME_COLORS['text_primary'],
}

# Alias for backward compatibility
COLORS = SYNTAX_COLORS


class SyntaxHighlighter:
    """Applies syntax highlighting to a Tkinter Text widget."""
    
    def __init__(self, text_widget: tk.Text):
        self.text = text_widget
        self._setup_tags()
    
    def _setup_tags(self):
        """Configure text tags for each syntax element."""
        for name, color in COLORS.items():
            self.text.tag_configure(name, foreground=color)
        
        # Set tag priorities (higher = applied later = wins)
        self.text.tag_raise('comment')  # Comments override everything
        self.text.tag_raise('string')   # Strings override keywords inside them
    
    def highlight_all(self):
        """Highlight the entire text content."""
        # Remove existing tags
        for tag in COLORS.keys():
            self.text.tag_remove(tag, "1.0", tk.END)
        
        content = self.text.get("1.0", tk.END)
        
        # Apply highlighting
        self._highlight_comments(content)
        self._highlight_strings(content)
        self._highlight_numbers(content)
        self._highlight_keywords(content)
        self._highlight_types(content)
        self._highlight_builtins(content)
    
    def highlight_line(self, line_num: int):
        """Highlight a single line."""
        start = f"{line_num}.0"
        end = f"{line_num}.end"
        
        # Remove existing tags on this line
        for tag in COLORS.keys():
            self.text.tag_remove(tag, start, end)
        
        line_content = self.text.get(start, end)
        
        # Apply highlighting to this line
        self._highlight_comments(line_content, line_num)
        self._highlight_strings(line_content, line_num)
        self._highlight_numbers(line_content, line_num)
        self._highlight_keywords(line_content, line_num)
        self._highlight_types(line_content, line_num)
        self._highlight_builtins(line_content, line_num)
    
    def _highlight_pattern(
        self,
        pattern: str,
        tag: str,
        content: str,
        line_offset: int = 0
    ):
        """Apply a tag to all matches of a regex pattern."""
        for match in re.finditer(pattern, content, re.MULTILINE):
            start_idx = match.start()
            end_idx = match.end()
            
            if line_offset:
                # Single line mode
                start = f"{line_offset}.{start_idx}"
                end = f"{line_offset}.{end_idx}"
            else:
                # Full text mode - convert index to line.col
                start = self._index_to_pos(content, start_idx)
                end = self._index_to_pos(content, end_idx)
            
            self.text.tag_add(tag, start, end)
    
    def _index_to_pos(self, content: str, index: int) -> str:
        """Convert a string index to Tkinter line.col position."""
        lines = content[:index].split('\n')
        line_num = len(lines)
        col = len(lines[-1])
        return f"{line_num}.{col}"
    
    def _highlight_comments(self, content: str, line_offset: int = 0):
        """Highlight // comments."""
        self._highlight_pattern(r'//.*$', 'comment', content, line_offset)
    
    def _highlight_strings(self, content: str, line_offset: int = 0):
        """Highlight string literals."""
        self._highlight_pattern(r'"[^"\\]*(?:\\.[^"\\]*)*"', 'string', content, line_offset)
    
    def _highlight_numbers(self, content: str, line_offset: int = 0):
        """Highlight numeric literals."""
        # Decimal and hex numbers
        self._highlight_pattern(r'\b(?:0x[0-9a-fA-F]+|\d+)\b', 'number', content, line_offset)
    
    def _highlight_keywords(self, content: str, line_offset: int = 0):
        """Highlight keywords."""
        pattern = r'\b(' + '|'.join(KEYWORDS) + r')\b'
        self._highlight_pattern(pattern, 'keyword', content, line_offset)
    
    def _highlight_types(self, content: str, line_offset: int = 0):
        """Highlight type names."""
        # Match types, including array types like int[3]
        pattern = r'\b(' + '|'.join(TYPES) + r')(?:\[\d+\])?\b'
        self._highlight_pattern(pattern, 'type', content, line_offset)
    
    def _highlight_builtins(self, content: str, line_offset: int = 0):
        """Highlight builtin functions."""
        pattern = r'\b(' + '|'.join(BUILTINS) + r')\b'
        self._highlight_pattern(pattern, 'builtin', content, line_offset)


def highlight_text_widget(text_widget: tk.Text, content: str):
    """
    Highlight content in a text widget (convenience function).
    Used for preview panes where we set content then highlight.
    """
    text_widget.config(state=tk.NORMAL)
    text_widget.delete("1.0", tk.END)
    text_widget.insert("1.0", content)
    
    highlighter = SyntaxHighlighter(text_widget)
    highlighter.highlight_all()
    
    text_widget.config(state=tk.DISABLED)


def get_highlighted_tags() -> dict:
    """Return the color configuration for external use."""
    return COLORS.copy()
