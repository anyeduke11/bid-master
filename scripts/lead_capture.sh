#!/bin/bash
# lead_capture.sh · L1 标讯真抓取入口 (crawl4ai 版 v0.4.0)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -x "$REPO_DIR/.venv/bin/python3" ]; then
  exec "$REPO_DIR/.venv/bin/python3" "$SCRIPT_DIR/lead_capture_crawl4ai.py" "$@"
else
  exec python3 "$SCRIPT_DIR/lead_capture_crawl4ai.py" "$@"
fi
