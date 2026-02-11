// Demonstrate ct_eq and ct_select on QuinLang

fn choose(a: int, b: int, use_a: int): int {
    // Semantically: use_a != 0 ? a : b, but via ct_select.
    return ct_select(use_a, a, b);
}

fn main(): int {
    let x: int = 1234;
    let y: int = 1234;
    let z: int = 42;

    if (ct_eq(x, y)) {
        println("x == y$");
    }
    if (!ct_eq(x, z)) {
        println("x != z$");
    }

    let r1: int = choose(10, 20, 1);
    let r2: int = choose(10, 20, 0);

    println(r1);
    println(r2);

    return 0;
}