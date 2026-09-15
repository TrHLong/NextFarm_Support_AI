from __future__ import annotations

import re
import unicodedata
from typing import Any


def norm(value: str | None) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def resolve_crop_key(name: str | None, catalog: list[dict[str, Any]]) -> tuple[str, float, str]:
    target = norm(name)
    if not target:
        return "other", 0.0, "missing"
    exact: list[tuple[str, str]] = []
    partial: list[tuple[str, str]] = []
    for row in catalog:
        values = [row["display_name_vi"], row["crop_key"], *(row.get("aliases") or [])]
        for value in values:
            n = norm(str(value))
            if target == n:
                exact.append((row["crop_key"], str(value)))
            elif n and (n in target or target in n):
                partial.append((row["crop_key"], str(value)))
    if exact:
        return exact[0][0], 1.0, f"exact:{exact[0][1]}"
    if partial:
        return partial[0][0], 0.86, f"partial:{partial[0][1]}"
    return "other", 0.25, "fallback"
