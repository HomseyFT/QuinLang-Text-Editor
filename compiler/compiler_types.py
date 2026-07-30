from dataclasses import dataclass
from typing import Dict, Optional

@dataclass(frozen=True)
class Type:
    name: str
    size: int  # bytes

    def __str__(self) -> str:
        return self.name
Int = Type("int", 2)
Str = Type("str", 2)  # pointer to string data
Void = Type("void", 0)
Bool = Type("bool", 1)

# QuinLang has two disjoint address spaces, and they are separate types so that
# a pointer into one cannot be dereferenced as if it belonged to the other.
#
#   ptr     - an index into the current frame's locals, produced by '&'.
#             Read/written with load16/store16/memcpy/memset.
#   heapptr - a byte offset into the VM's heap, produced by alloc().
#             Read/written with heap_load/heap_store.
#
# They are both 16-bit values, so nothing but the type system distinguishes
# them; mixing them used to typecheck and silently read the wrong memory.
Ptr = Type("ptr", 2)
HeapPtr = Type("heapptr", 2)

BUILTIN_TYPES: Dict[str, Type] = {
    "int": Int,
    "str": Str,
    "void": Void,
    "bool": Bool,
    "ptr": Ptr,
    "heapptr": HeapPtr,
}

ARRAY_PREFIX = "int["


class UnknownTypeError(Exception):
    """Raised when a type name cannot be resolved to a concrete Type.

    Callers that know the source location should catch this and re-raise it
    as a SemanticError carrying line/col.
    """


def array_length_from_name(name: Optional[str]) -> Optional[int]:
    """Return N for a type name of the form 'int[N]', or None if it isn't an array name.

    Raises UnknownTypeError if the name looks like an array but the length is
    missing, non-numeric, or non-positive.
    """
    if not isinstance(name, str) or not name.startswith(ARRAY_PREFIX) or not name.endswith("]"):
        return None
    inner = name[len(ARRAY_PREFIX):-1]
    try:
        n = int(inner)
    except ValueError:
        raise UnknownTypeError(f"Invalid array length '{inner}' in type '{name}'")
    if n <= 0:
        raise UnknownTypeError(f"Array length must be positive, got {n} in type '{name}'")
    return n


def type_from_name(name: str) -> Type:
    if not isinstance(name, str):
        raise UnknownTypeError(f"Invalid type name {name!r}")
    n = array_length_from_name(name)
    if n is not None:
        return Type(name, 2 * n)
    if name in BUILTIN_TYPES:
        return BUILTIN_TYPES[name]
    raise UnknownTypeError(f"Unknown type '{name}'")


def is_array_type(t: Type) -> bool:
    return isinstance(t, Type) and t.name.startswith(ARRAY_PREFIX)


def array_length(t: Type) -> Optional[int]:
    """Return the element count of an array Type, or None for scalars."""
    return array_length_from_name(t.name) if isinstance(t, Type) else None
