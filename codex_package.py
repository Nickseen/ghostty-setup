"""Find or fetch the verified official support files for our pinned CLI build."""
import hashlib
import json
from pathlib import Path
import platform
import tarfile
import urllib.request
from setup_support import ROOT, VERSIONS, brew_binary


def find_package():
    version = VERSIONS['codex']
    candidates = []
    try:
        candidates.append(brew_binary('codex').resolve().parent.parent)
    except RuntimeError:
        pass
    candidates.append(Path.home() / '.local/opt/codex-image-preview' / version)
    for candidate in candidates:
        try:
            if json.loads((candidate / 'codex-package.json').read_text())['version'] == version:
                return candidate
        except (OSError, ValueError, KeyError):
            pass
    info = VERSIONS['codex_packages'][platform.machine()]
    archive = ROOT / '.build' / info['asset']
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        url = 'https://github.com/openai/codex/releases/download/rust-v' + version + '/' + info['asset']
        request = urllib.request.Request(url, headers={'User-Agent': 'ghostty-setup'})
        pending = archive.with_suffix('.pending')
        try:
            with urllib.request.urlopen(request, timeout=60) as response, pending.open('wb') as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            pending.replace(archive)
        finally:
            pending.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != info['sha256']:
        raise RuntimeError('Codex package checksum mismatch; archive was not extracted')
    destination = ROOT / '.build' / ('codex-package-' + version + '-' + platform.machine())
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        root = destination.resolve()
        for member in tar.getmembers():
            target = (root / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError('Unsafe archive path')
            if member.isdev() or member.isfifo():
                raise RuntimeError('Unsupported archive member')
            if member.issym() or member.islnk():
                link = ((target.parent if member.issym() else root) / member.linkname).resolve()
                if link != root and root not in link.parents:
                    raise RuntimeError('Unsafe archive link')
        tar.extractall(root)
    manifests = list(destination.rglob('codex-package.json'))
    if len(manifests) != 1 or json.loads(manifests[0].read_text())['version'] != version:
        raise RuntimeError('Unexpected Codex package layout/version')
    return manifests[0].parent
