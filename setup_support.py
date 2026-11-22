"""Shared portable paths, atomic installs and explicit custom/official launchers."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
VERSIONS = json.loads((ROOT / 'versions.json').read_text())
MARKER = '# Managed by ghostty-setup.'


def brew_binary(name):
    """Do not resolve ~/.local/bin wrappers back into themselves."""
    brew = shutil.which('brew')
    prefixes = []
    if brew:
        prefixes.append(Path(subprocess.check_output([brew, '--prefix'], text=True).strip()))
    prefixes += [Path('/opt/homebrew'), Path('/usr/local')]
    for prefix in prefixes:
        path = prefix / 'bin' / name
        if path.is_file():
            return path
    raise RuntimeError('Missing Homebrew binary: ' + name)


def atomic_write(path, text, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.chmod(pending, mode)
        os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def atomic_copy(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix='.install-', dir=destination.parent)
    os.close(fd)
    try:
        shutil.copy2(source, pending)
        os.replace(pending, destination)
    finally:
        Path(pending).unlink(missing_ok=True)


def launcher_text(name, official, custom):
    optout = {'codex': 'CODEX_OFFICIAL', 'tmux': 'TMUX_OFFICIAL'}[name]
    lines = ['#!/bin/zsh', MARKER,
             'official=' + shlex.quote(str(official)),
             'custom=' + shlex.quote(str(custom)),
             '# Keep the tested build even when Homebrew upgrades its separate binary.',
             'if [[ ${' + optout + ':-0} != 1 && -x "$custom" ]]; then']
    if name == 'tmux':
        socket = VERSIONS['tmux_socket']
        lines += ['    if [[ ${TMUX_BALANCED:-1} != 0 ]]; then',
                  '        explicit_socket=0',
                  '        for arg in "$@"; do',
                  '            case "$arg" in -L*|-S*) explicit_socket=1 ;; esac',
                  '        done',
                  '        if [[ -z ${TMUX:-} && $explicit_socket == 0 && ${TMUX_SETUP_SOCKET:-' + socket + '} != default ]]; then',
                  '            exec "$custom" -L "${TMUX_SETUP_SOCKET:-' + socket + '}" "$@"',
                  '        fi',
                  '        exec "$custom" "$@"',
                  '    fi']
    else:
        lines += ['    exec "$custom" "$@"']
    lines += ['fi', 'if [[ ${' + optout + ':-0} != 1 ]]; then',
              '    print -u2 "ghostty-setup: custom ' + name + ' unavailable; using official. Run ghostty-setup doctor."',
              'fi', 'exec "$official" "$@"', '']
    return '\n'.join(lines)


def install_launchers():
    home = Path.home()
    paths = home / '.local/bin'
    for name, relative in [('codex', 'codex-image-preview/' + VERSIONS['codex']),
                           ('tmux', 'tmux-balanced/' + VERSIONS['tmux'])]:
        target = paths / name
        if target.exists():
            text = target.read_text()
            if not any(mark in text for mark in [MARKER, '# Local Codex image-click preview client.',
                                                '# Select the private build only while its official base is unchanged.']):
                raise RuntimeError('Unmanaged launcher exists: ' + str(target))
        custom = home / '.local/opt' / relative / 'bin' / name
        atomic_write(target, launcher_text(name, brew_binary(name), custom), 0o755)
    atomic_write(paths / 'tmux-balanced', '#!/bin/zsh\n' + MARKER + '\n'
                 '# An isolated server guarantees the private resize implementation.\n'
                 'exec "$HOME/.local/opt/tmux-balanced/' + VERSIONS['tmux'] + '/bin/tmux" -L ' + shlex.quote(VERSIONS['tmux_socket']) + ' "$@"\n', 0o755)
    atomic_write(paths / 'ghostty-setup', '#!/bin/zsh\n' + MARKER + '\nexec /usr/bin/python3 '
                 + shlex.quote(str(ROOT / 'setup.py')) + ' "$@"\n', 0o755)
