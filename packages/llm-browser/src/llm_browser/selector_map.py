"""Selector map: load a YAML file mapping symbolic names to selectors."""

from pathlib import Path
from typing import Any

import yaml


def load_selector_map(path: Path) -> dict[str, dict[str, Any]]:
    """Load a selector_map.yaml into a flat lookup: 'group.name' -> selector dict."""
    raw = yaml.safe_load(path.read_text())
    flat: dict[str, dict[str, Any]] = {}
    for group_name, fields in raw.items():
        for field_name, selector_spec in fields.items():
            flat[f"{group_name}.{field_name}"] = selector_spec
    return flat


def resolve_refs(
    step_dict: dict[str, Any],
    selector_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Replace 'ref' keys with actual selectors from the map.

    Handles:
      - step-level: {"ref": "invoice.rfc"} -> {"selector": {"id": "135..."}}
      - field-level: fields[i]["ref"] -> resolved selector as "id" key
    """
    result = dict(step_dict)

    if "ref" in result:
        ref = str(result.pop("ref"))
        if ref in selector_map:
            result["selector"] = selector_map[ref]

    if "fields" in result:
        resolved_fields = []
        for field in result["fields"]:
            if "ref" in field:
                ref = str(field.pop("ref"))
                if ref in selector_map:
                    spec = selector_map[ref]
                    if "id" in spec:
                        field["id"] = spec["id"]
                    else:
                        field["selector"] = spec
            resolved_fields.append(field)
        result["fields"] = resolved_fields

    if "read" in result:
        resolved_read: dict[str, Any] = {}
        for key, spec in result["read"].items():
            if "ref" in spec:
                ref = str(spec.pop("ref"))
                if ref in selector_map:
                    spec["selector"] = selector_map[ref]
            resolved_read[key] = spec
        result["read"] = resolved_read

    return result
