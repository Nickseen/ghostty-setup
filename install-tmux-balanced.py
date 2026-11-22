#!/usr/bin/python3
"""Install a private tmux and launchers; keep all existing servers running."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from setup_support import atomic_copy, brew_binary, install_launchers

workspace = Path(__file__).resolve().parent
binary = workspace / '.build/tmux-3.8/tmux'
official = brew_binary('tmux')
resolved = official.resolve(strict=True)
version = subprocess.check_output([str(binary), '-V'], text=True).strip()
if version != 'tmux 3.8-balanced.1':
    raise SystemExit('Expected the tested private tmux 3.8-balanced.1')
target = Path.home() / '.local/opt/tmux-balanced/3.8'
launchers = Path.home() / '.local/bin'
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = Path.home() / '.config/ghostty-setup/tmux-balanced-backup' / stamp
backup.mkdir(parents=True)
for source in (target / 'bin/tmux', launchers / 'tmux', launchers / 'tmux-balanced'):
    if source.exists() or source.is_symlink():
        shutil.copy2(source, backup / ('binary' if source.parent == target / 'bin' else source.name))
(target / 'bin').mkdir(parents=True, exist_ok=True)
launchers.mkdir(parents=True, exist_ok=True)
atomic_copy(binary, target / 'bin/tmux')
(target / 'bin/tmux').chmod(0o755)
shutil.copy2(workspace / '.build/tmux-3.8/COPYING', target / 'COPYING')
metadata = {'base_version': '3.8', 'private_version': version,
            'official_binary': str(resolved), 'installed_at': datetime.now().isoformat(),
            'source_patch': str(workspace / 'tmux-balanced.patch'),
            'source_extension': str(workspace / 'tmux-balanced-layout.c'),
            'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'source_sha256': hashlib.sha256((workspace / '.build/tmux-3.8.tar.gz').read_bytes()).hexdigest()}
(target / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
install_launchers()
print('Installed:', target / 'bin/tmux')
print('Official binary retained:', resolved)
print('Existing servers unchanged. New isolated workspace: tmux-balanced new -A -s myproject')
print('Backup:', backup)
