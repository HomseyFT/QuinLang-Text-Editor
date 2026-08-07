"""
Syntax highlighting for QuinLang code.
"""
from __future__ import annotations
import re
import tkinter as tk
from bisect import bisect_right
from typing import List

from .theme import COLORS as THEME_COLORS


# QuinLang syntax definitions.
# These mirror compiler/tokens.py KEYWORDS and compiler/builtins.py get_builtins();
# update them together when the language changes.
KEYWORDS = {
    'fn', 'let', 'if', 'else', 'while', 'return', 'true', 'false',
    'include', 'vm_asm',
}

TYPES = {
    'int', 'str', 'ptr', 'void', 'heapptr',
}

BUILTINS = {
    'print', 'println',
    'load16', 'store16', 'memcpy', 'memset',
    'array_push', 'array_pop',
    'alloc', 'heap_load', 'heap_store',
    'ct_eq', 'ct_select',
}

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


def _word_pattern(words: set) -> str:
    """Build an anchored alternation matching any of `words` as a whole word."""
    return r'\b(?:' + '|'.join(sorted(words, key=len, reverse=True)) + r')\b'


KEYWORD_RE = re.compile(_word_pattern(KEYWORDS))
TYPE_RE = re.compile(_word_pattern(TYPES))
BUILTIN_RE = re.compile(_word_pattern(BUILTINS))
NUMBER_RE = re.compile(r'\b(?:0x[0-9a-fA-F]+|\d+)\b')

# Comments and strings are matched in ONE pass so the leftmost token wins.
# This keeps `// "quoted"` a comment and `"http://x"` a string, which separate
# passes get wrong in one direction or the other.
COMMENT_OR_STRING_RE = re.compile(
    r'(?P<comment>//[^\n]*)'
    r'|(?P<string>"[^"\\\n]*(?:\\.[^"\\\n]*)*")'
)


class SyntaxHighlighter:
    """Applies syntax highlighting to a Tkinter Text widget."""

    def __init__(self, text_widget: tk.Text):
        self.text = text_widget
        self._setup_tags()

    def _setup_tags(self):
        """Configure text tags for each syntax element."""
        for name, color in SYNTAX_COLORS.items():
            self.text.tag_configure(name, foreground=color)

        # Priority: later raises win. Strings and comments must outrank word
        # tags so a keyword inside a string or comment is not recoloured.
        for name in ('operator', 'number', 'builtin', 'type', 'keyword'):
            self.text.tag_raise(name)
        self.text.tag_raise('string')
        self.text.tag_raise('comment')

    def highlight_all(self):
        """Highlight the entire text content."""
        content = self.text.get("1.0", tk.END)

        for tag in SYNTAX_COLORS:
            self.text.tag_remove(tag, "1.0", tk.END)

        # Offsets of each line start, so index->"line.col" is a binary search
        # instead of re-splitting the prefix for every match.
        line_starts = self._line_starts(content)

        # Word-level tags first; strings/comments are layered on top and win by
        # tag priority.
        for regex, tag in (
            (NUMBER_RE, 'number'),
            (KEYWORD_RE, 'keyword'),
            (TYPE_RE, 'type'),
            (BUILTIN_RE, 'builtin'),
        ):
            self._apply(regex, tag, content, line_starts)

        for match in COMMENT_OR_STRING_RE.finditer(content):
            tag = 'comment' if match.lastgroup == 'comment' else 'string'
            self.text.tag_add(
                tag,
                self._pos(line_starts, match.start()),
                self._pos(line_starts, match.end()),
            )

    def _apply(self, regex, tag: str, content: str, line_starts: List[int]):
        """Tag every match of `regex` in `content`."""
        for match in regex.finditer(content):
            self.text.tag_add(
                tag,
                self._pos(line_starts, match.start()),
                self._pos(line_starts, match.end()),
            )

    @staticmethod
    def _line_starts(content: str) -> List[int]:
        """Character offset at which each line begins."""
        starts = [0]
        for i, char in enumerate(content):
            if char == '\n':
                starts.append(i + 1)
        return starts

    @staticmethod
    def _pos(line_starts: List[int], index: int) -> str:
        """Convert a string index to a Tkinter line.col position."""
        line = bisect_right(line_starts, index) - 1
        return f"{line + 1}.{index - line_starts[line]}"


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
    return SYNTAX_COLORS.copy()
