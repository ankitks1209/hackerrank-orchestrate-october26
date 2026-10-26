"""A small JSON-Schema checker for tool arguments and model replies (SPEC 12.2).

Supports exactly what the agent's schemas use: `type` (one name or a list, so a field can be
nullable), `enum`, `properties`, `required`, `additionalProperties: false` and `items`. Size
limits are not expressed in the schemas (strict tool schemas do not take them); the tools
enforce them. `is_strict` checks that every object in a schema lists all its properties as
required and forbids extras, which the tool registry asserts for every tool definition.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Sequence

Schema = Mapping[str, Any]

_TYPES = {
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "null": lambda value: value is None,
    "array": lambda value: isinstance(value, (list, tuple)),
    "object": lambda value: isinstance(value, Mapping),
}


def validate(value: Any, schema: Schema, path: str = "$") -> List[str]:
    """Every way `value` violates `schema`, as readable strings; an empty list means valid."""
    errors: List[str] = []
    names = schema.get("type")
    names = [names] if isinstance(names, str) else list(names or [])
    if names and not any(_TYPES[name](value) for name in names):
        return ["%s: expected %s, got %s" % (path, "|".join(names), type(value).__name__)]
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s: %r is not one of %s" % (path, value, list(schema["enum"])))
    if isinstance(value, Mapping):
        errors.extend(_check_object(value, schema, path))
    elif isinstance(value, (list, tuple)):
        errors.extend(_check_array(value, schema, path))
    return errors


def _check_object(value: Mapping[str, Any], schema: Schema, path: str) -> List[str]:
    errors: List[str] = []
    properties: Mapping[str, Schema] = schema.get("properties", {})
    for name in schema.get("required", ()):
        if name not in value:
            errors.append("%s: missing required property %r" % (path, name))
    if schema.get("additionalProperties") is False:
        for name in sorted(set(value) - set(properties)):
            errors.append("%s: unexpected property %r" % (path, name))
    for name in sorted(set(value) & set(properties)):
        errors.extend(validate(value[name], properties[name], "%s.%s" % (path, name)))
    return errors


def _check_array(value: Sequence[Any], schema: Schema, path: str) -> List[str]:
    errors: List[str] = []
    item_schema = schema.get("items")
    if item_schema is not None:
        for position, item in enumerate(value):
            errors.extend(validate(item, item_schema, "%s[%d]" % (path, position)))
    return errors


def is_strict(schema: Schema) -> bool:
    """True when every object in `schema` requires all its properties and forbids extras."""
    if "object" in ([schema["type"]] if isinstance(schema.get("type"), str) else schema.get("type", [])):
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            return False
        if sorted(schema.get("required", ())) != sorted(properties):
            return False
        if not all(is_strict(child) for child in properties.values()):
            return False
    items = schema.get("items")
    return items is None or is_strict(items)
