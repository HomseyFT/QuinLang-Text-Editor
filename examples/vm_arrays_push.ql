fn main(): int {
    let a: int[3];
    let len: int;

    len = 0;
    len = array_push(a, len, 10);
    len = array_push(a, len, 20);
    len = array_push(a, len, 30);

    println(a[0]);  // 10
    println(a[1]);  // 20
    println(a[2]);  // 30

    return 0;
}