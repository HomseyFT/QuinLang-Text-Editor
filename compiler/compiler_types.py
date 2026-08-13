from dataclasses import dataclass, field
from typing import Dict, List, Optional

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

# The type of the 'null' literal. It is not a type anyone can write down: it
# exists so that null can initialize or be compared against any reference type
# without those types collapsing into one.
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
    """A reference to a heap-allocated struct.

    A struct value is one word — the heap address of the object — so this is
    the same size as any other reference. The field layout lives in StructInfo
    rather than here, because Type is compared by value and two structs are the
    same type exactly when they have the same name.

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
        # The size here is the size of a *reference*, always one word — not the
        # size of the object, which lives in word_size. That matters for
        # recursion: resolving `next: Node` builds Node's type while Node's own
        # field list is still empty, so a size derived from the fields would
        # make that type unequal to the completed one.
        return StructType(self.name, 2)


def is_struct_type(t: Type) -> bool:
    return isinstance(t, StructType)


def is_reference_type(t: Type) -> bool:
    """Whether values of this type are heap addresses the GC must trace.

    A str is one of these: a string is a heap object, so a str slot roots it
    and a str field inside a struct has to be traced.
    """
    return is_struct_type(t) or t == HeapPtr or t == Str


def is_nullable(t: Type) -> bool:
    """Whether null may stand in for a value of this type.

    Not the same question as is_reference_type. A string is a heap reference,
    but there is no null string: an uninitialised str is the empty string, so
    every str denotes real characters and no operation needs a null check.
    """
    return is_struct_type(t) or t == HeapPtr


def assignable(target: Type, value: Type) -> bool:
    """Whether a value of type `value` may be stored into a `target` slot.

    There are no implicit conversions; the single exception is null, which
    initializes any reference.
    """
    if target == value:
        return True
    return value == Null and is_nullable(target)


def comparable(left: Type, right: Type) -> bool:
    """Whether == and != accept this pair of operand types."""
    if left == right:
        return True
    return ((left == Null and is_nullable(right))
            or (right == Null and is_nullable(left)))


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
    """Return the element count of an array Type, or None for scalars."""
    return array_length_from_name(t.name) if isinstance(t, Type) else None
