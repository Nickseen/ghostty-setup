"""File actions used by the personal Broot configuration."""

from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CREATE_DIALOG_SCRIPT = '''on run argv
set answer to display dialog ("Имя в папке «" & item 2 of argv & "»:") default answer "" with title (item 1 of argv) buttons {"Отмена", "Создать"} default button "Создать" cancel button "Отмена"
return text returned of answer
end run'''


def project_directory(root):
    root = Path(root).resolve(strict=True)
    result = subprocess.run(
        ['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else root


def relative_file_path(filename, root):
    source = Path(os.path.abspath(filename))
    view_root = Path(os.path.abspath(root))
    try:
        # Normalize macOS /var aliases without resolving a selected symlink.
        source = view_root.resolve() / source.relative_to(view_root)
    except ValueError:
        source = source.parent.resolve() / source.name
    return os.path.relpath(source, project_directory(root))


def create_entry(directory, name, is_directory=False):
    base = Path(directory).resolve(strict=True)
    if not name.strip() or Path(name).is_absolute():
        raise ValueError('Укажи имя внутри выбранной папки')
    target = base / name
    resolved = target.resolve()
    if resolved == base or base not in resolved.parents:
        raise ValueError('Новый файл или папка должны находиться внутри выбранной папки')
    if is_directory:
        target.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x'):
            pass
    return target


def publish_exclusive(source, target):
    """Atomically move an item without replacing an existing name on macOS."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(source), os.fsencode(target), 4):  # RENAME_EXCL
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


@contextmanager
def locked_history(root):
    project = project_directory(root)
    state_home = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    folder = state_home / 'broot/trash-history'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(os.fsencode(project)).hexdigest()[:24]
    path = folder / (key + '.json')
    lock_fd = os.open(folder / (key + '.lock'), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(lock_fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            records = json.loads(path.read_text())
        except FileNotFoundError:
            records = []
        if not isinstance(records, list) or not all(
            isinstance(record, dict) and isinstance(record.get('source'), str)
            and isinstance(record.get('trashed'), str) for record in records
        ):
            raise ValueError('История Корзины повреждена; файлы не изменены')
        yield path, records


def save_history(path, records):
    fd, temporary = tempfile.mkstemp(prefix='.history-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(records[-100:], stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def remember_trash(filename, root, move_to_trash):
    with locked_history(root) as (path, records):
        destination = move_to_trash(filename, root)
        if destination is not None:
            records.append({'source': os.path.abspath(filename), 'trashed': str(destination)})
            save_history(path, records)
        return destination


def undo_delete(root):
    with locked_history(root) as (path, records):
        while records and not os.path.lexists(records[-1]['trashed']):
            records.pop()
        if not records:
            save_history(path, records)
            return None
        record = records[-1]
        original = Path(record['source'])
        if os.path.lexists(original):
            raise FileExistsError(f'По этому пути уже есть файл. Он сохранён: {original}')
        if not original.parent.is_dir():
            raise FileNotFoundError(f'Папка для восстановления больше не существует: {original.parent}')
        publish_exclusive(record['trashed'], original)
        records.pop()
        save_history(path, records)
        return original


def adopt_trash_receipt(receipt, root):
    """Carry the previous wrapper's last deletion into persistent Undo."""
    source = Path(receipt['source'])
    trashed = Path(receipt['trashed'])
    project = project_directory(root)
    if os.path.lexists(source) or not os.path.lexists(trashed):
        return False
    if project not in source.parents:
        return False
    with locked_history(root) as (path, records):
        if receipt not in records:
            records.append(receipt)
            save_history(path, records)
    return True


def copy_relative_path(filename, root):
    value = relative_file_path(filename, root)
    subprocess.run(['/usr/bin/pbcopy'], input=value.encode(), check=True)
    return value


def reveal_in_finder(filename):
    path = os.path.abspath(filename)
    if not os.path.lexists(path):
        raise FileNotFoundError('Файл больше не существует: ' + path)
    subprocess.run(['/usr/bin/open', '-R', path], check=True)


def toggle_selection(manifest, filename):
    path = Path(manifest)
    selected = json.loads(path.read_text()) if path.exists() else []
    filename = os.path.abspath(filename)
    if filename in selected:
        selected.remove(filename)
    else:
        selected.append(filename)
    path.write_text(json.dumps(selected, ensure_ascii=False))
    return selected


def selected_paths(manifest, filenames):
    path = Path(manifest)
    selected = json.loads(path.read_text()) if path.exists() else []
    return [name for name in (selected or filenames) if os.path.lexists(name)]


def copy_selected_paths(manifest, filenames):
    value = '\n'.join(selected_paths(manifest, filenames))
    if value:
        subprocess.run(['/usr/bin/pbcopy'], input=value.encode(), check=True)
    return value


def prompt_create(directory, is_directory=False):
    title = 'Новая папка' if is_directory else 'Новый файл'
    result = subprocess.run(['/usr/bin/osascript', '-e', CREATE_DIALOG_SCRIPT, title, Path(directory).name],
                            capture_output=True, text=True)
    if result.returncode:
        if '(-128)' in result.stderr:  # standard macOS Cancel
            return None
        raise RuntimeError(result.stderr.strip())
    return create_entry(directory, result.stdout.rstrip('\n'), is_directory)


def main(arguments):
    try:
        action, *args = arguments
        if action == 'new-file':
            create_entry(*args)
        elif action == 'new-folder':
            create_entry(*args, is_directory=True)
        elif action == 'copy-relative':
            copy_relative_path(*args)
        elif action == 'reveal':
            reveal_in_finder(*args)
        elif action == 'toggle-selection':
            toggle_selection(*args)
        elif action == 'clear-selection':
            Path(args[0]).write_text('[]')
        elif action == 'copy-selected':
            copy_selected_paths(args[0], args[1:])
        elif action == 'prompt-file':
            prompt_create(*args)
        elif action == 'prompt-folder':
            prompt_create(*args, is_directory=True)
        elif action == 'undo-delete':
            undo_delete(*args)
        else:
            raise ValueError('Неизвестная команда Broot')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        subprocess.run(
            ['/usr/bin/osascript', '-e', 'on run argv\ndisplay alert "Broot" message (item 1 of argv) buttons {"OK"}\nend run', str(error)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
