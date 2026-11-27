"""Extract the parts of bot.py / tenant modules that handle the Supply Chain Mini App API (analysis helper, read-only)."""
import ast
import os
import re

budget = 80000
out = []


def add(title, body):
    global budget
    chunk = f"\n===== {title} =====\n{body}\n"
    if len(chunk) > budget:
        chunk = chunk[:max(0, budget)] + "\n[TRUNCATED]\n"
    budget -= len(chunk)
    out.append(chunk)


src = open("bot.py", encoding="utf-8").read()
lines = src.split("\n")
tree = ast.parse(src)

summary = []
bodies = {}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        seg = ast.get_source_segment(src, node) or ""
        if re.search(r"sc_|tenant|supply", node.name, re.I) or "tenant" in seg.lower():
            summary.append(f"{node.name} lines {node.lineno}-{node.end_lineno} size {len(seg)}")
            bodies.setdefault(node.name, []).append(seg)
add("SUMMARY bot.py functions (sc/tenant)", "\n".join(sorted(summary)))

for name in ("_sc_api_get", "_sc_api_post"):
    for seg in bodies.get(name, []):
        add(f"{name} FULL", seg[:16000])

grep_hits = []
for i, line in enumerate(lines):
    if re.search(r"visible_charts|supply_chain_telegram_tenants|sc_tenants|TenantSessionStore|_SC_TENANT|SC_TENANT", line):
        grep_hits.append(f"{i + 1}: {line.strip()[:200]}")
add("GREP hits", "\n".join(grep_hits[:80]))

for module in ("supply_chain_telegram_tenants.py",):
    if os.path.exists(module):
        msrc = open(module, encoding="utf-8").read()
        mtree = ast.parse(msrc)
        names = []
        for node in ast.walk(mtree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seg = ast.get_source_segment(msrc, node) or ""
                names.append(f"{node.name} lines {node.lineno}-{node.end_lineno} size {len(seg)}")
        add(f"SUMMARY {module}", "\n".join(names))
        head = msrc[:3500]
        add(f"HEAD {module}", head)

os.makedirs("analysis", exist_ok=True)
open("analysis/bot_excerpt.txt", "w", encoding="utf-8").write("".join(out))
print("written", sum(len(x) for x in out))
