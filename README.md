# QuinLang IDE

A lightweight, self-contained IDE for the QuinLang programming language. This application bundles the full QuinLang compiler and QuinVM interpreter, providing an integrated environment for writing, running, and debugging QL programs.

## Features

- **Code Editor** — Syntax-aware text editor with line numbers
- **Integrated Compiler** — Full QuinLang compiler built-in (lexer, parser, semantic analysis, bytecode generation)
- **QuinVM Runtime** — Programs execute directly in the embedded virtual machine
- **Run/Stop Controls** — Execute programs with F5, stop running programs with Shift+F5
- **Output Panel** — View program output and error messages with colored diagnostics
- **File Management** — New, Open, Save, Save As with unsaved changes detection

## Requirements

- Python 3.10+
- Tkinter (included with standard Python on Windows/macOS)

## Quick Start

```bash
python run_ide.py
```

The IDE opens with a simple example program. Click **Run** or press **F5** to execute it.

## Keyboard Shortcuts

| Action       | Shortcut       |
|--------------|----------------|
| Run          | F5             |
| Stop         | Shift+F5       |
| New File     | Ctrl+N         |
| Open File    | Ctrl+O         |
| Save         | Ctrl+S         |
| Save As      | Ctrl+Shift+S   |

## Project Structure

```
QuinLang-IDE/
├── compiler/       # QuinLang compiler (lexer, parser, sema, codegen)
├── runtime/        # QuinVM bytecode interpreter
├── examples/       # Sample .ql programs
├── ide/
│   ├── app.py      # Main application window
│   ├── editor.py   # Code editor widget
│   └── runner.py   # Compiler/VM execution wrapper
└── run_ide.py      # Entry point
```

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

- Types: `int`, `bool`, `str`, `ptr`, `void`, `int[N]` arrays
- Control flow: `if`/`else`, `while`
- Functions with parameters and return values
- Built-in `print`/`println`
- Pointer intrinsics: `load16`, `store16`, `memcpy`, `memset`
- Array helpers: `array_push`, `array_pop`

See the `examples/` folder for more sample programs.
