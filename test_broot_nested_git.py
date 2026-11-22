"""Check Git badges from multiple repositories under a non-Git tree root."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

BINARY = Path(__file__).parent / '.build/broot-folders-src/target/release/broot'


class NestedGitTests(unittest.TestCase):
    def test_nested_repos_worktree_clean_boundaries_and_refresh(self):
        with tempfile.TemporaryDirectory(prefix='broot-nested-git-') as temporary:
            base = Path(temporary).resolve()
            root = base / 'workspace'
            root.mkdir()
            def git(repo, *args):
                return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                                       '-c', 'user.email=fixture@example.invalid',
                                       '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                                       *args], check=True, capture_output=True, text=True).stdout
            def repo(name, filename):
                directory = root / name
                directory.mkdir(parents=True)
                git(directory, 'init', '-q')
                (directory / filename).write_text('original\n')
                (directory / '.gitignore').write_text('ignored.tmp\n')
                git(directory, 'add', '.')
                git(directory, 'commit', '-qm', 'fixture')
                return directory
            first = repo('repo-a', 'modified_a.txt')
            (first / 'modified_a.txt').write_text('modified\n')
            second = repo('repo-b', 'clean_b.txt')
            (second / 'untracked_b.txt').write_text('new\n')
            clean = repo('repo-clean', 'clean_file.txt')
            (clean / 'ignored.tmp').write_text('ignored\n')
            nested = repo('repo-a/inner-clean', 'inner_clean.txt')
            worktree = root / 'repo-worktree'
            git(clean, 'worktree', 'add', '-qb', 'worktree-fixture', str(worktree))
            self.assertTrue((worktree / '.git').is_file())
            (worktree / 'clean_file.txt').write_text('worktree modification\n')
            (root / 'ordinary.txt').write_text('not under git\n')
            config = base / 'conf.hjson'
            config.write_text(json.dumps({'default_flags': 'g', 'modal': True,
                                         'initial_mode': 'command', 'show_selection_mark': False,
                                         'imports': [str(Path.home() / '.config/broot/skins/dark-blue.hjson')]}))
            tmux = ['/opt/homebrew/bin/tmux', '-L', 'nested-git-' + str(os.getpid()), '-f', '/dev/null']
            listen = 'nested-git-broot-' + str(os.getpid())
            def run(*args):
                return subprocess.run(tmux + list(args), check=True, capture_output=True, text=True).stdout
            def screen():
                return run('capture-pane', '-p', '-t', 'check:0.0')
            def wait_for(predicate):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    text = screen()
                    if predicate(text):
                        return text
                    time.sleep(.04)
                self.fail('Broot did not show expected Git badges\n' + screen())
            def line_for(text, name):
                return next(line for line in text.splitlines() if line.rstrip().endswith(name))
            def badge(text, name):
                line = line_for(text, name)
                return line[0] if line and line[0] in 'MUASRCI?' else None
            def click_arrow(name):
                text = screen()
                row, line = next((i, line) for i, line in enumerate(text.splitlines()) if line.rstrip().endswith(name))
                column = next(i for i, char in enumerate(line) if char in '▸▾')
                run('send-keys', '-t', 'check:0.0', '-l',
                    f'\x1b[<0;{column+1};{row+1}M\x1b[<0;{column+1};{row+1}m')
                time.sleep(.15)
            try:
                launch = shlex.join(['env', '-u', 'NO_COLOR', 'COLORTERM=truecolor',
                                     'BROOT_CLICK_FOLDERS=1', 'BROOT_HIDE_SCROLLBAR=1',
                                     str(BINARY), '--conf', str(config), '--listen', listen,
                                     '--cmd', ':watch', str(root)])
                run('new-session', '-d', '-s', 'check', '-x', '120', '-y', '35', launch)
                text = wait_for(lambda text: 'repo-worktree' in text and 'ordinary.txt' in text)
                self.assertEqual(badge(text, 'repo-a'), 'M', text)
                self.assertEqual(badge(text, 'repo-b'), 'U')
                self.assertEqual(badge(text, 'repo-worktree'), 'M')
                self.assertIsNone(badge(text, 'repo-clean'), 'Ignored files made a clean repository dirty')
                self.assertIsNone(badge(text, 'ordinary.txt'))
                for folder, filename in [('repo-a', 'modified_a.txt'), ('repo-b', 'untracked_b.txt'),
                                         ('repo-clean', 'clean_file.txt'), ('repo-worktree', 'clean_file.txt')]:
                    click_arrow(folder)
                    wait_for(lambda text: filename in text)
                text = screen()
                self.assertEqual(badge(text, 'modified_a.txt'), 'M')
                self.assertEqual(badge(text, 'untracked_b.txt'), 'U')
                self.assertIsNone(badge(text, 'clean_b.txt'))
                self.assertIsNone(badge(text, 'inner-clean'), 'A clean nested repo inherited parent untracked status')
                click_arrow('inner-clean')
                self.assertIsNone(badge(screen(), 'inner_clean.txt'))
                (first / 'modified_a.txt').write_text('original\n')
                subprocess.run([str(BINARY), '--send', listen, '--cmd', ':refresh'], check=True, capture_output=True)
                text = wait_for(lambda text: 'modified_a.txt' in text and badge(text, 'modified_a.txt') is None)
                self.assertEqual(badge(text, 'untracked_b.txt'), 'U')
                print('Verified closed repo badges, modified/untracked files, clean nested repo, .git worktree file and refresh')
            finally:
                subprocess.run(tmux + ['kill-server'], capture_output=True)


if __name__ == '__main__':
    unittest.main()
