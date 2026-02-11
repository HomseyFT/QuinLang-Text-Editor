fn is_positive(x: int): int {
    if (x > 0) {
        return 1;
    }
    return 0;
}

fn main(): int {
    let a: int;
    let b: int;
    let ok: bool;

    a = 10;
    b = -5;

    // Short-circuit &&: second side should not run when first is false
    ok = (a > 0) && (b > 0);
    if (ok) {
        println(1);    // not printed
    }

    ok = (a > 0) && (b < 0);
    if (ok) {
        println(2);    // printed
    }

    // Short-circuit ||
    ok = (a > 0) || (b > 0);
    if (ok) {
        println(3);    // printed
    }

    // Call user function
    println(is_positive(a));   // 1
    println(is_positive(b));   // 0

    return 0;
}