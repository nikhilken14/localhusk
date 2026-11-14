"""Dependency-free sanity checks: undefined names, unresolved intra-project imports, unused imports."""
import ast, builtins, sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def module_path(mod):
    base = SRC / mod.replace(".", "/")
    return base.with_suffix(".py") if base.with_suffix(".py").exists() else (base / "__init__.py" if (base / "__init__.py").exists() else None)


def top_level_names(tree):
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(n):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    names.add(t.id)
        elif isinstance(n, (ast.For, ast.If, ast.Try, ast.With)):
            for t in ast.walk(n):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    names.add(t.id)
                if isinstance(t, (ast.FunctionDef, ast.ClassDef)):
                    names.add(t.name)
                if isinstance(t, (ast.Import, ast.ImportFrom)):
                    names.update((a.asname or a.name).split(".")[0] for a in t.names)
    return names


problems = 0
files = sorted(SRC.rglob("*.py"))
for file in files:
    tree = ast.parse(file.read_text())
    bound = set(dir(builtins)) | {"__name__", "__file__"}
    imported = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                name = (a.asname or a.name).split(".")[0]
                bound.add(name); imported[name] = n.lineno
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
            if not isinstance(n, ast.ClassDef):
                for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs + [x for x in (n.args.vararg, n.args.kwarg) if x]:
                    bound.add(a.arg)
        elif isinstance(n, ast.Lambda):
            for a in n.args.args + n.args.kwonlyargs:
                bound.add(a.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            used.add(n.id)
            if n.id not in bound:
                print(f"{file.relative_to(SRC)}:{n.lineno}: undefined name '{n.id}'"); problems += 1
        if isinstance(n, ast.Attribute):
            pass
    # string annotations / __all__ count as use
    text = file.read_text()
    for name, line in imported.items():
        if name not in used and name not in text.replace(f"import {name}", "", 1) and file.name != "__init__.py":
            print(f"{file.relative_to(SRC)}:{line}: unused import '{name}'")
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("assistant") and n.level == 0:
            target = module_path(n.module)
            if target is None:
                print(f"{file.relative_to(SRC)}:{n.lineno}: module not found: {n.module}"); problems += 1; continue
            names = top_level_names(ast.parse(target.read_text()))
            for a in n.names:
                sub = module_path(f"{n.module}.{a.name}")
                if a.name != "*" and a.name not in names and sub is None:
                    print(f"{file.relative_to(SRC)}:{n.lineno}: '{a.name}' not defined in {n.module}"); problems += 1
print(f"{len(files)} files checked, {problems} problem(s)")
sys.exit(1 if problems else 0)
