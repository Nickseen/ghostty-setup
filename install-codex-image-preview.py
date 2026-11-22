"""Install the private image-click client alongside the official Homebrew package."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from codex_package import find_package
from setup_support import VERSIONS, install_launchers

setup = Path(__file__).resolve().parent
version = VERSIONS['codex']
built = setup / '.build/codex-image-preview-src/codex-rs/target/dev-small/codex'
package = find_package()
assert json.loads((package / 'codex-package.json').read_text())['version'] == version
result = subprocess.check_output([str(built), '--version'], text=True).strip()
assert result == 'codex-cli ' + version, result
target = Path.home() / '.local/opt/codex-image-preview' / version
launcher = Path.home() / '.local/bin/codex'
marker = '# Local Codex image-click preview client.'
if launcher.exists() and marker not in launcher.read_text() and '# Managed by ghostty-setup.' not in launcher.read_text():
    raise SystemExit('An unrelated personal launcher exists; no files changed')
target.parent.mkdir(parents=True, exist_ok=True)
pending = Path(tempfile.mkdtemp(prefix='.image-preview-', dir=target.parent))
try:
    shutil.copytree(package, pending, symlinks=True, dirs_exist_ok=True)
    # Replace the executable inode, including inside the staged package.
    staged = pending / 'bin/codex.local'
    shutil.copy2(built, staged)
    staged.chmod(0o755)
    os.replace(staged, pending / 'bin/codex')
    metadata = {'base_version': version, 'source': str(setup / '.build/codex-image-preview-src'),
                'patch': str(setup / 'codex-image-preview.patch'),
                'sha256': hashlib.sha256(built.read_bytes()).hexdigest(),
                'installed_at': datetime.now().isoformat()}
    (pending / 'image-preview-build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if target.exists():
        os.replace(target, target.with_name(version + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    os.replace(pending, target)
finally:
    if pending.exists(): shutil.rmtree(pending)
launcher.parent.mkdir(parents=True, exist_ok=True)
install_launchers()
print('Installed image preview client:', target / 'bin/codex')
print('Launcher:', launcher)
print('Support package:', package)
