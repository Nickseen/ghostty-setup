#!/usr/bin/python3
"""Update only the preview bindings in the personal Broot verbs file."""
from datetime import datetime
from pathlib import Path
import re
import shutil

source = Path(__file__).with_name('broot-verbs.hjson').read_text()
source = source.replace('@BROOT_HOME@', str(Path.home() / '.config/broot'))
start = '    # Visual formats take precedence over text detection (SVG is XML).'
end = '    # You should customize this standard opening of text files.'
replacement = source[source.index(start):source.index(end)]
path = Path.home() / '.config/broot/verbs.hjson'
if not (shutil.which('highlight') or Path('/opt/homebrew/bin/highlight').is_file()):
    raise SystemExit('Install the Highlight renderer first: brew install highlight')
text = path.read_text()
# Remove the old Ctrl+P split binding so all preview shortcuts use a window.
text = re.sub(r'    # Show or hide a quick preview of the selected file in Broot\.\n    \{\n        key: ctrl-p\n        internal: ":toggle_preview"\n        apply_to: file\n    \}\n\n', '', text)
for name in ('source-preview.py', 'source-preview-mocha.theme'):
    shutil.copy2(Path(__file__).with_name(name), path.parent / name)
if replacement in text:
    print('Preview bindings already up to date')
    raise SystemExit(0)
pattern = r'    # (?:Show the selected file in Quick Look in front of Ghostty\.|Visual formats take precedence over text detection \(SVG is XML\)\.).*?(?=    # You should customize this standard opening of text files\.)'
updated, count = re.subn(pattern, lambda _: replacement, text, flags=re.S)
if count != 1:
    raise SystemExit('Existing preview bindings not recognized; config unchanged')
backup = path.with_name('verbs.hjson.before-smart-preview-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
shutil.copy2(path, backup)
path.write_text(updated)
print('Installed: all previews in native Quick Look; source files with Mocha highlighting')
