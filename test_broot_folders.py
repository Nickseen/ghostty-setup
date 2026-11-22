"""Exercise the custom tree through actual Broot mouse input in a private tmux."""
import os
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest


BINARY = Path(__file__).parent / '.build/broot-folders-src/target/release/broot'


class FolderMouseTests(unittest.TestCase):
    def test_folder_clicks_preserve_command_selection_and_copy(self):
        with tempfile.TemporaryDirectory(prefix='broot-fold-wrapper-') as tmp:
            base = Path(tmp).resolve()
            root = base / 'tree'
            folder = root / 'folder'
            folder.mkdir(parents=True)
            child, sibling = folder / 'child.txt', root / 'sibling.txt'
            child.write_text('child')
            sibling.write_text('sibling')
            modifier = base / 'command-down'
            clipboard = base / 'clipboard.txt'
            actions = base / 'actions-fixture.py'
            workspace = str(Path(__file__).parent.resolve())
            actions.write_text('import sys\nfrom pathlib import Path\n'
                               f'sys.path.insert(0, {workspace!r})\n'
                               'import broot_actions as actions\noriginal_run=actions.subprocess.run\n'
                               'def run(args, **kwargs):\n'
                               "    if args == ['/usr/bin/pbcopy']:\n"
                               f"        Path({str(clipboard)!r}).write_bytes(kwargs['input'])\n"
                               '        return actions.subprocess.CompletedProcess(args, 0)\n'
                               '    return original_run(args, **kwargs)\n'
                               'actions.subprocess.run=run\n'
                               'sys.exit(actions.main(sys.argv[1:]))\n')
            bootstrap = base / 'launch.py'
            bootstrap.write_text('import os,sys,importlib.util\nfrom pathlib import Path\n'
                                 f'sys.path.insert(0, {workspace!r})\n'
                                 f'spec=importlib.util.spec_from_file_location("proxy", {workspace + "/broot-file-import.py"!r})\n'
                                 'proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)\n'
                                 f'proxy.real_broot=lambda: {str(BINARY.resolve())!r}\n'
                                 f'proxy.command_modifier_down=lambda: Path({str(modifier)!r}).exists()\n'
                                 f'proxy.actions.__file__={str(actions)!r}\n'
                                 'os.environ["BROOT_CLICK_FOLDERS"]="1"\n'
                                 f'sys.exit(proxy.launch([{str(root)!r}]))\n')
            tmux = ['/opt/homebrew/bin/tmux', '-L', 'fold-wrapper-' + str(os.getpid()), '-f', '/dev/null']
            def run(*args):
                return subprocess.run(tmux + list(args), check=True, capture_output=True, text=True)
            def screen():
                return run('capture-pane', '-p', '-t', 'check:0.0').stdout
            def wait_for(predicate):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(.04)
                self.fail('Wrapper expectation timed out\n' + screen())
            def click(name, arrow=False):
                row, line = next((i, line) for i, line in enumerate(screen().splitlines()) if i and name in line)
                column = next(i for i, c in enumerate(line) if c in '▸▾') if arrow else line.index(name) + 1
                run('send-keys', '-l', '-t', 'check:0.0',
                    f'\x1b[<0;{column+1};{row+1}M\x1b[<0;{column+1};{row+1}m')
                time.sleep(.2)
            try:
                run('new-session', '-d', '-s', 'check', '-x', '125', '-y', '32',
                    shlex.join(['env', '-u', 'NO_COLOR', 'COLORTERM=truecolor', '/usr/bin/python3', str(bootstrap)]))
                wait_for(lambda: 'folder' in screen() and '▸' in screen())
                self.assertNotIn('child.txt', screen())
                click('folder', arrow=True)
                wait_for(lambda: 'child.txt' in screen())
                modifier.touch()
                click('child.txt')
                wait_for(lambda: '◍' in screen())
                self.assertNotIn('Staging Area', screen())
                sessions = [p.parent for p in Path('/tmp').glob('broot-import-*/verbs.hjson')
                            if str(actions) in p.read_text()]
                self.assertEqual(len(sessions), 1)
                session = sessions[0]
                manifest = session / 'selected-paths.json'
                click('sibling.txt')
                wait_for(lambda: manifest.exists() and len(json.loads(manifest.read_text())) == 2)
                listen = 'file-import-' + session.name
                result = subprocess.run([str(BINARY), '--send', listen, '--cmd', ':bcopypaths'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                wait_for(clipboard.exists)
                self.assertEqual(clipboard.read_text().splitlines(), [str(child), str(sibling)])
                modifier.unlink()
                run('send-keys', '-t', 'check:0.0', 'Escape')
                wait_for(lambda: manifest.read_text() == '[]')
                self.assertIn('child.txt', screen(), 'Clearing selection changed the folder state')
                self.assertNotIn('◍', screen())
            finally:
                subprocess.run(tmux + ['kill-server'], capture_output=True)

    def test_native_disclosures_search_refresh_and_scroll(self):
        with tempfile.TemporaryDirectory(prefix='broot-folders-check-') as tmp:
            base = Path(tmp).resolve()
            root = base / 'project'
            a, b, z = root / 'a Папка with spaces', root / 'b-folder', root / 'z-folder'
            nested = a / 'nested'
            nested.mkdir(parents=True)
            b.mkdir()
            z.mkdir()
            (a / 'inside_a.txt').write_text('A')
            (nested / 'needle_nested.go').write_text('package main\n')
            (b / 'inside_b.txt').write_text('B')
            (z / 'inside_z.txt').write_text('Z')
            for index in range(40):
                (root / f'middle-{index:02}.txt').write_text('scroll fixture')
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            socket = 'broot-fold-check-' + str(os.getpid())
            listen = 'fold-native-' + str(os.getpid())
            tmux = ['/opt/homebrew/bin/tmux', '-L', socket, '-f', '/dev/null']
            def run(*args):
                return subprocess.run(tmux + list(args), check=True, capture_output=True, text=True)
            def screen(colored=False):
                return run('capture-pane', '-p' + ('e' if colored else ''), '-t', 'check:0.0').stdout
            def wait_for(predicate, description):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    text = screen()
                    if predicate(text):
                        return text
                    time.sleep(.04)
                self.fail(description + '\n' + screen())
            def command(text):
                result = subprocess.run([str(BINARY), '--send', listen, '--cmd', text],
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr + '\n' + screen())
                time.sleep(.12)
            def click(name, disclosure=True):
                text = wait_for(lambda text: any(name in line for line in text.splitlines()[1:]),
                                'Target not visible: ' + name)
                row, line = next((i, line) for i, line in enumerate(text.splitlines()) if i and name in line)
                if disclosure:
                    column = next(i for i, char in enumerate(line) if char in '▸▾')
                else:
                    column = line.index(name) + 1
                data = f'\x1b[<0;{column+1};{row+1}M\x1b[<0;{column+1};{row+1}m'
                run('send-keys', '-l', '-t', 'check:0.0', data)
                time.sleep(.12)
            try:
                launch = shlex.join(['env', '-u', 'NO_COLOR', 'COLORTERM=truecolor',
                                     'BROOT_CLICK_FOLDERS=1', 'BROOT_HIDE_SCROLLBAR=1', str(BINARY), '--listen', listen,
                                     '--conf', str(Path.home() / '.config/broot/conf.hjson'),
                                     '--cmd', ':watch', str(root)])
                run('new-session', '-d', '-s', 'check', '-x', '125', '-y', '32', launch)
                text = wait_for(lambda text: 'a Папка with spaces' in text, 'Broot did not start')
                self.assertNotIn('inside_a.txt', text)
                self.assertNotIn('needle_nested.go', text)
                self.assertNotIn('inside_b.txt', text)
                self.assertIn('▸', text)
                self.assertIn('38;2;96;165;250', screen(True))
                self.assertNotIn('▐', screen(), 'The tree scrollbar is still drawn')
                run('resize-window', '-t', 'check:0', '-x', '95')
                time.sleep(.15)
                self.assertNotIn('▐', screen(), 'Resizing brought back the scrollbar')

                click(a.name, disclosure=False)
                self.assertNotIn('inside_a.txt', screen(), 'Clicking the name should only select')
                click(a.name)
                wait_for(lambda text: 'inside_a.txt' in text and 'nested' in text, 'A did not expand')
                self.assertNotIn('needle_nested.go', screen())
                self.assertNotIn('inside_b.txt', screen())
                click('nested')
                wait_for(lambda text: 'needle_nested.go' in text, 'Nested folder did not expand')
                click(a.name)
                wait_for(lambda text: 'inside_a.txt' not in text and 'needle_nested.go' not in text,
                         'A did not collapse')
                click(a.name)
                wait_for(lambda text: 'needle_nested.go' in text, 'Child expansion state was lost')
                click(b.name)
                wait_for(lambda text: 'inside_b.txt' in text, 'B did not expand independently')
                click(a.name)
                wait_for(lambda text: 'inside_a.txt' not in text and 'inside_b.txt' in text,
                         'Collapsing A affected B')

                time.sleep(.4)  # Let Broot re-arm its native watcher after the mouse redraw.
                (b / 'created_from_outside.txt').write_text('watch fixture')
                wait_for(lambda text: 'created_from_outside.txt' in text, 'Watcher lost expansion state')
                command(':refresh')
                self.assertIn('inside_b.txt', screen())
                self.assertNotIn('inside_a.txt', screen())
                current_root = subprocess.check_output([str(BINARY), '--send', listen, '--get-root'], text=True).strip()
                self.assertEqual(current_root, str(root), 'Click changed the root')

                command(':select ' + str(z))
                click(z.name)
                wait_for(lambda text: 'inside_z.txt' in text, 'Triangle hit detection failed after scrolling')

                command(':mode_input')
                run('send-keys', '-l', '-t', 'check:0.0', 'needle_nested')
                wait_for(lambda text: 'needle_nested.go' in text, 'Search failed inside a closed folder')
                click(a.name)
                wait_for(lambda text: a.name in text and 'needle_nested.go' not in text,
                         'Collapsing a search ancestor lost the parent row')
                click(a.name)
                wait_for(lambda text: 'needle_nested.go' in text, 'Search ancestor could not be reopened')
                run('send-keys', '-t', 'check:0.0', 'Escape')
                time.sleep(.12)  # Native modal mode: leave input, then clear the filter.
                run('send-keys', '-t', 'check:0.0', 'Escape')
                wait_for(lambda text: 'middle-' in text, 'Escape did not restore the base tree')
                command(':select_first')
                self.assertNotIn('inside_a.txt', screen(), 'Search changed the normal expansion state')
            finally:
                subprocess.run(tmux + ['kill-server'], capture_output=True)


if __name__ == '__main__':
    unittest.main()
