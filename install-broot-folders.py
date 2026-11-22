#!/usr/bin/python3
"""Install the private Broot disclosure build and update the existing proxy."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from setup_support import brew_binary

workspace = Path(__file__).resolve().parent
source = workspace / '.build/broot-folders-src'
built = source / 'target/release/broot'
official = brew_binary('broot').resolve(strict=True)
for binary in (built,):
    result = subprocess.run([str(binary), '--version'], check=True, capture_output=True, text=True)
    if result.stdout.strip() != 'broot 1.61.0':
        raise SystemExit('Expected Broot 1.61.0; no installed files changed')

target = Path.home() / '.local/opt/broot-folders/1.61.0'
proxy = Path.home() / '.config/broot/file-import.py'
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = Path.home() / '.config/broot/folders-backup' / stamp
backup.mkdir(parents=True)
if proxy.exists():
    shutil.copy2(proxy, backup / 'file-import.py')
if (target / 'bin/broot').exists():
    shutil.copy2(target / 'bin/broot', backup / 'broot')
(target / 'bin').mkdir(parents=True, exist_ok=True)
# Replace the inode atomically: overwriting an executable used by a live process
# can leave macOS's code-signature cache rejecting the new contents with SIGKILL.
fd, pending = tempfile.mkstemp(prefix='.broot-', dir=target / 'bin')
os.close(fd)
try:
    shutil.copy2(built, pending)
    subprocess.run([pending, '--version'], check=True, capture_output=True)
    os.replace(pending, target / 'bin/broot')
finally:
    Path(pending).unlink(missing_ok=True)
for name in ('LICENSE', 'LICENSE.md', 'LICENSE-MIT'):
    if (source / name).is_file():
        shutil.copy2(source / name, target / name)
shutil.copy2(workspace / 'broot-input-events.LICENSE', target / 'input-events.LICENSE')
metadata = {'base_version': '1.61.0', 'feature': 'folder disclosures, hidden scrollbar, nested Git status, batched trackpad scrolling and shortcut hints',
            'official_binary': str(official), 'installed_at': datetime.now().isoformat(),
            'source_patch': str(workspace / 'broot-folders.patch'),
            'source_patches': [str(workspace / name) for name in ('broot-folders.patch', 'broot-no-scrollbar.patch', 'broot-nested-git.patch', 'broot-scroll.patch', 'broot-untracked-u.patch', 'broot-shortcut-hints.patch')],
            'input_source': str(workspace / 'broot-input-events.rs')}
(target / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
shutil.copy2(workspace / 'broot-file-import.py', proxy)
print('Folder disclosures installed:', target / 'bin/broot')
print('Official Broot retained:', official)
print('Proxy backup:', backup)
