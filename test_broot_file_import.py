"""Regression checks for copying user files and forwarding terminal input."""

import importlib.util
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import termios
import tempfile
import time
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("broot_import", Path(__file__).with_name("broot-file-import.py"))
broot_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(broot_import)


class FileImportTests(unittest.TestCase):
    def test_command_click_survives_split_mouse_frames_and_preserves_normal_click(self):
        output = []
        stream = broot_import.CommandClickStream(output.append)
        down, up = b'\x1b[<0;15;4M', b'\x1b[<0;15;4m'
        with patch.object(broot_import, 'command_modifier_down', return_value=True):
            for byte in down + up:
                stream.feed(bytes([byte]))
        self.assertEqual(b''.join(output), down + up + b'\x1b[25~')
        output.clear()
        with patch.object(broot_import, 'command_modifier_down', return_value=False):
            stream.feed(down + up + b'hello\x03')
        self.assertEqual(b''.join(output), down + up + b'hello\x03')

    def test_cmd_backspace_does_not_reassign_control_u(self):
        with patch.object(broot_import, 'command_modifier_down', return_value=False):
            self.assertIsNone(broot_import.shortcut_command(b'\x15'))
        with patch.object(broot_import, 'command_modifier_down', return_value=True):
            self.assertEqual(broot_import.shortcut_command(b'\x15'), ':btrash')

    def test_copy_batch_preserves_originals_and_existing_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            file = source / "Отчёт $(echo nope); ' №1.pdf"
            file.write_bytes(b"pdf fixture")
            folder = source / "Folder with spaces"
            folder.mkdir()
            (folder / "inside.txt").write_text("nested")
            (folder / "link").symlink_to("inside.txt")
            dangling = source / "missing-link"
            dangling.symlink_to("absent")
            existing = target / file.name
            existing.write_text("keep existing")

            copied = broot_import.copy_files(target, [str(file), str(folder), str(dangling)])

            self.assertEqual(existing.read_text(), "keep existing")
            self.assertEqual(file.read_bytes(), b"pdf fixture")
            self.assertEqual(Path(copied[0]).read_bytes(), b"pdf fixture")
            self.assertIn(" copy.pdf", copied[0])
            self.assertEqual((target / folder.name / "inside.txt").read_text(), "nested")
            self.assertEqual(os.readlink(target / folder.name / "link"), "inside.txt")
            self.assertTrue((target / dangling.name).is_symlink())
            self.assertTrue(folder.exists())
            self.assertFalse(any(p.name.startswith(".broot-import-") for p in target.iterdir()))

    def test_recursive_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            with self.assertRaises(ValueError):
                broot_import.copy_files(child, [str(root)])
            self.assertEqual(list(child.iterdir()), [])

    def test_repeated_pastes_keep_all_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "same.txt"
            file.write_text("original")
            for _ in range(3):
                broot_import.copy_files(root, [str(file)])
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ["same copy 2.txt", "same copy 3.txt", "same copy.txt", "same.txt"])

    def test_path_decoding_handles_ghostty_escaping_and_ordinary_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "Файл ' with spaces.txt"
            file.touch()
            self.assertEqual(broot_import.pasted_paths(shlex.quote(str(file)).encode()), [str(file)])
            self.assertEqual(broot_import.pasted_paths(file.as_uri().encode()), [str(file)])
            self.assertIsNone(broot_import.pasted_paths(b"ordinary search text"))
            self.assertIsNone(broot_import.pasted_paths(b"/nonexistent/file.txt"))

    def test_stream_split_frames_and_passthrough(self):
        output, imported = [], []
        def receive(payload):
            imported.append(payload)
            return payload == b"file payload"
        parser = broot_import.PasteStream(output.append, receive)
        data = b"\x1b[B" + broot_import.PASTE_START + b"file payload" + broot_import.PASTE_END + b"x"
        for byte in data:
            parser.feed(bytes([byte]))
        self.assertEqual(b"".join(output), b"\x1b[Bx")
        text_paste = broot_import.PASTE_START + b"text\nsecond line" + broot_import.PASTE_END
        parser.feed(text_paste)
        self.assertTrue(b"".join(output).endswith(text_paste))
        self.assertEqual(imported, [b"file payload", b"text\nsecond line"])


