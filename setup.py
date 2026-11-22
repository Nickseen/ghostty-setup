#!/usr/bin/env python3
"""Install, inspect, repair and roll back the macOS terminal setup."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from setup_support import ROOT, VERSIONS, atomic_copy, atomic_write, brew_binary, install_launchers


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def render(text, home):
    escaped = json.dumps(str(home / '.config/broot'), ensure_ascii=False)[1:-1]
    return text.replace('@BROOT_HOME@', escaped).replace(
        '@SETUP_HOME@', str(home / '.config/ghostty-setup'))


def config_files(home):
    mappings = {
        'ghostty.conf': 'Library/Application Support/com.mitchellh.ghostty/config.ghostty',
        'tmux.conf': '.tmux.conf', 'starship.toml': '.config/starship.toml',
        'broot-conf.hjson': '.config/broot/conf.hjson', 'broot-verbs.hjson': '.config/broot/verbs.hjson',
        'broot-file-import.py': '.config/broot/file-import.py', 'broot_actions.py': '.config/broot/broot_actions.py',
        'source-preview.py': '.config/broot/source-preview.py',
        'source-preview-mocha.theme': '.config/broot/source-preview-mocha.theme',
        'quicklook-front.sh': '.config/broot/quicklook-front.sh',
        'quicklook-front.applescript': '.config/broot/quicklook-front.applescript',
        'skins/dark-blue.hjson': '.config/broot/skins/dark-blue.hjson',
        'skins/white.hjson': '.config/broot/skins/white.hjson',
        'codex-shell.zsh': '.config/ghostty-setup/codex-shell.zsh',
        'codex-reset-countdown.py': '.config/ghostty-setup/codex-reset-countdown.py',
        'broot-launch.zsh': '.local/bin/broot',
    }
    return [(ROOT / source, home / target) for source, target in mappings.items()]


def managed_paths(home):
    return [p for _, p in config_files(home)] + [home / x for x in [
        '.zshrc', '.local/bin/codex', '.local/bin/tmux', '.local/bin/tmux-balanced',
        '.local/bin/ghostty-setup', '.config/broot/broot-copy-hotkey',
        '.config/broot/broot-trash', 'Library/Fonts/broot-vscode.ttf']]


def backup(home):
    folder = home / '.config/ghostty-setup/backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    records = []
    for path in managed_paths(home):
        relative = str(path.relative_to(home))
        exists = path.exists() or path.is_symlink()
        records.append({'path': relative, 'existed': exists})
        if exists:
            target = folder / 'files' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=False)
    atomic_write(folder / 'manifest.json', json.dumps(records, indent=2) + '\n', 0o600)
    return folder


def install_configs(home):
    for source, target in config_files(home):
        mode = 0o755 if source.suffix == '.sh' or source.name == 'broot-launch.zsh' else 0o644
        atomic_write(target, render(source.read_text(), home), mode)
    zsh = home / '.zshrc'
    text = zsh.read_text() if zsh.exists() else ''
    for line in ['export PATH="$HOME/.local/bin:$PATH"', 'eval "$(starship init zsh)"',
                 'source "$HOME/.config/ghostty-setup/codex-shell.zsh"']:
        if line not in text:
            text += '\n' + line + '\n'
    atomic_write(zsh, text)
    # Never import or overwrite model/auth/MCP settings.
    codex = home / '.codex/config.toml'
    if not codex.exists():
        atomic_write(codex, (ROOT / 'codex-tui.toml').read_text(), 0o600)


def build(component, force=False):
    artifacts = {'tmux': '.build/tmux-3.8/tmux', 'broot': '.build/broot-folders-src/target/release/broot',
                 'codex': '.build/codex-image-preview-src/codex-rs/target/dev-small/codex'}
    scripts = {'tmux': 'build-tmux-balanced.zsh', 'broot': 'build-broot-folders.zsh',
               'codex': 'build-codex-image-preview.zsh'}
    if force or not (ROOT / artifacts[component]).is_file():
        run(['/bin/zsh', ROOT / scripts[component]], cwd=ROOT)
    else:
        print('Using local build:', component, flush=True)


def install(args):
    home = Path.home()
    if args.dry_run:
        for source, target in config_files(home):
            print(str(source.relative_to(ROOT)) + ' -> ' + str(target))
        print('Full profile:', args.full, '; no files changed')
        return
    if platform.system() != 'Darwin':
        raise RuntimeError('This setup targets macOS; Linux is not supported')
    if args.brew:
        run(['brew', 'bundle', '--file', ROOT / 'Brewfile'])
    for name in ['tmux', 'broot', 'starship', 'highlight', 'codex']:
        brew_binary(name)
    if args.full:
        for component in ['tmux', 'broot', 'codex']:
            build(component, args.rebuild)
    print('Backup:', backup(home), flush=True)
    install_configs(home)
    if args.full:
        for script in ['install-tmux-balanced.py', 'install-broot-folders.py', 'install-codex-image-preview.py']:
            run([sys.executable, ROOT / script], cwd=ROOT)
    run(['/bin/zsh', ROOT / 'install-broot-file-import.zsh'], cwd=ROOT)
    install_launchers()
    print('Installed; existing tasks/servers were not stopped.')
    print('New full-feature workspace: tmux-balanced new -A -s myproject')
    print('Check: ghostty-setup doctor; repair graphics: ghostty-setup repair')


def output(args, timeout=5):
    try:
        p = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def no_color_scopes(command):
    """Inspect only NO_COLOR, never dump a server's potentially secret environment."""
    scopes = []
    sessions = output(command + ['list-sessions', '-F', '#{session_id}'])
    if sessions is None:
        return scopes
    for label, flags in [('server', ['-g'])] + [
            (session, ['-t', session]) for session in sessions.splitlines()]:
        value = output(command + ['show-environment'] + flags + ['NO_COLOR'])
        if value and value.startswith('NO_COLOR=') and value != 'NO_COLOR=':
            scopes.append((label, flags))
    return scopes


