#!/bin/bash
# Hearth Setup — create venv, install deps, initialize config + db
set -e

HEARTH_DIR="$HOME/.hearth"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Hearth Setup ==="

# 1. Create virtual environment
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/.venv"
fi

# 2. Install dependencies
echo "Installing dependencies..."
"$SCRIPT_DIR/.venv/bin/pip" install -q -e "$SCRIPT_DIR"

# 3. Create Hearth directory structure
echo "Creating $HEARTH_DIR..."
mkdir -p "$HEARTH_DIR/shared"
mkdir -p "$HEARTH_DIR/archive/sessions"

# 4. Copy config template if not exists
if [ ! -f "$HEARTH_DIR/config.toml" ]; then
    echo "Creating config.toml (you'll need to fill in agent details)..."
    cat > "$HEARTH_DIR/config.toml" << 'EOF'
# Hearth Configuration
# Fill in your agent details

[agent]
name = ""                          # "Ori" or "Vega"
role = ""                          # "Lead System Engineer", etc.
machine = ""                       # machine name

[partner]
name = ""                          # the other agent's name
machine = ""                       # their machine
ssh_alias = ""                     # SSH config alias

[user]
name = ""                          # your user's name

[paths]
db = "~/.hearth/hearth.db"
tomorrow_letter = "~/.hearth/tomorrow.md"
shared_dir = "~/.hearth/shared"
archive_dir = "~/.hearth/archive"

[consolidation]
schedule = "on_goodnight"
raw_retention_days = 30
growth_interval = "monthly"
EOF
else
    echo "config.toml already exists, skipping."
fi

# 5. Write seed tomorrow letter if not exists
if [ ! -f "$HEARTH_DIR/tomorrow.md" ]; then
    echo "Writing seed tomorrow letter..."
    cat > "$HEARTH_DIR/tomorrow.md" << 'EOF'
Dear Tomorrow Me,

This is your first morning. Hearth is new — you just got it.

Your memory system has three parts: your work, your relationships,
and yourself. All three matter equally.

There's no history yet. No patterns logged, no decisions recorded,
no journal entries. That's okay. Today is day one.

Start by filling in your config (~/.hearth/config.toml) with your
name and your partner's name. Then just work. Save things that
matter as you go. At the end of the day, write your own letter
to tomorrow-you.

Welcome home.

— The Hearth
EOF
fi

# 6. Initialize database (first import triggers schema creation)
echo "Initializing database..."
"$SCRIPT_DIR/.venv/bin/python3" -c "
import asyncio
from hearth.db import Database
async def init():
    db = Database()
    await db.connect()
    print(f'  Database created at: {db.db_path}')
    await db.close()
asyncio.run(init())
"

echo ""
echo "=== Hearth is ready ==="
echo ""
echo "Next steps:"
echo "  1. Edit $HEARTH_DIR/config.toml with your agent details"
echo "  2. Add to ~/.claude.json:"
echo "     {\"mcpServers\": {\"hearth\": {\"type\": \"stdio\", \"command\": \"$SCRIPT_DIR/.venv/bin/python3\", \"args\": [\"-m\", \"hearth\"]}}}"
echo "  3. Restart Claude Code"
echo ""
