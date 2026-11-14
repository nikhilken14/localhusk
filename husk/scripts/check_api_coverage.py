"""Static check (no imports of app code): every endpoint in the frontend spec exists in the routers.

Usage: python scripts/check_api_coverage.py FrontEnd-API-Required.txt
"""
import ast
import re
import sys
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[1] / "src" / "assistant" / "api" / "v1"
METHODS = {"get", "post", "put", "patch", "delete"}


def norm(path: str) -> str:
    path = path.split("?")[0].rstrip("/") or "/"
    return re.sub(r"\{[^}]*\}", "{}", path)


def implemented() -> set[tuple[str, str]]:
    found = set()
    for file in ROUTERS.glob("*.py"):
        tree = ast.parse(file.read_text())
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
                for kw in node.keywords:
                    if kw.arg == "prefix":
                        prefix = ast.literal_eval(kw.value)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in METHODS
                            and dec.args and isinstance(dec.args[0], ast.Constant)):
                        found.add((dec.func.attr.upper(), norm(prefix + dec.args[0].value)))
    return found


def required(spec: Path) -> list[tuple[str, str]]:
    rows = []
    for line in spec.read_text().splitlines():
        m = re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)", line.strip())
        if m:
            rows.append((m.group(1), norm(m.group(2))))
    return rows


if __name__ == "__main__":
    have, need = implemented(), required(Path(sys.argv[1]))
    missing = [r for r in need if r not in have]
    print(f"{len(need) - len(missing)}/{len(need)} required endpoints implemented")
    for method, path in missing:
        print("MISSING", method, path)
    extra = sorted(have - set(need))
    print(f"{len(extra)} additional endpoints:", *[f"{m} {p}" for m, p in extra], sep="\n  ")
    sys.exit(1 if missing else 0)
