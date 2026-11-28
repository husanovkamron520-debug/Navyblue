"""Extract archive/delete related code (analysis helper, read-only)."""
import ast
import os
import re

budget = 85000
out = []


def add(title, body):
    global budget
    chunk = f"\n===== {title} =====\n{body}\n"
    if len(chunk) > budget:
        chunk = chunk[:max(0, budget)] + "\n[TRUNCATED]\n"
    budget -= len(chunk)
    out.append(chunk)


def scan(path, pattern_name, pattern_body, limit=9000):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node) or ""
            if re.search(pattern_name, node.name) or re.search(pattern_body, seg):
                rows.append((node, seg))
    add(f"{path} SUMMARY", "\n".join(f"{n.name} {n.lineno}-{n.end_lineno} size {len(s)}" for n, s in rows))
    for node, seg in sorted(rows, key=lambda r: len(r[1])):
        if len(seg) <= limit:
            add(f"{path}::{node.name} ({node.lineno}-{node.end_lineno})", seg)


scan("bot.py", r"_sc_api_delete|delete_inventory|archive", r"deleted_products|archive_product|_sc_delete_inventory_product")
if os.path.exists("supply_chain_tenants.py"):
    scan("supply_chain_tenants.py", r"commit|archive|delete", r"deleted_products|archive", limit=6000)
scan("supply_chain_api.py", r"archive|delete", r"deleted_products|archive", limit=5000)

os.makedirs("analysis", exist_ok=True)
open("analysis/bot_excerpt.txt", "w", encoding="utf-8").write("".join(out))
print("written", sum(len(x) for x in out))
