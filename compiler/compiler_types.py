from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass(frozen=True)
class Type:
    name: str
    size: int  # bytes

    def __str__(self) -> str:
        return self.name
Int = Type("int", 2)
Str = Type("str", 2)  # heap address of a string object
Void = Type("void", 0)
Bool = Type("bool", 1)

# Two disjoint address spaces, kept as separate types so a pointer into one
# cannot be dereferenced as if it belonged to the other:
#
#   ptr     - index into the current frame's locals, from '&'.
#             Read/written with load16/store16/memcpy/memset.
#   heapptr - byte offset into the VM's heap, from alloc().
#             Read/written with heap_load/heap_store.
#
# Both are 16-bit values, so nothing but the type system tells them apart;
# mixing them used to typecheck and silently read the wrong memory.
Ptr = Type("ptr", 2)
HeapPtr = Type("heapptr", 2)

# The type of the 'null' literal, which nobody can write down. It exists so
# null can initialize or be compared against any reference type without those
# types collapsing into one.
Null = Type("null", 2)

BUILTIN_TYPES: Dict[str, Type] = {
    "int": Int,
    "str": Str,
    "void": Void,
    "bool": Bool,
    "ptr": Ptr,
    "heapptr": HeapPtr,
}

ARRAY_PREFIX = "int["


@dataclass(frozen=True)
class StructType(Type):
    """A reference to a heap-allocated struct: one word, like any other
    reference. The field layout lives in StructInfo instead, because Type is
    compared by value and two structs are the same type exactly when they
    share a name.

    Subclassing matters: a dataclass __eq__ requires both sides to be the same
    class, so StructType('Point', 2) never compares equal to Type('Point', 2).
    """


@dataclass(frozen=True)
class StructField:
    name: str
    type: Type
    offset: int  # in 16-bit words from the object's base address


@dataclass
class StructInfo:
    """A struct's declared layout, and the id its heap header carries."""
    name: str
    type_id: int
    fields: List[StructField] = field(default_factory=list)

    @property
    def word_size(self) -> int:
        return len(self.fields)

    def field_named(self, name: str) -> Optional[StructField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def type(self) -> StructType:
        # Always one word: the size of a *reference*, not of the object, which
        # lives in word_size. That matters for recursion — resolving
        # `next: Node` builds Node's type while its field list is still empty,
        # so a size derived from the fields would not equal the completed one.
        return StructType(self.name, 2)


def is_struct_type(t: Type) -> bool:
    return isinstance(t, StructType)


def is_reference_type(t: Type) -> bool:
    """Whether values of this type are heap addresses the GC must trace. A str
    counts: a str slot roots its string, and a str field must be traced."""
    return is_struct_type(t) or t == HeapPtr or t == Str


def is_nullable(t: Type) -> bool:
    """Whether null may stand in for a value of this type. Not the same
    question as is_reference_type: a string is a heap reference, but an
    uninitialised str is the empty string, so there is no null string."""
    return is_struct_type(t) or t == HeapPtr


def assignable(target: Type, value: Type) -> bool:
    """There are no implicit conversions; null initializing a reference is the
    single exception."""
    if target == value:
        return True
    return value == Null and is_nullable(target)


def comparable(left: Type, right: Type) -> bool:
    if left == right:
        return True
    return ((left == Null and is_nullable(right))
            or (right == Null and is_nullable(left)))


class UnknownTypeError(Exception):
    """Callers that know the source location should catch this and re-raise it
    as a SemanticError carrying line/col."""


def array_length_from_name(name: Optional[str]) -> Optional[int]:
    """N for a type name of the form 'int[N]', None if it isn't one. Raises
    UnknownTypeError if it looks like an array but N is missing, non-numeric,
    or non-positive."""
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


def type_from_name(name: str, structs: Optional[Dict[str, "StructInfo"]] = None) -> Type:
    if not isinstance(name, str):
        raise UnknownTypeError(f"Invalid type name {name!r}")
    n = array_length_from_name(name)
    if n is not None:
        return Type(name, 2 * n)
    if name in BUILTIN_TYPES:
        return BUILTIN_TYPES[name]
    if structs and name in structs:
        return structs[name].type()
    raise UnknownTypeError(f"Unknown type '{name}'")


def is_array_type(t: Type) -> bool:
    return isinstance(t, Type) and t.name.startswith(ARRAY_PREFIX)


def array_length(t: Type) -> Optional[int]:
    return array_length_from_name(t.name) if isinstance(t, Type) else None