def repair_colors(command):
    # Existing shells/clients keep their own environment and must be reopened.
    for _, flags in no_color_scopes(command):
        run(command + ['set-environment'] + flags + ['-u', 'NO_COLOR'])


def doctor(args):
    home, warnings = Path.home(), []
    def report(ok, text):
        print(('OK   ' if ok else 'WARN ') + text)
        if not ok:
            warnings.append(text)
    report(Path('/Applications/Ghostty.app/Contents/MacOS/ghostty').is_file(), 'Ghostty installed')
    for source, target in config_files(home):
        report(target.is_file() and target.read_text() == render(source.read_text(), home),
               'config ' + str(target.relative_to(home)))
    for name, relative, version in [('tmux', 'tmux-balanced/3.8', 'tmux ' + VERSIONS['tmux_private']),
        ('codex', 'codex-image-preview/0.169.0', 'codex-cli 0.169.0'), ('broot', 'broot-folders/1.61.0', 'broot 1.61.0')]:
        custom = home / '.local/opt' / relative / 'bin' / name
        actual = output([custom, '-V' if name == 'tmux' else '--version'], timeout=20) if custom.is_file() else None
        report(actual == version, name + ' private build: ' + str(actual or 'missing'))
        if name != 'broot':
            wrapper = home / '.local/bin' / name
            text = wrapper.read_text() if wrapper.is_file() else ''
            report('# Managed by ghostty-setup.' in text and '${official:A}' not in text,
                   name + ' launcher survives independent Homebrew updates')
    for helper in ['broot-copy-hotkey', 'broot-trash', 'quicklook-front.sh']:
        report(os.access(home / '.config/broot' / helper, os.X_OK), 'Broot helper ' + helper)
    processes = output(['/bin/ps', '-axo', 'comm='])
    if processes:
        custom_count = sum('codex-image-preview/' in line for line in processes.splitlines())
        official_count = sum('/Caskroom/codex/' in line and line.rstrip().endswith('/bin/codex')
                             for line in processes.splitlines())
        print('INFO running Codex clients: private=' + str(custom_count) + ', official=' + str(official_count))
    tmux = home / '.local/bin/tmux'
    if tmux.is_file():
        server = output([tmux, 'display-message', '-p', '#{version}'])
        if server:
            expected_server = VERSIONS['tmux_private']
            report(server == expected_server, 'current/default tmux server: ' + server +
                   ('; use tmux-balanced in a NEW tab; old tasks stay alive' if server != expected_server else ''))
            graphics = output([tmux, 'list-panes', '-a', '-F', '#{pane_id} #{allow-passthrough}'])
            report(bool(graphics) and all(x.endswith(' all') for x in graphics.splitlines()),
                   'graphics passthrough for all live panes')
        else:
            print('INFO no current/default tmux server')
        balanced = output([home / '.local/bin/tmux-balanced', 'display-message', '-p', '#{version}'])
        if balanced:
            report(balanced == VERSIONS['tmux_private'], 'isolated balanced server: ' + balanced)
            disabled = no_color_scopes([home / '.local/bin/tmux-balanced'])
            report(not disabled, 'managed tmux color environment' +
                   ('; NO_COLOR disables colors AND image previews; run ghostty-setup repair --colors, then reopen affected shells/Codex'
                    if disabled else ''))
        else:
            print('INFO start the updated server with: tmux-balanced new -A -s myproject')
        legacy = output([brew_binary('tmux'), '-L', 'default', 'display-message', '-p', '#{version}'])
        if legacy and 'balanced' not in legacy:
            print('INFO legacy default server still runs ' + legacy + '; its existing panes do not gain balanced resize.')
    print('INFO Dock-click / hot-corner utility was discussed only; it is not installed.')
    print('INFO Reopen Codex after graphics repair if its startup cached graphics=off.')
    if args.strict and warnings:
        raise SystemExit(1)


