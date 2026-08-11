// for loops, break, continue, and bare blocks

fn main(): int {
    // Counting up. The loop variable is scoped to the loop.
    for (let i: int = 0; i < 3; i = i + 1) {
        println(i);            // 0 1 2
    }

    // The init type can be inferred, and the loop can count down.
    for (let i = 3; i > 0; i = i - 1) {
        println(i);            // 3 2 1
    }

    // break leaves the loop; continue skips to the step, so i still advances.
    for (let i = 0; i < 6; i = i + 1) {
        if (i == 4) {
            break;
        }
        if (i == 1) {
            continue;
        }
        println(i);            // 0 2 3
    }

    // break and continue bind to the innermost loop.
    for (let i = 0; i < 2; i = i + 1) {
        for (let j = 0; j < 5; j = j + 1) {
            if (j == 1) {
                break;
            }
            println(i * 10 + j);   // 0 10
        }
    }

    // Every clause is optional; with no condition, break is the only exit.
    let n: int = 0;
    for (;;) {
        n = n + 1;
        if (n == 3) {
            break;
        }
    }
    println(n);                // 3

    // A bare block is just a scope.
    let x: int = 1;
    {
        let x: int = 2;
        println(x);            // 2
    }
    println(x);                // 1

    return 0;
}
