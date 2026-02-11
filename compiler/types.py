from dataclasses import dataclass
from typing import Dict

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
Ptr = Type("ptr", 2)

BUILTIN_TYPES: Dict[str, Type] = {
    "int": Int,
    "str": Str,
    "void": Void,
    "bool": Bool,
    "ptr": Ptr,
}


def type_from_name(name: str) -> Type:
    # Array types of the form int[N]
    if name is not None and isinstance(name, str) and name.startswith("int[") and name.endswith("]"):
        inner = name[4:-1]
        try:
            n = int(inner)
        except ValueError:
            return Int
        if n <= 0:
            return Int
        return Type(name, 2 * n)
    if name in BUILTIN_TYPES:
        return BUILTIN_TYPES[name]
    # Unknown types default to int for now (placeholder)
    return Int


def is_array_type(t: Type) -> bool:
    return isinstance(t, Type) and t.name.startswith("int[")
