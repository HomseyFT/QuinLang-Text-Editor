from typing import Dict, List, Tuple

# Builtin function signatures expressed in terms of type *names*.
# sema.py is responsible for mapping these names to concrete Type objects.
# Signature format: name -> (param_type_names, return_type_name)

BuiltinSig = Tuple[List[str], str]


def get_builtins() -> Dict[str, BuiltinSig]:
    return {
        # Low-level memory ops (16-bit word oriented where applicable)
        "load16":   (["ptr"], "int"),
        "store16":  (["ptr", "int"], "void"),
        "memcpy":   (["ptr", "ptr", "int"], "void"),
        "memset":   (["ptr", "int", "int"], "void"),
        # Array helpers; detailed shape checking is done in sema/codegen.
        "array_push": (["int", "int", "int"], "int"),
        "array_pop":  (["int", "int"], "int"),
        # Constant-time style primitives.
        # ct_eq(a, b): returns bool indicating equality.
        "ct_eq":      (["int", "int"], "bool"),
        # ct_select(mask, x, y): returns x when mask != 0, else y.
        # Intended usage is mask in {0,1}.
        "ct_select":  (["int", "int", "int"], "int"),
        # Heap allocation and access. These use 'heapptr', a different address
        # space from the frame-relative 'ptr' that '&' produces.
        "alloc":      (["int"], "heapptr"),
        "heap_load":  (["heapptr"], "int"),
        "heap_store": (["heapptr", "int"], "void"),
        # Force a collection. Collection also happens on its own when an
        # allocation cannot be satisfied; this exists so a program (or a test)
        # can ask for one at a known point.
        "gc":         ([], "void"),
        # Abort with a message. Nothing else in the language can report a
        # problem, so a library function given bad arguments has no way to
        # complain without this.
        "panic":      (["str"], "void"),
    }
