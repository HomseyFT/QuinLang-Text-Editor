from typing import Dict, List, Tuple

# Signatures are written as type *names*; sema maps them to concrete Type
# objects, so this module needs to know nothing about the type system.

BuiltinSig = Tuple[List[str], str]


def get_builtins() -> Dict[str, BuiltinSig]:
    return {
        "load16":   (["ptr"], "int"),
        "store16":  (["ptr", "int"], "void"),
        "memcpy":   (["ptr", "ptr", "int"], "void"),
        "memset":   (["ptr", "int", "int"], "void"),
        # Shape checking for these two happens in sema/codegen.
        "array_push": (["int", "int", "int"], "int"),
        "array_pop":  (["int", "int"], "int"),
        "ct_eq":      (["int", "int"], "bool"),
        # ct_select(mask, x, y) returns x when mask != 0, else y; mask is
        # meant to be 0 or 1.
        "ct_select":  (["int", "int", "int"], "int"),
        # 'heapptr' is a different address space from the frame-relative 'ptr'
        # that '&' produces.
        "alloc":      (["int"], "heapptr"),
        "heap_load":  (["heapptr"], "int"),
        "heap_store": (["heapptr", "int"], "void"),
        # Collection also happens on allocation failure; this asks for one at
        # a known point.
        "gc":         ([], "void"),
        # The only way to report a problem: without it a library function
        # given bad arguments has no way to complain.
        "panic":      (["str"], "void"),
        # Concatenation is the '+' operator rather than a builtin.
        "str_len":     (["str"], "int"),
        "str_char_at": (["str", "int"], "int"),
        "str_slice":   (["str", "int", "int"], "str"),
        "int_to_str":  (["int"], "str"),
        "char_to_str": (["int"], "str"),
        # int and float never convert implicitly, so these are the only bridge
        # between them. float_to_int truncates toward zero, like integer '/'.
        "int_to_float":  (["int"], "float"),
        "float_to_int":  (["float"], "int"),
        "float_to_str":  (["float"], "str"),
    }
