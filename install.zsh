#!/bin/zsh
set -euo pipefail
setup_dir="${0:A:h}"
exec /usr/bin/python3 "$setup_dir/setup.py" install "$@"
