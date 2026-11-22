"""Replace helper inodes atomically, including while the old helpers are running."""
from pathlib import Path
from setup_support import ROOT, atomic_copy

home = Path.home()
for source, destination in [
    ('.build/broot-copy-hotkey', '.config/broot/broot-copy-hotkey'),
    ('.build/broot-trash', '.config/broot/broot-trash'),
    ('.build/broot-vscode.ttf', 'Library/Fonts/broot-vscode.ttf'),
]:
    atomic_copy(ROOT / source, home / destination)
