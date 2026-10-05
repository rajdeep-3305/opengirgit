"""Collect every ``tr("…")`` source string into translations/en.json.

Usage (from the repository root)::

    python tools/collect_strings.py          # write/refresh en.json
    python tools/collect_strings.py --check  # fail when it is out of date (CI)

``en.json`` doubles as the translator inventory: copy it to ``<code>.json``,
translate the *values*, drop the file into ``client/opengirgit/translations/``.
English itself is implicit at runtime — an absent entry just passes through.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "client" / "opengirgit"
TARGET = SOURCE_DIR / "translations" / "en.json"

#: Files that define or use ``tr`` without user-visible literals of interest.
SKIP = {"i18n.py"}


def collect() -> dict[str, str]:
    strings: set[str] = set()
    for path in sorted(SOURCE_DIR.glob("*.py")):
        if path.name in SKIP:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "tr":
                continue
            for argument in node.args[:1]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    strings.add(argument.value)
    return {text: text for text in sorted(strings)}


def render(catalog: dict[str, str]) -> str:
    return json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    catalog = collect()
    content = render(catalog)
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != content:
            print(f"{TARGET} is out of date — run: python tools/collect_strings.py")
            return 1
        print(f"{TARGET}: {len(catalog)} strings, up to date")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")
    print(f"wrote {TARGET} ({len(catalog)} strings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
