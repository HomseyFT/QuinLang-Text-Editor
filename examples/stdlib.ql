// A tour of the standard library.
//
// The prelude brings in the modules that define only functions. The two
// collection modules declare struct types, so they are included by name.

include "std/prelude.ql";
include "std/list.ql";
include "std/vec.ql";

fn main(): int {
    println("-- math --");
    println(gcd(48, 18));            // 6
    println(lcm(4, 6));              // 12
    println(isqrt(50));              // 7  (7*7 = 49, 8*8 = 64)
    println(pow(2, 10));             // 1024
    println(pow(2, 16));             // 0 — wraps, like any 16-bit multiply
    println(clamp(99, 0, 10));       // 10
    println(sign(0 - 7));            // -1

    println("-- bits --");
    println(popcount(255));          // 8
    println(highest_bit(1000));      // 9
    println(trailing_zeros(8));      // 3
    print("0xBEEF = ");
    println_binary(48879);
    print("reversed  = ");
    println_hex(reverse_bits(48879));
    // >> is arithmetic, so shifting a negative number keeps its sign.
    // logical_shift_right is the version that does not.
    println(0 - 1 >> 8);             // -1
    println(logical_shift_right(0 - 1, 8));   // 255

    println("-- io --");
    print_line(12);
    print("|");
    print_padded(7, 5);
    print(" |");
    print_padded(1234, 5);
    println(" |");
    print_line(12);

    println("-- list --");
    // A list is persistent at the front: reversing builds a new one and
    // leaves the original intact.
    let l: IntList = list_empty();
    for (let i = 5; i > 0; i = i - 1) {
        l = list_push(l, i);
    }
    list_println(l);                 // [1, 2, 3, 4, 5]
    println(list_sum(l));            // 15
    println(list_max(l));            // 5
    list_println(list_reverse(l));   // [5, 4, 3, 2, 1]
    list_println(l);                 // [1, 2, 3, 4, 5] — unchanged

    println("-- vec --");
    // A vector is a reference, so push is visible to whoever else holds it,
    // and the block it points at is traced and moved by the collector.
    let v: IntVec = vec_new(2);
    for (let i = 1; i < 8; i = i + 1) {
        vec_push(v, i * i);
    }
    vec_println(v);                  // [1, 4, 9, 16, 25, 36, 49]
    println(vec_len(v));             // 7
    println(vec_capacity(v));        // 8 — grew from 2
    println(vec_sum(v));             // 140
    println(vec_pop(v));             // 49
    vec_reverse(v);
    vec_println(v);                  // [36, 25, 16, 9, 4, 1]

    gc();
    vec_println(v);                  // survives being moved
    list_println(l);

    return 0;
}
