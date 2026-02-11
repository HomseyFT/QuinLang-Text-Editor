// Minimal inline asm example (8086 backend only)

fn main(): int {
    println("Before asm$");

    // Emit a couple of raw 8086 instructions.
    asm "mov ax, 1234\ncall rt_print_num16\ncall rt_print_newline";

    println("After asm$");
    return 0;
}