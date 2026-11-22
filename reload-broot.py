#!/usr/bin/python3
"""Reload the single running personal Broot pane without changing its root."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

import broot_actions as actions


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout.strip()


def tmux(*args):
    return run(['tmux', *args])


rows = [line.split('\t') for line in tmux(
    'list-panes', '-a', '-F', '#{pane_id}\t#{pane_pid}\t#{@broot_file_import}'
).splitlines()]
rows = [row for row in rows if len(row) > 2 and row[2] == '1']
if len(rows) != 1:
    raise SystemExit('Expected one active personal Broot; no panes were changed.')
pane, shell, _ = rows[0]
socket = None
for wrapper in run(['pgrep', '-P', shell]).splitlines():
    if '/.config/broot/file-import.py' not in run(['ps', '-p', wrapper, '-o', 'command=']):
        continue
    for child in run(['pgrep', '-P', wrapper]).splitlines():
        match = re.search(r'--listen\s+(\S+)', run(['ps', '-p', child, '-o', 'command=']))
        if match:
            socket = match.group(1)
            break
if not socket:
    raise SystemExit('Broot control socket not found; no action taken.')
binary = '/opt/homebrew/bin/broot'
root = run([binary, '--send', socket, '--get-root'])
session = Path('/tmp') / socket.removeprefix('file-import-')
receipt = session / 'last-trash.json'
if receipt.exists():
    actions.adopt_trash_receipt(json.loads(receipt.read_text()), root)
run([binary, '--send', socket, '--cmd', ':quit'])
for _ in range(50):
    time.sleep(.1)
    if tmux('display-message', '-p', '-t', pane, '#{pane_current_command}') in ('zsh', 'bash', 'fish'):
        break
else:
    raise SystemExit('The shell did not resume; no launch command was sent.')
tmux('send-keys', '-t', pane, '-l', shlex.join([str(Path.home() / '.local/bin/broot'), root]))
tmux('send-keys', '-t', pane, 'Enter')
for _ in range(50):
    time.sleep(.1)
    if tmux('display-message', '-p', '-t', pane, '#{@broot_file_import}') == '1':
        break
else:
    raise SystemExit('Updated Broot did not start.')
time.sleep(.3)
screen = tmux('capture-pane', '-p', '-t', pane)
print('Updated Broot active:', pane)
print('Root preserved:', root)
print('File icon codepoints present:', any(0x100000 <= ord(c) <= 0x10FFFF for c in screen))
print('No search error:', 'Invalid search mode' not in screen)
