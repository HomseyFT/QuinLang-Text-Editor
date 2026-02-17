"""
Centralized theme configuration for QuinLang IDE.
"""

# Navy Blue Theme
COLORS = {
    # Base colors
    'bg_dark': '#0a1628',        # Darkest navy - main background
    'bg_medium': '#122240',      # Medium navy - panels, tabs
    'bg_light': '#1a3358',       # Lighter navy - active elements, accents
    'bg_highlight': '#2a4a7a',   # Highlight navy - hover states
    
    # Text colors
    'text_primary': '#f0e6a0',   # Light yellow - main text
    'text_secondary': '#b8a860', # Muted yellow - secondary text
    'text_muted': '#6a7a9a',     # Muted blue-gray - comments, hints
    
    # Accent colors
    'accent': '#5b9bd5',         # Light blue - accents, highlights
    'accent_bright': '#7ec8f0',  # Brighter blue - active states
    'accent_dim': '#3d6a94',     # Dimmer blue - borders
    
    # Semantic colors
    'success': '#7ec97e',        # Green - success messages
    'error': '#e06060',          # Red - errors
    'warning': '#e0c060',        # Yellow/gold - warnings
    'info': '#5b9bd5',           # Blue - info messages
    
    # Syntax highlighting
    'syntax_keyword': '#c490d0',  # Purple - keywords
    'syntax_type': '#5bbbbb',     # Teal - types
    'syntax_builtin': '#e0c060',  # Gold - builtins
    'syntax_string': '#d09070',   # Orange - strings
    'syntax_number': '#a0d0a0',   # Light green - numbers
    'syntax_comment': '#6a7a6a',  # Gray-green - comments
}

# Font configuration
FONTS = {
    'code': ('Consolas', 11),
    'code_small': ('Consolas', 10),
    'ui': ('Segoe UI', 10),
}


def apply_theme(root, style):
    """Apply the theme to ttk style and root window."""
    style.theme_use("clam")
    
    # General
    style.configure(".", 
                    background=COLORS['bg_medium'], 
                    foreground=COLORS['text_primary'])
    
    # Frames
    style.configure("TFrame", background=COLORS['bg_medium'])
    
    # Labels
    style.configure("TLabel", 
                    background=COLORS['bg_medium'], 
                    foreground=COLORS['text_primary'])
    
    # Buttons
    style.configure("TButton", 
                    background=COLORS['bg_light'], 
                    foreground=COLORS['text_primary'])
    style.map("TButton",
              background=[("active", COLORS['bg_highlight']), 
                         ("pressed", COLORS['accent_dim'])])
    
    # Entry
    style.configure("TEntry",
                    fieldbackground=COLORS['bg_dark'],
                    foreground=COLORS['text_primary'])
    
    # PanedWindow
    style.configure("TPanedwindow", background=COLORS['bg_medium'])
    
    # Scrollbar
    style.configure("TScrollbar",
                    background=COLORS['bg_light'],
                    troughcolor=COLORS['bg_dark'])
    
    # Separator
    style.configure("TSeparator", background=COLORS['accent_dim'])
    
    # Tab styles
    style.configure("Tab.TFrame", background=COLORS['bg_medium'])
    style.configure("TabActive.TFrame", background=COLORS['bg_dark'])
    style.configure("Tab.TLabel", 
                    background=COLORS['bg_medium'], 
                    foreground=COLORS['text_muted'],
                    padding=(10, 5))
    style.configure("TabActive.TLabel", 
                    background=COLORS['bg_dark'], 
                    foreground=COLORS['text_primary'],
                    padding=(10, 5))
    style.configure("TabClose.TLabel", 
                    background=COLORS['bg_medium'], 
                    foreground=COLORS['text_muted'],
                    padding=(2, 5))
    style.configure("TabCloseActive.TLabel", 
                    background=COLORS['bg_dark'], 
                    foreground=COLORS['text_primary'],
                    padding=(2, 5))
    
    # Root window
    root.configure(bg=COLORS['bg_medium'])


def get_text_widget_config():
    """Get configuration dict for tk.Text widgets."""
    return {
        'bg': COLORS['bg_dark'],
        'fg': COLORS['text_primary'],
        'insertbackground': COLORS['text_primary'],
        'selectbackground': COLORS['accent'],
        'selectforeground': COLORS['bg_dark'],
        'highlightthickness': 0,
        'borderwidth': 0,
    }


def get_entry_widget_config():
    """Get configuration dict for tk.Entry widgets."""
    return {
        'bg': COLORS['bg_dark'],
        'fg': COLORS['text_primary'],
        'insertbackground': COLORS['text_primary'],
        'relief': 'flat',
        'highlightthickness': 1,
        'highlightbackground': COLORS['accent_dim'],
        'highlightcolor': COLORS['accent'],
    }
