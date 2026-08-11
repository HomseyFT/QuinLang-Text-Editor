// The garbage collector at work.
//
// A Node costs 8 bytes on the heap: two words of header plus two of fields.
// The heap is 64 KiB, so it holds a little over 8000 of them at once.

struct Node {
    value: int,
    next: Node,
}

// Deliberately much larger than a Node, to make the holes it leaves behind
// too small to be useful without compaction.
struct Wide {
    a: int, b: int, c: int, d: int, e: int, f: int, g: int, h: int,
    i: int, j: int, k: int, l: int, m: int, n: int, o: int, p: int,
}

// Each call allocates a node and then drops it: once make_garbage returns,
// its frame is gone and nothing refers to that node any more.
fn make_garbage(): void {
    let junk: Node = Node { value: 1, next: null };
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
    // A list that stays reachable for the whole program.
    let keep: Node = null;
    for (let i = 0; i < 10; i = i + 1) {
        keep = Node { value: i, next: keep };
    }
    println(length(keep));        // 10

    // Allocate 40000 nodes, far more than the heap can hold at once. Nothing
    // retains them, so collection reclaims each batch and the program runs to
    // completion instead of running out of memory.
    for (let i = 0; i < 40000; i = i + 1) {
        make_garbage();
    }

    // The reachable list is untouched by all of that.
    println(length(keep));        // 10
    println(keep.value);          // 9
    println(keep.next.value);     // 8

    // Collection can also be asked for directly.
    gc();
    println(length(keep));        // 10

    // A cycle is still garbage when nothing outside it refers to it. A
    // reference count would never reach zero here; tracing from the roots
    // never reaches these nodes at all.
    for (let i = 0; i < 5000; i = i + 1) {
        let a: Node = Node { value: 1, next: null };
        let b: Node = Node { value: 2, next: a };
        a.next = b;
    }
    gc();
    println(length(keep));        // 10

    // Fragmentation, and why the collector moves things.
    //
    // Each iteration allocates a large block that immediately dies, then a
    // small node that survives on the list. The survivors end up scattered
    // through the heap with dead space between them, so the free memory is
    // thousands of separate holes and none of them is large.
    //
    // A collector that only freed objects in place could not satisfy the Wide
    // allocation below: there would be plenty of free bytes and no single gap
    // big enough. Sliding the survivors together turns all those holes into
    // one run, and the allocation succeeds.
    let scattered: Node = null;
    for (let i = 0; i < 1200; i = i + 1) {
        let dead: Wide = Wide { a:0, b:0, c:0, d:0, e:0, f:0, g:0, h:0,
                                i:0, j:0, k:0, l:0, m:0, n:0, o:0, p:0 };
        scattered = Node { value: i, next: scattered };
    }
    let wide: Wide = Wide { a:1, b:0, c:0, d:0, e:0, f:0, g:0, h:0,
                            i:0, j:0, k:0, l:0, m:0, n:0, o:0, p:0 };
    println(wide.a);              // 1
    println(length(scattered));   // 1200
    println(length(keep));        // 10 — untouched by all of it

    return 0;
}
