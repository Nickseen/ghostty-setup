#!/usr/bin/python3
"""Add Finder file pastes/drops to Broot's selected directory on macOS.

Native file clipboard/drop payloads are copied into the selected directory.
Other text goes to Broot's single-line input. Keyboard input, mouse events,
and pastes into Broot's external editor/shell pass through.
The Homebrew Broot binary and its normal configuration remain in use.
"""

import ctypes
import errno
import fcntl
from functools import lru_cache
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import tty
from urllib.parse import unquote, urlsplit
import broot_actions as actions
from broot_actions import publish_exclusive


PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
CLIPBOARD_SCRIPT = r'''
ObjC.import('AppKit');
function files(pb) {
    var result = [];
    var items = pb.pasteboardItems;
    for (var i = 0; items && i < items.count; i++) {
        var value = items.objectAtIndex(i).stringForType('public.file-url');
        if (value && !value.isNil()) {
            var url = $.NSURL.URLWithString(value);
            if (url.isFileURL) result.push(ObjC.unwrap(url.path));
        }
    }
    if (!result.length) {
        var old = pb.propertyListForType('NSFilenamesPboardType');
        if (old && !old.isNil()) result = ObjC.deepUnwrap(old);
    }
    return result;
}
// NSDragPboard is an AppKit constant, not the pasteboard's literal name.
var drag = $.NSPasteboard.pasteboardWithName($.NSDragPboard);
JSON.stringify({general: files($.NSPasteboard.generalPasteboard),
                drag: files(drag), drag_count: Number(drag.changeCount)});
'''


@lru_cache(maxsize=1)
def event_flags_reader():
    graphics = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    reader = graphics.CGEventSourceFlagsState
    reader.argtypes = [ctypes.c_int32]
    reader.restype = ctypes.c_uint64
    return reader


def command_modifier_down():
    try:
        flags = event_flags_reader()(0)  # combined state of the current login session
        return bool(flags & (1 << 20)) and not bool(flags & (1 << 18))
    except (OSError, AttributeError):
        return False


def shortcut_command(data):
    # Ghostty's native Cmd+Backspace sends Ctrl+U. Check the actual modifiers
    # so Ctrl+U remains an input-editing key and Codex needs no remapping.
    if data == b'\x15' and command_modifier_down():
        return ':btrash'
    if data in (b'\x03', b'\x1b[99;5u', b'\x1b[99;5:1u'):
        return ':quit'
    return None


class CommandClickStream:
    """Keep native mouse coordinates; append an ordered selection key on Cmd-click."""
    def __init__(self, send):
        self.send = send
        self.pending = b''
        self.command_click = False
        self.updated = 0

    def feed(self, data):
        self.pending += data
        self.updated = time.monotonic()
        while self.pending:
            match = re.search(rb'\x1b\[<\d+;\d+;\d+[Mm]', self.pending)
            if match:
                self.send(self.pending[:match.start()])
                mouse = match.group()
                button = int(mouse[3:].split(b';', 1)[0])
                left = button & 3 == 0 and not button & (32 | 64)
                if left and mouse.endswith(b'M'):
                    self.command_click = command_modifier_down()
                self.send(mouse)
                if left and mouse.endswith(b'm') and self.command_click:
                    self.send(b'\x1b[25~')  # F13: select native clicked path, then stage it
                    self.command_click = False
                self.pending = self.pending[match.end():]
                continue
            partial = re.search(rb'\x1b(?:\[<?[\d;]*)?$', self.pending)
            if partial:
                self.send(self.pending[:partial.start()])
                self.pending = self.pending[partial.start():]
            else:
                self.send(self.pending)
                self.pending = b''
            break

    def expire(self):
        if self.pending and time.monotonic() - self.updated > .03:
            self.send(self.pending)
            self.pending = b''


