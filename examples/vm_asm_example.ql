// Demonstrate vm_asm inline VM-level IR

fn main(): int {
    let x: int = 5;

    vm_asm {
        load_local x;
        push_int 1;
        add;
        store_local x;
    }

    println(x); // should print 6
    return 0;
}