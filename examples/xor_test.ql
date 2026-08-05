fn main(): int {
    let a: int;

    // Basic XOR
    a = 5 ^ 3;
    println(a);        // expect 6

    a = 0 ^ 0;
    println(a);        // expect 0

    a = 12 ^ 10;
    println(a);        // expect 6

    // Precedence: '+' binds tighter than '^'  ->  1 ^ (2 + 3) = 1 ^ 5 = 4
    a = 1 ^ 2 + 3;
    println(a);        // expect 4

    // Precedence: '*' binds tighter than '^'  ->  (2 * 3) ^ 1 = 6 ^ 1 = 7
    a = 2 * 3 ^ 1;
    println(a);        // expect 7

    // Left associativity: (7 ^ 3) ^ 1 = 4 ^ 1 = 5
    a = 7 ^ 3 ^ 1;
    println(a);        // expect 5

    // Parentheses override
    a = (1 ^ 2) + 3;
    println(a);        // expect 6

    // Signedness: -1 is all ones, XOR 0 leaves it unchanged
    a = -1 ^ 0;
    println(a);        // expect -1

    return 0;
}
