// Floats: 32-bit IEEE 754, the only type wider than a machine word.
//
// A float takes two consecutive slots wherever it is stored, but that is a
// storage detail; in the language it behaves like any other value. What is
// visible is that int and float never mix implicitly.

include "std/float.ql";

struct Circle {
    radius: float,
    label: str,
}

fn area(c: Circle): float {
    // No exponent notation and no float constants in the language, so pi is
    // written out.
    return 3.14159 * c.radius * c.radius;
}

fn average(total: float, count: int): float {
    if (count == 0) {
        panic("average of nothing");
    }
    // count is an int, so it has to be converted before it can divide a float.
    return total / int_to_float(count);
}

fn main(): int {
    println("-- arithmetic --");
    println(1.5 + 0.25);
    println(1.5 / 0.25);
    println(-1.5);

    println("-- single precision --");
    // Seven significant digits, not seventeen: this is a float, not a double.
    println(1.0 / 3.0);
    // Ten additions of 0.1 do not land on 1.0, which is why fclose exists.
    let acc: float = 0.0;
    let i: int = 0;
    while (i < 10) {
        acc = acc + 0.1;
        i = i + 1;
    }
    println(acc);
    println(acc == 1.0);
    println(fclose(acc, 1.0, 0.001));

    println("-- conversion --");
    // int and float never convert implicitly, so `2` and `2.0` are different
    // values and `x + 1` would not compile.
    println(int_to_float(7));
    println(float_to_int(3.75));      // truncates toward zero
    println(float_to_int(0.0 - 3.75));
    println("half of 7 is " + float_to_str(average(7.0, 2)));

    println("-- structs --");
    let c: Circle = Circle { radius: 2.0, label: "unit-ish" };
    println(c.label);
    println(area(c));
    c.radius = 3.0;
    println(area(c));

    println("-- std/float.ql --");
    println(fabs(0.0 - 2.5));
    println(fmin(1.5, 2.5));
    println(floor(0.0 - 2.7));        // -3.0, not the -2.0 truncation gives
    println(ceil(2.1));
    println(round(2.5));
    println(fpow(2.0, 10));

    return 0;
}
