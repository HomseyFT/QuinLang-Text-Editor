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
- **Interrupt** — Press `Ctrl+C` to stop a running command and its children

### Compiler & Runtime
- **Full QuinLang Compiler** — Lexer, parser, semantic analysis, bytecode generation
- **QuinVM Interpreter** — Programs execute directly in the embedded virtual machine
- **Run/Stop Controls** — Execute and terminate programs with toolbar buttons or hotkeys
- **Output Panel** — View program output with colored error messages and diagnostics

### Auto-Updater
- **Automatic Update Checks** — Notified when new versions are available
- **One-Click Updates** — Download and install updates directly from the IDE
- **Seamless Restart** — Application restarts automatically after updating
- **Verified Downloads** — An update is only applied if it is a real executable

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
QuinLang-Text-Editor/
├── compiler/           # Synced from QuinLang - do not edit by hand
│   ├── lexer.py        # Tokenization
│   ├── parser.py       # AST generation
│   ├── sema.py         # Semantic analysis
│   ├── codegen_vm.py   # Bytecode generation
│   └── bytecode.py     # Instruction definitions
├── runtime/            # Synced from QuinLang - do not edit by hand
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
├── examples/           # Sample .ql programs (synced from QuinLang)
├── run_ide.py          # Entry point
└── quinlang_ide.spec   # PyInstaller build config
```

### Never patch `compiler/`, `runtime/` or `examples/`

`sync-compiler.yml` **deletes and replaces those three directories** on every
sync. Any change made there is silently lost the next time QuinLang is updated.

This has broken the IDE twice. Both times, IDE-specific hooks
(`output_callback`, `request_stop`, `ExecutionStopped`) were added to
`runtime/vm.py`; the next sync removed them, and `ide/runner.py` then failed to
import — leaving the IDE unable to start at all.

`ide/runner.py` therefore drives a **stock, unmodified** `QuinVM`:

- **Output** — `QuinVM` prints to stdout, so the runner redirects `sys.stdout`
  for the duration of the run and forwards writes to the output panel.
- **Stopping** — a thread trace hook raises `ExecutionStopped` (defined in
  `ide/runner.py`) at the VM's next function call.

If the IDE needs something new from the VM, adapt `ide/runner.py` to work with
what upstream provides. `tests/test_vm_integration.py` enforces this and will
fail if the dependency creeps back into `runtime/`.

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

To point auto-updates at your own fork, edit `ide/updater.py`:

```python
GITHUB_OWNER = "HomseyFT"                # GitHub username
GITHUB_REPO = "QuinLang-Text-Editor"     # Repository name
CURRENT_VERSION = "2.0.0"                # Bumped automatically on compiler sync
```

The updater downloads the release asset whose name identifies your platform
(`QuinLangIDE-windows-x64.exe` or `QuinLangIDE-linux-x64`), so the release
workflow must publish those exact names — a release with differently named
assets is invisible to the updater.

## Building Executables

### Local Build

```bash
pip install pyinstaller
python build_exe.py
```

The executable will be created in the `dist/` folder.

### GitHub Actions

Two workflows cooperate:

**`sync-compiler.yml`** — runs when QuinLang signals a compiler change. It copies
`compiler/`, `runtime/` and `examples/` from the QuinLang repo, bumps the patch
version in `ide/updater.py`, and pushes a `vX.Y.Z` tag. It deliberately does
**not** create a release, so frequent language commits don't flood the releases
page.

**`release.yml`** — builds and attaches both binaries. It runs when you:

- **publish a release from the GitHub UI** (pick an existing tag → Publish), or
- push a tag yourself from a local clone, or
- run *Build and Release* manually and give it a tag.

> Tags pushed *by a workflow* using the default `GITHUB_TOKEN` do not trigger
> `on: push`. That is why the auto-bumped tags never produced builds, and why
> publishing the release is what starts the build.

The release job refuses to finish unless both `QuinLangIDE-windows-x64.exe` and
`QuinLangIDE-linux-x64` are present, and re-queries the GitHub API afterwards to
confirm they actually attached — so a release can no longer end up with no
downloads.

### Cutting a release

1. **Releases → Draft a new release**
2. Choose the tag the sync workflow already created (e.g. `v2.0.1`)
3. **Publish release** — the build starts automatically and attaches both binaries

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

- **Types**: `int`, `str`, `ptr`, `void`, `heapptr`, `int[N]` arrays
- **Control Flow**: `if`/`else`, `while`
- **Functions**: Parameters and return values
- **I/O**: Built-in `print`/`println`
- **Pointers**: `load16`, `store16`, `memcpy`, `memset`
- **Heap**: `alloc`, `heap_load`, `heap_store`
- **Arrays**: `array_push`, `array_pop`
- **Constant-time**: `ct_eq`, `ct_select`
- **Inline assembly**: `vm_asm`

> The editor's highlighting lists live in `ide/highlighter.py` and mirror
> `compiler/tokens.py` and `compiler/builtins.py`. Update them together when the
> language changes.

See the `examples/` folder for more sample programs.
