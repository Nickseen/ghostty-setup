"""Measure a real wheel burst followed by a keyboard action on a private PTY."""
import fcntl
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

BINARY = Path(os.environ.get('BROOT_SCROLL_TEST_BINARY', str(Path(__file__).parent / '.build/broot-folders-src/target/release/broot')))


def measure(count=400):
    with tempfile.TemporaryDirectory(prefix='broot-scroll-check-') as temporary:
        base = Path(temporary)
        root = base / 'files'
        root.mkdir()
        for index in range(600):
            (root / f'file-{index:04}.txt').touch()
        config = base / 'conf.hjson'
        config.write_text('{"modal":true,"initial_mode":"command","show_selection_mark":true}')
        bootstrap = base / 'launch.py'
        if os.environ.get('BROOT_SCROLL_PROXY') == '1':
            workspace = Path(__file__).parent.resolve()
            proxy_source = Path(os.environ.get('BROOT_SCROLL_PROXY_SCRIPT', str(workspace / 'broot-file-import.py')))
            bootstrap.write_text('import os,sys,importlib.util\n'
                                 f'sys.path.insert(0,{str(workspace)!r})\n'
                                 f'spec=importlib.util.spec_from_file_location("proxy",{str(proxy_source)!r})\n'
                                 'proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)\n'
                                 f'proxy.real_broot=lambda: {str(BINARY.resolve())!r}\n'
                                 'proxy.command_modifier_down=lambda: False\n'
                                 f'sys.exit(proxy.launch([{str(root)!r}]))\n')
        pid, fd = pty.fork()
        if pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            os.environ.pop('TMUX', None)
            if bootstrap.exists():
                os.execv('/usr/bin/python3', ['/usr/bin/python3', str(bootstrap)])
            os.execv(str(BINARY), [str(BINARY), '--conf', str(config), '--cmd', ':watch', str(root)])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 100, 0, 0))
        os.set_blocking(fd, False)
        output = bytearray()
        pending = bytearray()
        def queue(data):
            pending.extend(data)
        def pump(duration):
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                readable, writable, _ = select.select([fd], [fd] if pending else [], [], .005)
                if writable:
                    try:
                        sent = os.write(fd, pending[:4096])
                        del pending[:sent]
                    except BlockingIOError:
                        pass
                if readable:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        break
                    output.extend(data)
                    if b'\x1b[6n' in data:
                        queue(b'\x1b[1;1R')
                    if b'\x1b]11;?' in data:
                        queue(b'\x1b]11;rgb:1e1e/1e1e/2e2e\x1b\\')
                    if b'\x1b[c' in data:
                        queue(b'\x1b[?1;2c')
                    if b'\x1b[?u' in data:
                        queue(b'\x1b[?0u')
                    if b'\x1b[5n' in data:
                        queue(b'\x1b[0n')
        try:
            startup = time.monotonic() + 8
            while b'file-0000.txt' not in output and time.monotonic() < startup:
                pump(.05)
            if b'file-0000.txt' not in output:
                raise AssertionError('Broot did not finish startup')
            pump(.15)
            start = time.monotonic()
            output.clear()
            help_seen = False
            queue(b'\x1b[<65;20;12M' * count + b'\x1b[<64;20;12M' * count + b'?')
            while time.monotonic() - start < 25:
                pump(.02)
                clean = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', bytes(output[-100000:]))
                if b'lets you explore directory trees' in clean:
                    help_seen = True
                    break
            elapsed = time.monotonic() - start
            print(f'{count * 2} wheel events + keyboard response: {elapsed:.3f}s, output {len(output)} bytes', flush=True)
            (Path(__file__).parent / '.build/broot-scroll-transcript.bin').write_bytes(output)
            if not help_seen:
                raise AssertionError('The keyboard action remained blocked behind wheel events')
            return elapsed
        finally:
            os.kill(pid, signal.SIGTERM)
            os.close(fd)
            os.waitpid(pid, 0)


if __name__ == '__main__':
    measure()
