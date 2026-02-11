fn main(): int {
    let arr: int[3];
    let len: int;
    let v: int;
    len = 0;

    len = array_push(arr, len, 10);
    len = array_push(arr, len, 20);
    len = array_push(arr, len, 30);

    v = array_pop(arr, len);
    len = len - 1;
    print(v);

    v = array_pop(arr, len);
    len = len - 1;
    print(v);

    v = array_pop(arr, len);
    len = len - 1;
    print(v);

    // Pointer + memory intrinsic tests using stack-allocated ints
    let a: int;
    let b: int;
    let pa: ptr;
    let pb: ptr;
    a = 1234;
    b = 0;

    pa = &a;
    pb = &b;

    // store16 & load16
    store16(pa, 4321);
    print(a);          // expect 4321

    store16(pb, 1111);
    print(b);          // expect 1111

    // memcpy/memset tests with int[3] buffers
    let buf1: int[3];
    let buf2: int[3];

    buf1[0] = 7;
    buf1[1] = 8;
    buf1[2] = 9;

    // memcpy(buf2, buf1, 6)  ; 3 ints * 2 bytes each
    memcpy(&buf2[0], &buf1[0], 6);

    print(buf2[0]);    // 7
    print(buf2[1]);    // 8
    print(buf2[2]);    // 9

    // memset(buf2, 0, 6)
    memset(&buf2[0], 0, 6);

    print(buf2[0]);    // 0
    print(buf2[1]);    // 0
    print(buf2[2]);    // 0
    println(" ");
    println("Hello");
    print("My Name Is Nathan");

    let za: bool;
    let zb: bool;
    let zc: bool;

    za = true;
    zb = false;

    zc = zb && zb;         // false
    zc = za || zb;         // true

    if (za && !zb) {
        println(1);
    }
    if (za || zb && false) {
        println(2);
    }

    return 0;
}