class SelectionMarkStyle:
    """Tint Broot's staged-file circles, preserving surrounding terminal styles."""
    marker = '◍'.encode()
    blue = b'\x1b[1;38;2;96;165;250m'

    def __init__(self):
        self.pending = b''
        self.style = b''

    def feed(self, output):
        data = self.pending + output
        self.pending = b''
        partial = re.search(rb'\x1b(?:\[[0-9;:]*)?$', data)
        keep = len(data) - partial.start() if partial else 0
        for size in (1, 2):
            if data.endswith(self.marker[:size]):
                keep = max(keep, size)
        if keep:
            self.pending, data = data[-keep:], data[:-keep]

        def replace(match):
            token = match.group()
            if token == self.marker:
                return self.blue + token + b'\x1b[0m' + self.style
            if token in (b'\x1b[m', b'\x1b[0m'):
                self.style = b''
            else:
                self.style += token
            return token
        return re.sub(rb'\x1b\[[0-9;:]*m|' + self.marker, replace, data)


def trash_file(filename, root):
    source = Path(os.path.abspath(filename))
    tree_root = Path(os.path.abspath(root))
    # Broot initially selects its root. Never trash an entire project this way.
    if source == tree_root or (not source.is_symlink() and source.resolve() == tree_root.resolve()):
        return None
    if not os.path.lexists(source):
        raise FileNotFoundError(str(source))
    helper = Path(__file__).with_name('broot-trash')
    if not helper.exists():
        helper = Path(__file__).parent / '.build/broot-trash'
    result = subprocess.run(
        [str(helper), str(source)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return Path(json.loads(result.stdout)['path'])


def trash_selected(filename, root, receipt=None):
    try:
        destination = actions.remember_trash(filename, root, trash_file)
        if destination is not None and receipt:
            Path(receipt).write_text(json.dumps({'source': filename, 'trashed': str(destination)}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        message = f'Не удалось переместить файл в Корзину: {error}'
        subprocess.run(
            ['/usr/bin/osascript', '-e', 'on run argv\ndisplay alert "Broot" message (item 1 of argv) buttons {"OK"}\nend run', message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return 1


def clipboard_files():
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", CLIPBOARD_SCRIPT],
            capture_output=True, text=True, timeout=3, check=True,
        )
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"general": [], "drag": [], "drag_count": None}


def pasted_paths(payload):
    """Decode Ghostty's shell-escaped paths without executing any shell code."""
    try:
        text = payload.decode("utf-8").strip()
    except UnicodeError:
        return None
    if not text or "\0" in text:
        return None
    # A single unquoted path may itself contain spaces or newlines.
    if os.path.isabs(text) and os.path.lexists(text):
        return [text]
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    if not parts or len(parts) > 1000:
        return None
    paths = []
    for part in parts:
        if part.startswith("file://"):
            url = urlsplit(part)
            if url.netloc not in ("", "localhost"):
                return None
            part = unquote(url.path)
        if not os.path.isabs(part) or not os.path.lexists(part):
            return None
        paths.append(part)
    return paths


def same_paths(left, right):
    return [os.path.normpath(p) for p in left] == [os.path.normpath(p) for p in right]


class PasteStream:
    """Split bracketed pastes even when the terminal sends partial frames."""

    def __init__(self, send, import_paste):
        self.send = send
        self.import_paste = import_paste
        self.pending = b""
        self.in_paste = False
        self.updated = 0

    def feed(self, data):
        self.pending += data
        self.updated = time.monotonic()
        while self.pending:
            if self.in_paste:
                end = self.pending.find(PASTE_END)
                if end < 0:
                    if len(self.pending) > 1024 * 1024:
                        self.flush()
                    return
                payload = self.pending[:end]
                self.pending = self.pending[end + len(PASTE_END):]
                self.in_paste = False
                if not self.import_paste(payload):
                    self.send(PASTE_START + payload + PASTE_END)
                continue
            start = self.pending.find(PASTE_START)
            if start >= 0:
                self.send(self.pending[:start])
                self.pending = self.pending[start + len(PASTE_START):]
                self.in_paste = True
                continue
            # Hold only a possible partial start marker; ordinary typing is instant.
            keep = 0
            for length in range(1, min(len(self.pending), len(PASTE_START) - 1) + 1):
                if self.pending.endswith(PASTE_START[:length]):
                    keep = length
            if keep:
                self.send(self.pending[:-keep])
                self.pending = self.pending[-keep:]
            else:
                self.send(self.pending)
                self.pending = b""
            return

    def flush(self):
        self.send((PASTE_START if self.in_paste else b"") + self.pending)
        self.pending = b""
        self.in_paste = False

    def expire(self):
        timeout = 5 if self.in_paste else 0.03
        if self.pending and time.monotonic() - self.updated >= timeout:
            self.flush()


def copy_files(destination, sources):
    destination = Path(destination).resolve(strict=True)
    if not destination.is_dir():
        raise ValueError("Выбранная папка больше не существует")
    copied = []
    for name in sources:
        source = Path(name)
        if not source.is_absolute() or not os.path.lexists(source):
            raise ValueError(f"Исходный файл больше не существует: {name}")
        if source.is_dir() and not source.is_symlink():
            resolved = source.resolve()
            if destination == resolved or resolved in destination.parents:
                raise ValueError(f"Нельзя копировать папку внутрь неё самой: {source.name}")
        elif not (source.is_file() or source.is_symlink()):
            raise ValueError(f"Этот тип файла не поддерживается: {source.name}")
        with tempfile.TemporaryDirectory(prefix=".broot-import-", dir=destination) as staging:
            temporary = Path(staging) / source.name
            if source.is_symlink():
                temporary.symlink_to(os.readlink(source))
            elif source.is_dir():
                shutil.copytree(source, temporary, symlinks=True)
            else:
                shutil.copy2(source, temporary)
            index = 0
            while True:
                if index == 0:
                    filename = source.name
                else:
                    stem, suffix = (source.name, "") if source.is_dir() else (source.stem, source.suffix)
                    filename = f"{stem} copy{'' if index == 1 else ' ' + str(index)}{suffix}"
                target = destination / filename
                try:
                    publish_exclusive(temporary, target)
                    copied.append(str(target))
                    break
                except OSError as error:
                    if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                        raise
                    index += 1
    return copied


def copy_manifest(destination, manifest):
    path = Path(manifest)
    try:
        sources = json.loads(path.read_text())
        if not isinstance(sources, list) or not all(isinstance(p, str) for p in sources):
            raise ValueError("Некорректный список файлов")
        copy_files(destination, sources)
        return 0
    except (OSError, ValueError, shutil.Error) as error:
        message = f"Не удалось завершить копирование: {error}"
        print(message, file=sys.stderr)
        subprocess.run(
            ["/usr/bin/osascript", "-e", "on run argv\ndisplay alert \"Broot\" message (item 1 of argv) buttons {\"OK\"}\nend run", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return 1
    finally:
        path.unlink(missing_ok=True)


def write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def real_broot():
    custom = Path.home() / '.local/opt/broot-folders/1.61.0/bin/broot'
    # Keep the tested tree features after a Homebrew update. The official app
    # remains available explicitly, instead of silently losing our features.
    if os.environ.get('BROOT_OFFICIAL') != '1' and custom.is_file():
        return str(custom)
    for candidate in ("/opt/homebrew/bin/broot", "/usr/local/bin/broot"):
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError("Не найден Broot, установленный через Homebrew")


def tmux_marker(active):
    pane = os.environ.get("TMUX_PANE")
    binary = shutil.which("tmux")
    if not (os.environ.get("TMUX") and pane and binary):
        return
    args = ["set-option", "-p", "-t", pane, "@broot_file_import", "1"] if active else [
        "set-option", "-pu", "-t", pane, "@broot_file_import"]
    try:
        subprocess.run([binary, *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


def launch(arguments):
    binary = real_broot()
    os.environ.setdefault('BROOT_HIDE_SCROLLBAR', '1')
    os.environ.setdefault('BROOT_SHORTCUT_HINTS', '1')
    bypass = {"--help", "--version", "--conf", "--listen", "--listen-auto", "--send",
              "--get-root", "--install", "--set-install-state", "--print-shell-function",
              "--write-default-conf", "--outcmd", "--verb-output"}
    config = Path.home() / ".config/broot/conf.hjson"
    if (not sys.stdin.isatty() or not sys.stdout.isatty() or not config.exists()
            or any(arg.split("=", 1)[0] in bypass for arg in arguments)):
        os.execv(binary, [binary, *arguments])
    if 'broot-folders' in Path(binary).parts:
        os.environ.setdefault('BROOT_CLICK_FOLDERS', '1')
    command_modifier_down()  # load CoreGraphics before the first shortcut
    with tempfile.TemporaryDirectory(prefix="broot-import-", dir="/tmp") as session_dir:
        session = Path(session_dir)
        socket_name = "file-import-" + session.name
        extra_config = session / "verbs.hjson"
        action_script = str(Path(actions.__file__).resolve())
        selection_manifest = str(session / 'selected-paths.json')
        extra_config.write_text(json.dumps({"auto_open_staging_area": False,
            **({'show_selection_mark': False} if os.environ.get('BROOT_CLICK_FOLDERS') == '1' else {}),
            "verbs": [{
            "name": "import_files",
            "invocation": "import_files {manifest}",
            "shortcut": "bimport",
            "external": ["/usr/bin/python3", str(Path(__file__).resolve()), "--copy", "{directory}", "{manifest}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "trash_selection",
            "invocation": "trash_selection",
            "shortcut": "btrash",
            "external": ["/usr/bin/python3", str(Path(__file__).resolve()), "--trash", "{file}", "{root}", str(session / 'last-trash.json')],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "new_file", "invocation": "newfile {name}", "shortcut": "nf",
            "external": ["/usr/bin/python3", action_script, "new-file", "{directory}", "{name}"],
            "auto_exec": False, "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "new_folder", "invocation": "newfolder {name}", "shortcut": "nd",
            "external": ["/usr/bin/python3", action_script, "new-folder", "{directory}", "{name}"],
            "auto_exec": False, "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "prompt_new_file", "invocation": "newfiledialog", "key": "F3",
            "external": ["/usr/bin/python3", action_script, "prompt-file", "{directory}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "prompt_new_folder", "invocation": "newfolderdialog", "key": "shift-F3",
            "external": ["/usr/bin/python3", action_script, "prompt-folder", "{directory}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "reveal_in_finder", "invocation": "revealinfinder", "shortcut": "reveal", "key": "F14",
            "external": ["/usr/bin/python3", action_script, "reveal", "{file}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "copy_relative_path", "invocation": "relativepath", "shortcut": "rp", "key": "F4",
            "external": ["/usr/bin/python3", action_script, "copy-relative", "{file}", "{root}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "undo_delete", "invocation": "undodelete", "shortcut": "undo", "key": "F8",
            "external": ["/usr/bin/python3", action_script, "undo-delete", "{root}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "show_git_diff", "invocation": "gitdiff", "shortcut": "diff", "key": "F6",
            "cmd": ":open_preview;:preview_diff", "apply_to": "file", "panels": ["tree"],
        }, {
            "name": "remember_multiselection", "invocation": "rememberselection", "shortcut": "bselect",
            "external": ["/usr/bin/python3", action_script, "toggle-selection", selection_manifest, "{file}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree"],
        }, {
            "name": "command_click_selection", "invocation": "commandclick", "key": "F13",
            "cmd": ":bselect;:toggle_stage", "panels": ["tree"],
        }, {
            "key": "ctrl-g", "cmd": ":bselect;:toggle_stage", "panels": ["tree"],
        }, {
            "name": "copy_selected_paths", "invocation": "copypaths", "shortcut": "bcopypaths",
            "external": ["/usr/bin/python3", action_script, "copy-selected", selection_manifest, "{file:space-separated}"],
            "leave_broot": False, "switch_terminal": False, "panels": ["tree", "stage"],
        }, {
            "name": "reset_selection_manifest", "invocation": "resetselectionmanifest", "shortcut": "bclear",
            "external": ["/usr/bin/python3", action_script, "clear-selection", selection_manifest],
            "leave_broot": False, "switch_terminal": False,
        }, {
            "name": "clear_multiselection", "invocation": "clearselection", "shortcut": "cls",
            "cmd": ":bclear;:clear_stage", "panels": ["tree"],
        }, {"key": "ctrl-c", "internal": ":quit"}]}))
        # Start the native watcher once, preserving any user startup command.
        arguments = list(arguments)
        separator = os.environ.get('BROOT_CMD_SEPARATOR', ';')
        for index, argument in enumerate(arguments):
            if argument in ('--cmd', '-c') and index + 1 < len(arguments):
                arguments[index + 1] = ':watch' + separator + arguments[index + 1]
                break
            if argument.startswith('--cmd='):
                arguments[index] = '--cmd=:watch' + separator + argument.split('=', 1)[1]
                break
        else:
            arguments.extend(['--cmd', ':watch'])
        saved_terminal = termios.tcgetattr(sys.stdin.fileno())
        pid, master = pty.fork()
        if pid == 0:
            os.execv(binary, [binary, "--conf", f"{config};{extra_config}",
                             "--listen", socket_name, *arguments])

        def resize(*_):
            try:
                size = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
                fcntl.ioctl(master, termios.TIOCSWINSZ, size)
            except OSError:
                pass

        # Drain the child's output while forwarding a trackpad burst. A blocking
        # write to its PTY can otherwise deadlock against a full output buffer.
        os.set_blocking(master, False)
        pending_input = bytearray()
        def send_input(data):
            pending_input.extend(data)

        def import_paste(payload):
            # An external editor/shell must receive its paste unchanged.
            children = subprocess.run(["/usr/bin/pgrep", "-P", str(pid)], capture_output=True)
            if children.returncode != 1:
                return False
            def text_input():
                # Broot doesn't consume paste events. Give its single-line
                # input printable text; never turn pasted newlines into Enter.
                text = payload.decode("utf-8", errors="replace")
                safe = "".join(" " if c in "\r\n\t" else c for c in text
                               if c.isprintable() or c in "\r\n\t")
                send_input(safe.encode("utf-8"))
                return True
            paths = pasted_paths(payload)
            if paths is None:
                return text_input()
            # Ghostty already supplies the file paths in the paste frame.
            # Finder's drag pasteboard may be empty, delayed, or replaced by a
            # screenshot. Never turn a valid file paste into Broot search input.
            fd, manifest = tempfile.mkstemp(prefix="files-", suffix=".json", dir=session)
            with os.fdopen(fd, "w") as stream:
                json.dump(paths, stream)
            try:
                result = subprocess.run(
                    [binary, "--send", socket_name, "--cmd", f":bimport {manifest}"],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
            Path(manifest).unlink(missing_ok=True)
            subprocess.run(
                ['/usr/bin/osascript', '-e',
                 'display alert "Broot" message "Не удалось передать файлы в выбранную папку. Повторите вставку." buttons {"OK"}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True  # A failed file import must never become a search query.

        def forward_input(data):
            action = shortcut_command(data)
            if data in (b'\x1b', b'\x1b[27u', b'\x1b[27;1u', b'\x1b[27;1:1u'):
                try:
                    if json.loads(Path(selection_manifest).read_text()):
                        action = ':bclear;:clear_stage'
                except (OSError, ValueError):
                    pass
            if action:
                children = subprocess.run(["/usr/bin/pgrep", "-P", str(pid)], capture_output=True)
                if children.returncode == 1:
                    try:
                        result = subprocess.run(
                            [binary, "--send", socket_name, "--cmd", action],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=2,
                        )
                        if result.returncode == 0:
                            return
                    except (OSError, subprocess.SubprocessError):
                        pass
            send_input(data)

        mouse_parser = CommandClickStream(forward_input)
        parser = PasteStream(mouse_parser.feed, import_paste)
        hotkey = None
        helper = Path(__file__).with_name('broot-copy-hotkey')
        if os.environ.get('TMUX') and os.environ.get('TMUX_PANE') and helper.exists():
            hotkey = subprocess.Popen([str(helper), shutil.which('tmux') or '/opt/homebrew/bin/tmux',
                                       str(session / 'hotkey-status.txt')],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        old_resize = signal.signal(signal.SIGWINCH, resize)
        def terminate(signum, _frame):
            raise SystemExit(128 + signum)
        old_signals = {sig: signal.signal(sig, terminate) for sig in (signal.SIGHUP, signal.SIGTERM)}
        resize()
        status = None
        try:
            tmux_marker(True)
            tty.setraw(sys.stdin.fileno())
            # Ghostty frames both Finder drops and Cmd+V this way. Broot's
            # proxy consumes these frames before they reach Broot's event reader.
            write_all(sys.stdout.fileno(), b"\x1b[?2004h")
            output_tail = b""
            selection_style = SelectionMarkStyle()
            hotkey_pending = b""
            while True:
                readers = [master]
                if len(pending_input) < 256 * 1024:
                    readers.append(sys.stdin.fileno())
                if hotkey and hotkey.poll() is None:
                    readers.append(hotkey.stdout.fileno())
                ready, writable, _ = select.select(readers, [master] if pending_input else [], [], 0.03)
                if writable:
                    try:
                        written = os.write(master, pending_input[:16384])
                        del pending_input[:written]
                    except BlockingIOError:
                        pass
                if hotkey and hotkey.stdout.fileno() in ready:
                    hotkey_pending += os.read(hotkey.stdout.fileno(), 1024)
                    while b'\n' in hotkey_pending:
                        request, hotkey_pending = hotkey_pending.split(b'\n', 1)
                        action = {b'copy': ':bcopypaths', b'reveal': ':reveal'}.get(request.strip())
                        if not action:
                            continue
                        active = subprocess.run(['tmux', 'display-message', '-p', '#{pane_id}'],
                                                capture_output=True, text=True, timeout=2)
                        children = subprocess.run(['/usr/bin/pgrep', '-P', str(pid)], capture_output=True)
                        if active.stdout.strip() == os.environ.get('TMUX_PANE') and children.returncode == 1:
                            subprocess.run([binary, '--send', socket_name, '--cmd', action],
                                           stdin=subprocess.DEVNULL, capture_output=True, timeout=2)
                if master in ready:
                    try:
                        output = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not output:
                        break
                    write_all(sys.stdout.fileno(), selection_style.feed(output))
                    if b"\x1b[?1049h" in output_tail + output:
                        write_all(sys.stdout.fileno(), b"\x1b[?2004h")
                    output_tail = output[-7:]
                if sys.stdin.fileno() in ready:
                    data = os.read(sys.stdin.fileno(), 65536)
                    if not data:
                        break
                    parser.feed(data)
                parser.expire()
                mouse_parser.expire()
        finally:
            if hotkey:
                hotkey.terminate()
                hotkey.wait(timeout=2)
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_terminal)
            write_all(sys.stdout.fileno(), b"\x1b[?2004l")
            signal.signal(signal.SIGWINCH, old_resize)
            for sig, handler in old_signals.items():
                signal.signal(sig, handler)
            tmux_marker(False)
            os.close(master)
            _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--copy"]:
        sys.exit(copy_manifest(*sys.argv[2:]))
    if sys.argv[1:2] == ["--trash"]:
        sys.exit(trash_selected(*sys.argv[2:]))
    sys.exit(launch(sys.argv[1:]))
