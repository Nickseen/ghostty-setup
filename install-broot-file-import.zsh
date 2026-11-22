#!/bin/zsh
set -euo pipefail

setup_dir="${0:A:h}"
mkdir -p "$setup_dir/.build"
if [[ ! -x "$setup_dir/.build/broot-copy-hotkey" || "$setup_dir/broot-copy-hotkey.swift" -nt "$setup_dir/.build/broot-copy-hotkey" ]]; then
    /usr/bin/swiftc -module-cache-path "$setup_dir/.build/swift-module-cache" "$setup_dir/broot-copy-hotkey.swift" -o "$setup_dir/.build/broot-copy-hotkey"
fi
if [[ ! -x "$setup_dir/.build/broot-trash" || "$setup_dir/broot-trash.swift" -nt "$setup_dir/.build/broot-trash" ]]; then
    /usr/bin/swiftc "$setup_dir/broot-trash.swift" -o "$setup_dir/.build/broot-trash"
fi
if [[ ! -f "$setup_dir/.build/broot-vscode.ttf" ]]; then
    curl -fLsS --max-time 30 https://raw.githubusercontent.com/Canop/broot/v1.61.0/resources/icons/vscode/vscode.ttf -o "$setup_dir/.build/broot-vscode.ttf"
fi
if [[ ! -x "$setup_dir/.build/register-broot-font" || "$setup_dir/register-broot-font.swift" -nt "$setup_dir/.build/register-broot-font" ]]; then
    /usr/bin/swiftc "$setup_dir/register-broot-font.swift" -o "$setup_dir/.build/register-broot-font"
fi
mkdir -p "$HOME/.config/broot" "$HOME/.local/bin" "$HOME/Library/Fonts"
backup_dir="$HOME/.config/broot/file-import-backup-$(date +%Y%m%d-%H%M%S)"
for target in "$HOME/.config/broot/file-import.py" "$HOME/.config/broot/broot_actions.py" "$HOME/.config/broot/broot-copy-hotkey" "$HOME/.config/broot/broot-trash" "$HOME/.config/broot/conf.hjson" "$HOME/.local/bin/broot" "$HOME/.tmux.conf"; do
    if [[ -e "$target" || -L "$target" ]]; then
        mkdir -p "$backup_dir"
        cp -p "$target" "$backup_dir/${target:t}"
    fi
done
install -m 0644 "$setup_dir/broot_actions.py" "$HOME/.config/broot/broot_actions.py"
install -m 0644 "$setup_dir/broot-file-import.py" "$HOME/.config/broot/file-import.py"
/usr/bin/python3 "$setup_dir/install-native-helpers.py"
install -m 0755 "$setup_dir/broot-launch.zsh" "$HOME/.local/bin/broot"
"$setup_dir/.build/register-broot-font" "$HOME/Library/Fonts/broot-vscode.ttf"
/usr/bin/python3 <<'PY'
from pathlib import Path
import re
import shutil
import subprocess
config = Path.home() / '.config/broot/conf.hjson'
if config.exists():
    text = config.read_text()
    text, count = re.subn(r'^[ \t]*#?[ \t]*icon_theme:.*$', 'icon_theme: vscode', text, count=1, flags=re.M)
    if not count:
        text += '\nicon_theme: vscode\n'
    text, count = re.subn(r'^[ \t]*#?[ \t]*auto_open_staging_area:.*$', 'auto_open_staging_area: false', text, count=1, flags=re.M)
    if not count:
        text += '\nauto_open_staging_area: false\n'
    config.write_text(text)
path = Path.home() / '.tmux.conf'
if path.exists():
    original = path.read_text()
    text = original.replace('#{?#{==:#{pane_current_command},broot},',
                            '#{?#{||:#{==:#{pane_current_command},broot},#{@broot_file_import}},')
    if text != original:
        path.write_text(text)
    tmux = shutil.which('tmux')
    for line in text.splitlines():
        if tmux and line.startswith("set -g status-left '"):
            subprocess.run([tmux, 'set-option', '-g', 'status-left', line.split("'", 2)[1]],
                           capture_output=True)
PY
printf '%s\n' 'Broot: file import, Trash undo, file actions, VS Code icons and automatic refresh installed.'
