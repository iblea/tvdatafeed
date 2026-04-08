#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$(cd "$SCRIPT_DIR/.." && pwd):$PYTHONPATH"
python "$SCRIPT_DIR/sample_test.py" "$@"
