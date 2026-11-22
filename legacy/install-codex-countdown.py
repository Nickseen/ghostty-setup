#!/usr/bin/python3
"""Install the verified native countdown build beside the official package."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

source = Path(sys.argv[1] if len(sys.argv) > 1 else '/private/tmp/codex-reset-source-0.165.0')
built = source / 'codex-rs/target/dev-small/codex'
official = Path('/opt/homebrew/bin/codex').resolve(strict=True)
package = official.parent.parent
metadata = json.loads((package / 'codex-package.json').read_text())
if metadata['version'] != '0.165.0':
    raise SystemExit('Expected official Codex 0.165.0; no launch commands changed')
result = subprocess.run([str(built), '--version'], check=True, capture_output=True, text=True)
if '0.165.0' not in result.stdout:
    raise SystemExit('Built binary version mismatch')
target = Path.home() / '.local/opt/codex-reset/0.165.0'
if target.exists():
    raise SystemExit('Custom package already exists; refusing to overwrite it blindly')
target.mkdir(parents=True)
for name in ('codex-package.json', 'codex-resources', 'codex-path'):
    entry = package / name
    if entry.is_dir():
        shutil.copytree(entry, target / name, symlinks=True)
    else:
        shutil.copy2(entry, target / name)
(target / 'bin').mkdir()
shutil.copy2(built, target / 'bin/codex')
shutil.copy2(package / 'bin/codex-code-mode-host', target / 'bin/codex-code-mode-host')
(target / 'LOCAL_COUNTDOWN_BUILD.txt').write_text(
    'Official Codex rust-v0.165.0 + local five-hour footer countdown.\n'
    'Source: https://github.com/openai/codex/tree/rust-v0.165.0\n'
    'Patch and rebuild scripts: ~/ghosty-setup/\n'
    'Installed: ' + datetime.now().isoformat() + '\n')
launcher = Path.home() / '.local/bin/codex'
launcher.parent.mkdir(parents=True, exist_ok=True)
if launcher.exists() or launcher.is_symlink():
    raise SystemExit('A personal codex launcher already exists; package installed, launch command unchanged')
# Existing shells already have ~/.local/bin in PATH. Preserve all CLI arguments.
launcher.write_text('''#!/bin/zsh
official=/opt/homebrew/bin/codex
resolved=${official:A}
custom="$HOME/.local/opt/codex-reset/0.165.0/bin/codex"
if [[ "$resolved" == */codex/0.165.0/bin/codex && -x "$custom" ]]; then
    exec "$custom" "$@"
fi
exec "$official" "$@"
''')
launcher.chmod(0o755)
print('Native countdown installed:', target / 'bin/codex')
print('Official Homebrew executable retained:', official)