def repair(args):
    install_launchers()
    for socket in set(['default', 'balanced', 'balanced-v2', 'balanced-v3', VERSIONS['tmux_socket']]):
        command = [brew_binary('tmux'), '-L', socket]
        if output(command + ['list-sessions']) is not None:
            run(command + ['set-option', '-g', 'allow-passthrough', 'all'])
            if args.colors:
                repair_colors(command)
    print('Launchers and graphics repaired; no running task stopped.')
    if args.colors:
        print('NO_COLOR cleared from tmux environments. Reopen affected shells/Codex; existing processes retain their old environment.')
    doctor(argparse.Namespace(strict=False))


def restore(args):
    home = Path.home()
    folder = Path(args.backup).expanduser().resolve()
    root = (home / '.config/ghostty-setup/backups').resolve()
    if root not in folder.parents:
        raise RuntimeError('Choose a backup under ' + str(root))
    records = json.loads((folder / 'manifest.json').read_text())
    allowed = {str(p.relative_to(home)) for p in managed_paths(home)}
    if any(item['path'] not in allowed for item in records):
        raise RuntimeError('Unknown backup destination')
    for item in records:
        target = home / item['path']
        if item['existed']:
            saved = folder / 'files' / item['path']
            if saved.is_symlink():
                target.unlink(missing_ok=True)
                target.symlink_to(os.readlink(saved))
            else:
                atomic_copy(saved, target)
        else:
            target.unlink(missing_ok=True)
    print('Restored configs and launchers; existing tasks were not stopped.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('install')
    for flag in ['full', 'brew', 'rebuild', 'dry-run']:
        p.add_argument('--' + flag, action='store_true')
    p.set_defaults(func=install)
    p = sub.add_parser('doctor');p.add_argument('--strict', action='store_true');p.set_defaults(func=doctor)
    p = sub.add_parser('repair')
    p.add_argument('--colors', action='store_true', help='clear NO_COLOR from tmux server/session environments')
    p.set_defaults(func=repair)
    p = sub.add_parser('restore');p.add_argument('backup');p.set_defaults(func=restore)
    p = sub.add_parser('build');p.add_argument('component', choices=['tmux', 'broot', 'codex'])
    p.set_defaults(func=lambda a: build(a.component, True))
    args = parser.parse_args()
    try:
        args.func(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'ghostty-setup: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
