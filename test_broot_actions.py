import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import broot_actions as actions


class FileActionsTests(unittest.TestCase):
    def test_multiselection_paths_toggle_and_copy_as_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / 'один файл.txt'
            second = root / 'two.txt'
            first.touch()
            second.touch()
            manifest = root / 'selection.json'
            self.assertEqual(actions.selected_paths(manifest, [str(first)]), [str(first)])
            actions.toggle_selection(manifest, first)
            actions.toggle_selection(manifest, second)
            with patch.object(actions.subprocess, 'run') as copy:
                text = actions.copy_selected_paths(manifest, [str(second)])
                self.assertEqual(text, f'{first}\n{second}')
                self.assertEqual(copy.call_args.kwargs['input'], text.encode())
            self.assertEqual(actions.toggle_selection(manifest, first), [str(second)])
            second.unlink()
            self.assertEqual(actions.selected_paths(manifest, [str(first)]), [])

    def test_creation_never_overwrites_or_escapes_selected_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = actions.create_entry(root, 'nested/Файл with spaces.txt')
            file.write_text('keep')
            with self.assertRaises(FileExistsError):
                actions.create_entry(root, 'nested/Файл with spaces.txt')
            self.assertEqual(file.read_text(), 'keep')
            folder = actions.create_entry(root, 'new/folder', is_directory=True)
            self.assertTrue(folder.is_dir())
            with self.assertRaises(ValueError):
                actions.create_entry(root, '../outside.txt')
            (root / 'escape').symlink_to(root.parent)
            with self.assertRaises(ValueError):
                actions.create_entry(root, 'escape/outside.txt')

    def test_relative_paths_use_git_root_even_inside_a_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            folder = root / 'services/map'
            folder.mkdir(parents=True)
            file = folder / 'go.mod'
            file.touch()
            self.assertEqual(actions.relative_file_path(file, folder), 'services/map/go.mod')

    def test_trash_undo_survives_a_new_process_and_does_not_overwrite(self):
        spec = importlib.util.spec_from_file_location('broot_import', Path(__file__).with_name('broot-file-import.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='broot-undo-test-') as tmp:
            base = Path(tmp)
            root = base / 'project'
            root.mkdir()
            source = root / (base.name + '-recover.txt')
            source.write_text('original')
            with patch.dict(os.environ, {'XDG_STATE_HOME': str(base / 'state')}):
                destination = actions.remember_trash(source, root, module.trash_file)
                try:
                    source.write_text('new file at the same path')
                    with self.assertRaises(FileExistsError):
                        actions.undo_delete(root)
                    self.assertEqual(source.read_text(), 'new file at the same path')
                    source.unlink()
                    subprocess.run(['/usr/bin/python3', str(Path(actions.__file__)), 'undo-delete', str(root)],
                                   check=True, capture_output=True)
                    self.assertEqual(source.read_text(), 'original')
                    self.assertFalse(destination.exists())
                    self.assertIsNone(actions.undo_delete(root))
                finally:
                    if destination.exists() and not source.exists():
                        os.rename(destination, source)


if __name__ == '__main__':
    unittest.main()
