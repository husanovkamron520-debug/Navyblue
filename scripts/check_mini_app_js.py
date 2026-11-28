"""CI gate: every inline <script> of the Mini App must pass `node --check`."""
import re
import subprocess
import sys
import tempfile

html = open("supply_chain_mini_app.html", encoding="utf-8").read()
blocks = [b for b in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S) if b.strip()]
if not blocks:
    raise SystemExit("No inline script found in the Mini App")
for index, block in enumerate(blocks):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(block)
    result = subprocess.run(["node", "--check", handle.name], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
        raise SystemExit(f"Inline script #{index} has a syntax error")
print(f"Mini App inline scripts OK ({len(blocks)})")
