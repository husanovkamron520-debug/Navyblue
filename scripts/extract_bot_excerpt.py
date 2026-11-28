"""Extract inventory-related pieces of the Mini App HTML (analysis helper, read-only)."""
import os
import re

html = open("supply_chain_mini_app.html", encoding="utf-8").read()
out = []


def add(title, body):
    out.append(f"\n===== {title} =====\n{body}\n")


m = re.search(r'<section id="inventory-view".*?</section>', html, re.S)
add("INVENTORY SECTION", m.group(0) if m else "NOT FOUND")


def js_function(name):
    start = html.find(name)
    if start < 0:
        return "NOT FOUND"
    brace = html.find("{", start)
    depth = 0
    in_str = None
    i = brace
    while i < len(html):
        ch = html[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in "\"'`":
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return html[start:i + 1]
        i += 1
    return "UNTERMINATED"


for fn in ("function makeProductCard", "async function loadInventory", "async function archiveInventoryProduct"):
    add(fn, js_function(fn)[:7000])

hits = [line.strip()[:260] for line in html.split("\n")
        if re.search(r'detail-delete|getElementById\("(prev|next|search|status|sort)"\)|\$\("(prev|next|search|inventory-refresh)"\)|function switchView|const \$ =|let token|let page', line)]
add("LISTENER LINES", "\n".join(hits[:40]))
add("SIZE", str(len(html)))

os.makedirs("analysis", exist_ok=True)
open("analysis/bot_excerpt.txt", "w", encoding="utf-8").write("".join(out))
print("written", sum(len(x) for x in out))
