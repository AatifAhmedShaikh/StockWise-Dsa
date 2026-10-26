#!/usr/bin/env sh
# One-command start for Linux and macOS. Nothing to install: only Python 3.8 or newer is needed.
cd "$(dirname "$0")" || exit 1
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' ||
    { echo "StockWise needs Python 3.8 or newer."; exit 1; }
exec python3 stockwise.py "$@"
