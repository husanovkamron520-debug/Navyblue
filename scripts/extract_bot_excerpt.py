"""Extract selected parts of bot.py (analysis helper, read-only)."""
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

WANT = ["_sc_tenant_context", "do_GET", "do_POST", "start_command", "register_telegram_company_selector"]
found = {}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in WANT:
        found.setdefault(node.name, []).append(ast.get_source_segment(src, node) or "")
for name in WANT:
    for seg in found.get(name, []):
        add(f"{name} ({len(seg)} chars)", seg[:7000])

hits = []
for i, line in enumerate(lines):
    if re.search(r"SC_PUBLIC_SIGNUP_ENABLED|MenuButton|menu_button|WebAppInfo|\.js\"|/supply-chain|OWNER_CHAT_ID =|OWNER_CHAT_ID=|TELEGRAM_BOT_TOKEN =|TELEGRAM_BOT_TOKEN=", line):
        hits.append(f"{i + 1}: {line.strip()[:220]}")
add("GREP", "\n".join(hits[:120]))

os.makedirs("analysis", exist_ok=True)
open("analysis/bot_excerpt.txt", "w", encoding="utf-8").write("".join(out))
print("written", sum(len(x) for x in out))
