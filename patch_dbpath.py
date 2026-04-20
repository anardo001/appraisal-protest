
import re
from pathlib import Path

app_path = Path(__file__).parent / "backend" / "app.py"
content = app_path.read_text(encoding="utf-8")

# Remove the dotenv import lines if we previously added them
content = re.sub(r'^from dotenv import load_dotenv\n', '', content, flags=re.MULTILINE)
content = re.sub(r'^load_dotenv\([^\n]+\)\n', '', content, flags=re.MULTILINE)

# Replace the DB_PATH line — use env var with relative fallback, no dotenv
old_pattern = re.compile(r'^DB_PATH\s*=\s*Path\([^\n]+\)', re.MULTILINE)
new_line = 'DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "dcad2026.db")))'

if not old_pattern.search(content):
    print("ERROR: DB_PATH line not found.")
    raise SystemExit(1)

patched = old_pattern.sub(new_line, content)

# Ensure 'import os' is present near the top
if 'import os' not in patched:
    patched = patched.replace('import sys', 'import os\nimport sys', 1)

app_path.write_text(patched, encoding="utf-8")
print("Patched: DB_PATH uses os.environ with relative fallback (no dotenv).")
print(f"Verify: {[l for l in patched.splitlines() if 'DB_PATH' in l and 'Path' in l][0]}")
