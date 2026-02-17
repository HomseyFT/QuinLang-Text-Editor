# QuinLang IDE

A lightweight, self-contained IDE for the QuinLang programming language. This application bundles the full QuinLang compiler and QuinVM interpreter, providing an integrated environment for writing, running, and debugging QL programs.

## Features

### Code Editor
- **Tabbed Editing** — Work with multiple files simultaneously
- **Line Numbers** — Easy code navigation
- **Syntax Highlighting** — Color-coded keywords, types, strings, comments, and numbers
- **Unsaved Changes Detection** — Prompts before closing modified files

### Fuzzy Finder
- **Quick File Search** — Press `Ctrl+Shift+F` to open
- **Fuzzy Matching** — Type partial filenames to filter results
- **Live Preview** — See file contents with syntax highlighting before opening
- **Keyboard Navigation** — Use arrow keys to browse, Enter to open

### Integrated Terminal
- **Built-in Command Line** — Run shell commands without leaving the IDE
- **Directory Navigation** — Use `cd` to change directories
- **Command History** — Press Up/Down arrows to recall previous commands
- **Persistent Working Directory** — Terminal remembers your current location

### Compiler & Runtime
- **Full QuinLang Compiler** — Lexer, parser, semantic analysis, bytecode generation
- **QuinVM Interpreter** — Programs execute directly in the embedded virtual machine
- **Run/Stop Controls** — Execute and terminate programs with toolbar buttons or hotkeys
- **Output Panel** — View program output with colored error messages and diagnostics

### Auto-Updater
- **Automatic Update Checks** — Notified when new versions are available
- **One-Click Updates** — Download and install updates directly from the IDE
- **Seamless Restart** — Application restarts automatically after updating

## Download

Pre-built executables are available on the [Releases](../../releases) page:

- **Windows**: `QuinLangIDE-windows-x64.exe` — Double-click to run
- **Linux**: `QuinLangIDE-linux-x64` — Run `chmod +x QuinLangIDE-linux-x64 && ./QuinLangIDE-linux-x64`

No installation or Python required for the standalone executables.

## Running from Source

### Requirements

- Python 3.10+
- Tkinter (included with standard Python on Windows/macOS)

### Quick Start

```bash
python run_ide.py
```

The IDE opens with a simple example program. Click **Run** or press **F5** to execute it.

## Keyboard Shortcuts

### File Operations
| Action          | Shortcut       |
|-----------------|----------------|
| New Tab         | Ctrl+N         |
| Open File       | Ctrl+O         |
| Find File       | Ctrl+Shift+F   |
| Save            | Ctrl+S         |
| Save As         | Ctrl+Shift+S   |
| Close Tab       | Ctrl+W         |

### Code Execution
| Action          | Shortcut       |
|-----------------|----------------|
| Run Program     | F5             |
| Stop Program    | Shift+F5       |

### Fuzzy Finder
| Action          | Shortcut       |
|-----------------|----------------|
| Open Finder     | Ctrl+Shift+F   |
| Navigate Up     | Up Arrow       |
| Navigate Down   | Down Arrow     |
| Open File       | Enter          |
| Close Finder    | Escape         |

### Terminal
| Action          | Shortcut       |
|-----------------|----------------|
| Execute Command | Enter          |
| Previous Command| Up Arrow       |
| Next Command    | Down Arrow     |
| Clear Input     | Escape         |

## User Interface

```
+----------------------------------------------------------+
|  File   Run                                              |
+----------------------------------------------------------+
|  [▶ Run] [■ Stop] | [Find File] [Clear Output]           |
+----------------------------------------------------------+
|  [Tab 1] [Tab 2 *] [Tab 3]                               |
+----------------------------------------------------------+
|  1 | fn main(): int {                                    |
|  2 |     println(42);                                    |
|  3 |     return 0;                                       |
|  4 | }                                                   |
|                                                          |
+----------------------------------------------------------+
|  Output                    |  Terminal                   |
|  Running...                |  ~/projects $               |
|  42                        |  > dir                      |
|  [Finished: exit code 0]   |  example.ql  test.ql        |
+----------------------------------------------------------+
|  Ready                              ~/projects/QuinLang  |
+----------------------------------------------------------+
```

## Project Structure

```
QuinLang-IDE/
├── compiler/           # QuinLang compiler
│   ├── lexer.py        # Tokenization
│   ├── parser.py       # AST generation
│   ├── sema.py         # Semantic analysis
│   ├── codegen_vm.py   # Bytecode generation
│   └── bytecode.py     # Instruction definitions
├── runtime/
│   └── vm.py           # QuinVM interpreter
├── ide/
│   ├── app.py          # Main application window
│   ├── editor.py       # Code editor with line numbers
│   ├── tabs.py         # Tab bar and buffer management
│   ├── finder.py       # Fuzzy file finder
│   ├── terminal.py     # Integrated command line
│   ├── runner.py       # Compiler/VM execution
│   ├── highlighter.py  # Syntax highlighting
│   ├── theme.py        # Color scheme configuration
│   └── updater.py      # Auto-update functionality
├── examples/           # Sample .ql programs
├── run_ide.py          # Entry point
└── quinlang_ide.spec   # PyInstaller build config
```

## Customization

### Theme Colors

Edit `ide/theme.py` to customize the color scheme:

```python
COLORS = {
    'bg_dark': '#0a1628',        # Main background
    'bg_medium': '#122240',      # Panel backgrounds
    'bg_light': '#1a3358',       # Active elements
    'text_primary': '#f0e6a0',   # Main text (light yellow)
    'accent': '#5b9bd5',         # Highlights (light blue)
    # ... more colors
}
```

### Auto-Updater Configuration

To enable auto-updates for your fork, edit `ide/updater.py`:

```python
GITHUB_OWNER = "your-username"  # Your GitHub username
GITHUB_REPO = "QuinLang-IDE"    # Repository name
CURRENT_VERSION = "0.1.0"       # Increment with each release
```

## Building Executables

### Local Build

```bash
pip install pyinstaller
python build_exe.py
```

The executable will be created in the `dist/` folder.

### GitHub Actions

Push a version tag to trigger automatic builds:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions will build Windows and Linux executables and create a release.

## Example Program

```quin
fn main(): int {
    let i: int;
    i = 0;
    while (i < 5) {
        println(i);
        i = i + 1;
    }
    return 0;
}
```

## About QuinLang

QuinLang is a small, C-style language featuring:

- **Types**: `int`, `bool`, `str`, `ptr`, `void`, `int[N]` arrays
- **Control Flow**: `if`/`else`, `while`
- **Functions**: Parameters and return values
- **I/O**: Built-in `print`/`println`
- **Pointers**: `load16`, `store16`, `memcpy`, `memset`
- **Arrays**: `array_push`, `array_pop`

See the `examples/` folder for more sample programs.
