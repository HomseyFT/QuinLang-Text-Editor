// Structs: heap objects with reference semantics.

struct Point {
    x: int,
    y: int,
}

// A struct may name itself, which is what makes linked structures possible.
struct Node {
    value: int,
    next: Node,
}

fn area(p: Point): int {
    return p.x * p.y;
}

// Structs are references, so a function can modify the caller's object.
fn scale(p: Point, k: int): void {
    p.x = p.x * k;
    p.y = p.y * k;
}

fn sum(head: Node): int {
    let total: int = 0;
    let cur: Node = head;
    while (cur != null) {
        total = total + cur.value;
        cur = cur.next;
    }
    return total;
}

fn length(head: Node): int {
    let n: int = 0;
    let cur: Node = head;
    while (cur != null) {
        n = n + 1;
        cur = cur.next;
    }
    return n;
}

fn main(): int {
    let p: Point = Point { x: 3, y: 4 };
    println(p.x);              // 3
    println(area(p));          // 12

    p.y = 10;
    println(area(p));          // 30

    // q and p name the same object, so writing through one is visible in the other.
    let q: Point = p;
    q.x = 1;
    println(p.x);              // 1

    scale(p, 5);
    println(p.x);              // 5
    println(p.y);              // 50

    // Two literals with equal fields are still two distinct objects.
    let a: Point = Point { x: 1, y: 1 };
    let b: Point = Point { x: 1, y: 1 };
    println(a == b);           // false
    println(a == a);           // true

    // Build a list 5 -> 4 -> 3 -> 2 -> 1 -> null
    let head: Node = null;
    for (let i = 1; i < 6; i = i + 1) {
        head = Node { value: i, next: head };
    }
    println(length(head));     // 5
    println(sum(head));        // 15
    println(head.value);       // 5
    println(head.next.value);  // 4

    // An uninitialized reference is null.
    let missing: Node;
    println(missing == null);  // true

    return 0;
}
