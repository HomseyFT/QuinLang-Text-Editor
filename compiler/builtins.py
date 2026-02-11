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
    }
