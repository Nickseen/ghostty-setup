#!/usr/bin/python3
"""Check real Space/Ctrl+O dispatch in an isolated Broot, without opening apps."""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time

binary = '/opt/homebrew/bin/broot'
with tempfile.TemporaryDirectory(prefix='broot-preview-check-') as tmp:
    base = Path(tmp).resolve()
    tree = base / 'tree'
    tree.mkdir()
    source = tree / 'main.go'
    source.write_text('package old_code_fixture\n')
    def git(*args):
        subprocess.run(['git', '-C', str(tree), *args], check=True, capture_output=True)
    git('init', '-q')
    git('add', 'main.go')
    git('-c', 'user.name=Preview Test', '-c', 'user.email=preview@example.invalid',
        '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
    source.write_text('package source_preview_fixture\n\nfunc main() { println("highlighted code") }\n')
    for name, content in [('data.json', '{"source_json_fixture": true}\n'),
                          ('Dockerfile', 'FROM source_docker_fixture\n'),
                          ('page.html', '<html>source_html_fixture</html>\n')]:
        (tree / name).write_text(content)
    for name, content in [('image.SVG', b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
                          ('report.PDF', b'%PDF-1.4\n'), ('photo.png', b'\x89PNG\r\n'),
                          ('document.docx', b'PK\x03\x04'), ('database.db', b'SQLite format 3\0')]:
        (tree / name).write_bytes(content)
    receipt = base / 'quicklook.json'
    source_receipt = base / 'source-window.json'
    stub = base / 'quicklook-stub.py'
    stub.write_text('#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\n'
                    f'Path({str(receipt)!r}).write_text(json.dumps(sys.argv[1:]))\n')
    stub.chmod(0o755)
    source_stub = base / 'source-stub.py'
    source_stub.write_text('import json,sys\nfrom pathlib import Path\n'
                           f'Path({str(source_receipt)!r}).write_text(json.dumps(sys.argv[1:]))\n')
    verbs = base / 'verbs.hjson'
    verbs.write_text(Path(__file__).with_name('broot-verbs.hjson').read_text().replace(
        '@BROOT_HOME@/quicklook-front.sh', str(stub)).replace(
        '@BROOT_HOME@/source-preview.py', str(source_stub)))
    conf = base / 'conf.hjson'
    conf.write_text(json.dumps({'modal': True, 'initial_mode': 'command', 'default_flags': 'g',
                               'imports': [str(verbs), str(Path.home() / '.config/broot/skins/dark-blue.hjson')]}))
    socket = 'preview-check-' + str(os.getpid())
    pid, fd = pty.fork()
    if pid == 0:
        os.environ['TERM'] = 'xterm-256color'
        os.execv(binary, [binary, '--conf', str(conf), '--listen', socket, str(tree)])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
    transcript = bytearray()
    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([fd], [], [], .03)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                transcript.extend(data)
                if b'\x1b[6n' in data:
                    os.write(fd, b'\x1b[1;1R')
                if b'\x1b]11;?' in data:
                    os.write(fd, b'\x1b]11;rgb:1e1e/1e1e/2e2e\x1b\\')
                if b'\x1b[c' in data:
                    os.write(fd, b'\x1b[?1;2c')
    def command(text):
        result = subprocess.run([binary, '--send', socket, '--cmd', text],
                                capture_output=True, timeout=3)
        assert result.returncode == 0, result.stderr.decode(errors='replace') + transcript[-2200:].decode(errors='replace')
        pump(.1)
    try:
        pump(.7)
        assert b'Invalid verb configuration' not in transcript, transcript.decode(errors='replace')
        for name, content in [('main.go', b'source_preview_fixture'),
                              ('data.json', b'source_json_fixture'),
                              ('Dockerfile', b'source_docker_fixture'),
                              ('page.html', b'source_html_fixture')]:
            command(':select ' + str(tree / name))
            offset = len(transcript)
            os.write(fd, b' ')
            deadline = time.monotonic() + 3
            while not source_receipt.exists() and time.monotonic() < deadline:
                pump(.1)
            rendered = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', transcript[offset:])
            assert source_receipt.exists(), (name, rendered[-1000:])
            assert json.loads(source_receipt.read_text()) == [str(tree / name)]
            assert content not in rendered, 'Source was rendered inside a split instead of a window'
            assert not receipt.exists(), 'A source file bypassed the highlighter'
            source_receipt.unlink()
        for name in ('image.SVG', 'report.PDF', 'photo.png', 'document.docx', 'database.db'):
            command(':select ' + str(tree / name))
            offset = len(transcript)
            os.write(fd, b' ')
            deadline = time.monotonic() + 3
            while not receipt.exists() and time.monotonic() < deadline:
                pump(.1)
            assert receipt.exists(), name + ' did not use Quick Look: ' + transcript[offset:][-2000:].decode(errors='replace')
            assert json.loads(receipt.read_text()) == [str(tree / name)]
            receipt.unlink()
        command(':select ' + str(source))
        for shortcut in (b'\x10', b'\x0f'):
            os.write(fd, shortcut)  # Ctrl+P and Ctrl+O both use the source window.
            deadline = time.monotonic() + 3
            while not source_receipt.exists() and time.monotonic() < deadline:
                pump(.1)
            assert json.loads(source_receipt.read_text()) == [str(source)]
            source_receipt.unlink()
        print('Verified: source files → highlighted window; SVG/PDF/images/Office → native Quick Look; '
              'Space, Ctrl+P and Ctrl+O use windows without a Broot split.')
    finally:
        subprocess.run([binary, '--send', socket, '--cmd', ':quit'], capture_output=True, timeout=3)
        pump(.1)
        os.close(fd)
        child, _ = os.waitpid(pid, os.WNOHANG)
        if not child:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