class NativeBrootTests(unittest.TestCase):
    def test_native_trash_is_recoverable_and_root_is_protected(self):
        with tempfile.TemporaryDirectory(prefix='broot-trash-test-') as tmp:
            root = Path(tmp)
            self.assertIsNone(broot_import.trash_file(root, root))
            self.assertTrue(root.is_dir())
            for name in (f"{root.name}-Файл with spaces.txt", f"{root.name}-folder with spaces"):
                source = root / name
                if name.endswith('.txt'):
                    source.write_text('recoverable fixture')
                else:
                    source.mkdir()
                    (source / 'inside.txt').write_text('recoverable fixture')
                trashed = broot_import.trash_file(source, root)
                try:
                    self.assertFalse(source.exists())
                    self.assertTrue(trashed.exists())
                    content = trashed / 'inside.txt' if trashed.is_dir() else trashed
                    self.assertEqual(content.read_text(), 'recoverable fixture')
                finally:
                    os.rename(trashed, source)  # restore only this fixture, leaving Trash unchanged

    def test_native_macos_file_clipboard_reader(self):
        import json
        import subprocess
        code = broot_import.CLIPBOARD_SCRIPT.split("\nvar drag =")[0]
        code += '''
var pb=$.NSPasteboard.pasteboardWithUniqueName;
pb.clearContents;
pb.setStringForType('file:///tmp/Fixture%20with%20spaces.txt', 'public.file-url');
var result=files(pb); pb.releaseGlobally; JSON.stringify(result);
'''
        result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", code],
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ["/tmp/Fixture with spaces.txt"])

    def test_real_broot_imports_into_selected_folder_and_still_quits(self):
        """Exercise native Broot + private socket + proxy in an isolated PTY.

        Clipboard metadata must not be required: Finder can leave its drag
        pasteboard empty. Ghostty supplies the paths for both paste and drop.
        """
        with tempfile.TemporaryDirectory(prefix="broot-test-") as tmp:
            base = Path(tmp).resolve()
            root = base / "tree"
            root.mkdir()
            destination = root / "destination"
            destination.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            tracked = root / 'tracked.txt'
            tracked.write_text('before diff fixture\n')
            subprocess.run(['git', '-C', str(root), 'add', 'tracked.txt'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Broot Test', '-c',
                            'user.email=broot-test@example.invalid', '-c', 'core.hooksPath=/dev/null',
                            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'], check=True)
            tracked.write_text('after diff fixture\n')
            file = base / "Файл with spaces.txt"
            file.write_text("native integration")
            clipboard_capture = base / 'clipboard.txt'
            reveal_capture = base / 'reveal.json'
            action_fixture = base / 'actions-fixture.py'
            action_fixture.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0, %r)
import broot_actions as actions
original_run = actions.subprocess.run
def run(args, **kwargs):
    if args == ['/usr/bin/pbcopy']:
        Path(%r).write_bytes(kwargs['input'])
        return actions.subprocess.CompletedProcess(args, 0)
    if args[:2] == ['/usr/bin/open', '-R']:
        Path(%r).write_text(json.dumps(args[2:]))
        return actions.subprocess.CompletedProcess(args, 0)
    return original_run(args, **kwargs)
actions.subprocess.run = run
sys.exit(actions.main(sys.argv[1:]))
''' % (str(Path(__file__).parent), str(clipboard_capture), str(reveal_capture)))
            sessions_before = set(Path('/tmp').glob('broot-import-*'))
            receipt = None
            pid, master = pty.fork()
            if pid == 0:
                os.environ["TERM"] = "xterm-256color"
                os.environ.pop("TMUX", None)
                os.environ.pop("TMUX_PANE", None)
                os.environ['XDG_STATE_HOME'] = str(base / 'state')
                broot_import.command_modifier_down = lambda: True
                broot_import.actions.__file__ = str(action_fixture)
                def no_clipboard_dependency():
                    raise AssertionError('File imports must not depend on macOS pasteboard metadata')
                broot_import.clipboard_files = no_clipboard_dependency
                try:
                    os._exit(broot_import.launch([str(root)]))
                except BaseException:
                    import traceback
                    traceback.print_exc()
                    os._exit(1)
            transcript = bytearray()
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
            exited = False
            def pump(seconds):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], min(0.03, max(0, deadline - time.monotonic())))
                    if ready:
                        try:
                            data = os.read(master, 65536)
                        except OSError:
                            return
                        if not data:
                            return
                        transcript.extend(data)
                        if b"\x1b[6n" in data:
                            os.write(master, b"\x1b[1;1R")
                        if b"\x1b]11;?" in data:
                            os.write(master, b"\x1b]11;rgb:1e1e/1e1e/2e2e\x1b\\")
                        if b"\x1b[5n" in data:
                            os.write(master, b"\x1b[0n")
                        # This fixture is xterm-256color: don't claim Kitty
                        # support while supplying legacy UTF-8 key input.
                        if b"\x1b[c" in data:
                            os.write(master, b"\x1b[?1;2c")
            try:
                pump(1.2)
                self.assertIn(b"destination", transcript, transcript[-3000:].decode(errors="replace"))
                sessions = set(Path('/tmp').glob('broot-import-*')) - sessions_before
                self.assertEqual(len(sessions), 1)
                session = sessions.pop()
                receipt = session / 'last-trash.json'
                socket = 'file-import-' + session.name
                self.assertIn(b"\x1b[?2004h", transcript, "Ghostty needs bracketed paste enabled for drops")
                def command(value):
                    subprocess.run([broot_import.real_broot(), '--send', socket, '--cmd', value],
                                   check=True, capture_output=True, stdin=subprocess.DEVNULL)
                    pump(.15)

                # Two native clicks arrive on different tree rows. The proxy
                # adds F13 in the same stream so native selection precedes stage.
                clicked = []
                for row in (2, 3):
                    os.write(master, f'\x1b[<0;10;{row}M\x1b[<0;10;{row}m'.encode())
                    pump(.35)
                    clicked.append(json.loads((session / 'selected-paths.json').read_text()))
                manifest = session / 'selected-paths.json'
                self.assertTrue(manifest.exists(), transcript[-1200:].decode(errors='replace'))
                chosen = json.loads(manifest.read_text())
                self.assertEqual(len(chosen), 2, 'Cmd-click did not select two files: ' + repr(clicked) + '\n' + transcript[-1500:].decode(errors='replace'))
                self.assertNotIn(b'Staging Area', transcript)
                self.assertIn(broot_import.SelectionMarkStyle.blue + '◍'.encode(), transcript)
                command(':bcopypaths')
                self.assertEqual(clipboard_capture.read_text(), '\n'.join(chosen))
                os.write(master, b'\x1b[<0;10;2M\x1b[<0;10;2m')
                pump(.25)
                self.assertEqual(json.loads(manifest.read_text()), chosen[1:])
                command(':bcopypaths')
                self.assertEqual(clipboard_capture.read_text(), chosen[1])
                os.write(master, b'\x1b')  # Escape clears selection without a staging panel
                pump(.3)
                self.assertEqual(json.loads(manifest.read_text()), [])
                command(':select ' + str(tracked))
                command(':bcopypaths')
                self.assertEqual(clipboard_capture.read_text(), str(tracked))
                command(':select_first')

                command(':select ' + str(tracked))
                os.write(master, b'\x1b[26~')  # F14 is the native Reveal action.
                deadline = time.monotonic() + 3
                while not reveal_capture.exists() and time.monotonic() < deadline:
                    pump(.1)
                self.assertEqual(json.loads(reveal_capture.read_text()), [str(tracked)])
                reveal_capture.unlink()
                command(':select ' + str(destination))
                command(':reveal')
                deadline = time.monotonic() + 3
                while not reveal_capture.exists() and time.monotonic() < deadline:
                    pump(.1)
                self.assertEqual(json.loads(reveal_capture.read_text()), [str(destination)])
                command(':select_first')

                command(':nf created Файл.txt')
                deadline = time.monotonic() + 3
                while not (root / 'created Файл.txt').exists() and time.monotonic() < deadline:
                    pump(.1)
                self.assertTrue((root / 'created Файл.txt').is_file(), transcript[-1000:].decode(errors='replace'))
                command(':nd created-folder')
                deadline = time.monotonic() + 3
                while not (root / 'created-folder').is_dir() and time.monotonic() < deadline:
                    pump(.1)
                self.assertTrue((root / 'created-folder').is_dir(), transcript[-1000:].decode(errors='replace'))

                (root / 'from-agent.txt').write_text('external change')
                deadline = time.monotonic() + 3
                while b'from-agent.txt' not in transcript and time.monotonic() < deadline:
                    pump(.1)
                self.assertTrue(b'from-agent.txt' in transcript, 'Native watch did not refresh the tree')

                command(':select ' + str(tracked))
                before_diff = len(transcript)
                os.write(master, b'\x1b[17~')  # F6
                pump(.4)
                diff_text = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', bytes(transcript[before_diff:]))
                self.assertTrue(b'before diff fixture' in diff_text and b'after diff fixture' in diff_text,
                                'Diff preview did not show changes: ' + diff_text[-1400:].decode(errors='replace'))
                command(':close_preview')
                command(':select_first')
                os.write(master, b'\x15')  # Cmd+Backspace on root must be harmless
                pump(.15)
                self.assertTrue(root.is_dir())
                command(':select ' + str(destination))
                paste = broot_import.PASTE_START + shlex.quote(str(file)).encode() + broot_import.PASTE_END
                os.write(master, paste)
                deadline = time.monotonic() + 5
                while not (destination / file.name).exists() and time.monotonic() < deadline:
                    pump(0.1)
                self.assertTrue((destination / file.name).exists(), transcript[-4000:].decode(errors="replace"))
                self.assertEqual((destination / file.name).read_text(), "native integration")
                self.assertFalse((root / file.name).exists())
                self.assertTrue(file.exists())
                pump(0.2)
                command(':select_first')
                os.write(master, paste)  # a fresh native drag payload
                deadline = time.monotonic() + 3
                while not (root / file.name).exists() and time.monotonic() < deadline:
                    pump(0.1)
                self.assertEqual((root / file.name).read_text(), "native integration")
                pump(0.2)
                command(':select ' + str(root / file.name))
                os.write(master, b'\x15')  # actual Cmd+Backspace on the selected file
                deadline = time.monotonic() + 4
                while not receipt.exists() and time.monotonic() < deadline:
                    pump(.1)
                self.assertTrue(receipt.exists(), 'Trash command did not execute: '+transcript[-1200:].decode(errors='replace'))
                movement = json.loads(receipt.read_text())
                self.assertEqual(Path(movement['source']).resolve(), (root / file.name).resolve())
                self.assertFalse((root / file.name).exists())
                self.assertTrue((destination / file.name).exists())
                os.write(master, b'\x1b[19~')  # F8: native shortcut for persistent Undo
                deadline = time.monotonic() + 3
                while not (root / file.name).exists() and time.monotonic() < deadline:
                    pump(.1)
                self.assertTrue((root / file.name).exists(), 'F8 did not restore the selected file')
                self.assertFalse(Path(movement['trashed']).exists())
                pump(.15)
                # Finder reuses the same drag data/counter across repeated drops.
                for duplicate in ('Файл with spaces copy.txt', 'Файл with spaces copy 2.txt'):
                    os.write(master, paste)
                    deadline = time.monotonic() + 3
                    while not (root / duplicate).exists() and time.monotonic() < deadline:
                        pump(.1)
                    self.assertTrue((root / duplicate).exists(), 'Repeated drop was lost: '+duplicate)
                    self.assertEqual((root / duplicate).read_text(), 'native integration')
                    pump(.15)
                offset = len(transcript)
                # A split frame must still copy the file with no pasteboard data.
                for chunk in (paste[:8], paste[8:-4], paste[-4:]):
                    os.write(master, chunk)
                    pump(.08)
                deadline = time.monotonic() + 3
                while not (root / 'Файл with spaces copy 3.txt').exists() and time.monotonic() < deadline:
                    pump(.1)
                self.assertTrue((root / 'Файл with spaces copy 3.txt').exists())
                self.assertNotIn(b'Invalid search mode', transcript[offset:])
                os.write(master, b'/')  # focus Broot's search input
                pump(.1)
                os.write(master, broot_import.PASTE_START + b"9876543210" + broot_import.PASTE_END)
                deadline = time.monotonic() + 2
                plain = b''
                while b'9876543210' not in plain and time.monotonic() < deadline:
                    pump(.1)
                    plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", bytes(transcript))
                self.assertTrue(b"9876543210" in plain, "Ordinary text paste must reach Broot: " + plain[-500:].decode(errors="replace"))
                os.write(master, b"\x03")
                for _ in range(50):
                    pump(0.03)
                    child, status = os.waitpid(pid, os.WNOHANG)
                    if child:
                        exited = True
                        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                        break
                self.assertTrue(exited, "Ctrl+C did not exit Broot: " + transcript[-500:].decode(errors="replace"))
            finally:
                if receipt and receipt.exists():
                    movement = json.loads(receipt.read_text())
                    if Path(movement['trashed']).exists() and not Path(movement['source']).exists():
                        os.rename(movement['trashed'], movement['source'])
                os.close(master)
                if not exited:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    os.waitpid(pid, 0)


if __name__ == "__main__":
    unittest.main()
