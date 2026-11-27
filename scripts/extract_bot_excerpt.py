"""Extract the parts of bot.py that handle the Supply Chain Mini App API (analysis helper, read-only)."""
import ast
import re
import sys

src = open("bot.py", encoding="utf-8").read()
lines = src.split("\n")
tree = ast.parse(src)
out = []
budget = 90000


def add(title, body):
    global budget
    chunk = f"\n===== {title} =====\n{body}\n"
    if len(chunk) > budget:
        chunk = chunk[:budget] + "\n[TRUNCATED]\n"
    budget -= len(chunk)
    out.append(chunk)


funcs = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        seg = ast.get_source_segment(src, node) or ""
        if "sc-api" in seg or "sc_api" in seg or "/supply-chain" in seg:
            funcs.append((len(seg), node, seg))
funcs.sort(key=lambda t: t[0])
add("SUMMARY (functions mentioning sc-api)",
    "\n".join(f"{n.name} lines {n.lineno}-{n.end_lineno} size {size}" for size, n, _ in funcs))
for size, node, seg in funcs:
    if size > 14000:
        add(f"{node.name} (lines {node.lineno}-{node.end_lineno}) [too large: head only]", seg[:5000])
    else:
        add(f"{node.name} (lines {node.lineno}-{node.end_lineno})", seg)

consts = []
for node in tree.body:
    if isinstance(node, ast.Assign):
        names = [getattr(t, "id", "") for t in node.targets]
        if any(re.search(r"OWNER|ADMIN|SC_|_SC|RENDER|PORT|APP\b", n) for n in names):
            consts.append(ast.get_source_segment(src, node)[:240])
add("CONSTANTS", "\n".join(consts))

hits = [i for i, l in enumerate(lines) if re.search(r"web\.Application|HTTPServer|run_webhook|run_polling|web\.run_app|add_routes|add_get|add_post", l)]
ctx = []
for i in hits[:12]:
    ctx.append(f"--- line {i + 1}\n" + "\n".join(lines[max(0, i - 6): i + 10]))
add("SERVER STARTUP CONTEXT", "\n".join(ctx))

import os
os.makedirs("analysis", exist_ok=True)
open("analysis/bot_excerpt.txt", "w", encoding="utf-8").write("".join(out))
print("written", sum(len(x) for x in out))
