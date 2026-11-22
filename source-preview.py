#!/usr/bin/python3
"""Open a syntax-highlighted, inert source document in native Quick Look."""
import argparse
import hashlib
import html
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

MAX_BYTES = 2 * 1024 * 1024
MAX_LINES = 20000


def render_source(source, cache_root=None):
    source = Path(source).absolute()
    if not source.is_file():
        raise ValueError('Файл не найден: ' + str(source))
    with source.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    clipped = len(data) > MAX_BYTES
    data = data[:MAX_BYTES]
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = data.decode('utf-16', errors='replace')
    elif data.startswith(b'\xef\xbb\xbf'):
        text = data.decode('utf-8-sig', errors='replace')
    else:
        if b'\0' in data:
            return source  # Native Quick Look handles binary files.
        text = data.decode('utf-8', errors='replace')
    lines = text.splitlines(keepends=True)
    clipped = clipped or len(lines) > MAX_LINES
    text = ''.join(lines[:MAX_LINES])
    theme = Path(__file__).with_name('source-preview-mocha.theme')
    highlight = shutil.which('highlight') or '/opt/homebrew/bin/highlight'
    command = [highlight, '--out-format=html', '--fragment', '--enclose-pre', '--inline-css',
               '--line-numbers', '--replace-tabs=4', '--font=Menlo', '--font-size=13',
               '--style=' + str(theme), '--encoding=UTF-8', '--force',
               '--syntax-by-name=' + source.name]
    if source.suffix.lower() == '.ipynb':
        command.append('--syntax=json')
    try:
        result = subprocess.run(command, input=text.encode(), capture_output=True,
                                check=True, timeout=10)
        code = result.stdout.decode('utf-8', errors='replace')
        if not code.strip().startswith('<pre'):
            raise ValueError('Highlighter returned no source preview')
    except (OSError, ValueError, subprocess.SubprocessError):
        # Unknown syntax must remain readable; no raw HTML from source is executed.
        code = '<pre>' + '\n'.join(
            '<span class="line-number">' + str(i).rjust(5) + '</span>  ' + html.escape(line)
            for i, line in enumerate(text.splitlines(), 1)) + '</pre>'
    title = html.escape(source.name)
    note = '<div class="note">Показано начало большого файла.</div>' if clipped else ''
    document = '''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>''' + title + '''</title><style>
:root { color-scheme: dark; }
html, body { margin: 0; background: #1e1e2e; color: #cdd6f4; }
header { padding: 18px 22px; background: #181825; border-bottom: 1px solid #313244;
         font: 14px -apple-system, sans-serif; overflow-wrap: anywhere; }
header strong { color: #89b4fa; font-weight: 600; }
header small { display: block; margin-top: 6px; color: #9399b2; overflow-wrap: anywhere; }
pre { margin: 0; padding: 18px 22px; font: 13px/1.65 Menlo, monospace !important;
      white-space: pre-wrap !important; overflow-wrap: anywhere; word-break: normal;
      tab-size: 4; background: #1e1e2e !important; }
.line-number { color: #6c7086; user-select: none; }
.note { padding: 12px 22px; color: #f9e2af; font: 13px -apple-system, sans-serif; }
</style></head><body><header><strong>''' + title + '''</strong><small>''' + html.escape(str(source)) + \
        '</small></header>' + note + code + '</body></html>'
    root = Path(cache_root) if cache_root else Path.home() / 'Library/Caches/ghostty-setup/source-preview'
    digest = hashlib.sha256((str(source) + '\0' + document).encode()).hexdigest()[:24]
    folder = root / digest
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = source.name.encode()[:160].decode('utf-8', errors='ignore') + '.html'
    output = folder / filename
    fd, temporary = tempfile.mkstemp(prefix='.render-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(document)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file')
    parser.add_argument('--render-only', action='store_true')
    args = parser.parse_args()
    preview = render_source(args.file)
    if args.render_only:
        print(preview)
    else:
        front = Path(__file__).with_name('quicklook-front.sh')
        subprocess.run([str(front), str(preview)], check=True)


if __name__ == '__main__':
    main()
