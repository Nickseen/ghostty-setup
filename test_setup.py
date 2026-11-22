"""Portable install/rollback and upgrade regressions; never touch the user's home."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import setup
from setup_support import atomic_write, launcher_text


class SetupTests(unittest.TestCase):
    def test_different_home_and_idempotent_config_install_preserve_codex_settings(self):
        with tempfile.TemporaryDirectory(prefix='setup home ') as tmp:
            home = Path(tmp)
            config = home / '.codex/config.toml'
            config.parent.mkdir()
            config.write_text('model = "personal-model"\n[mcp_servers.personal]\ncommand = "keep-me"\n')
            original = config.read_text()
            setup.install_configs(home)
            first = {str(p): p.read_bytes() for p in setup.managed_paths(home) if p.is_file()}
            setup.install_configs(home)
            self.assertEqual(first, {str(p): p.read_bytes() for p in setup.managed_paths(home) if p.is_file()})
            self.assertEqual(config.read_text(), original)
            verbs = (home / '.config/broot/verbs.hjson').read_text()
            self.assertIn(str(home / '.config/broot/source-preview.py'), verbs)
            self.assertNotIn('@BROOT_HOME@', verbs)
            self.assertNotIn('/Users/', verbs)
            self.assertIn('shift+enter', (home / 'Library/Application Support/com.mitchellh.ghostty/config.ghostty').read_text())

    def test_launchers_keep_private_build_after_official_upgrade_and_allow_optout(self):
        with tempfile.TemporaryDirectory(prefix='launchers ') as tmp:
            root = Path(tmp)
            for name, optout in [('codex', 'CODEX_OFFICIAL'), ('tmux', 'TMUX_OFFICIAL')]:
                official, private, launcher = [root / (name + x) for x in ['-official', '-private', '-launcher']]
                atomic_write(official, '#!/bin/sh\nprintf "official-v2:%s" "$1"\n', 0o755)
                atomic_write(private, '#!/bin/sh\nfor arg do last="$arg"; done\nprintf "private:%s" "$last"\n', 0o755)
                atomic_write(launcher, launcher_text(name, official, private), 0o755)
                self.assertEqual(subprocess.check_output([launcher, 'hello world'], text=True), 'private:hello world')
                atomic_write(official, '#!/bin/sh\nprintf "official-v3:%s" "$1"\n', 0o755)
                self.assertEqual(subprocess.check_output([launcher, 'hello world'], text=True), 'private:hello world')
                env = dict(os.environ, **{optout: '1'})
                self.assertEqual(subprocess.check_output([launcher, 'arg'], text=True, env=env), 'official-v3:arg')

    def test_tmux_outside_uses_balanced_inside_preserves_current_server_and_explicit_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private, launcher = root / 'tmux', root / 'wrapper'
            atomic_write(private, '#!/bin/sh\nprintf "%s\\n" "$@"\n', 0o755)
            atomic_write(launcher, launcher_text('tmux', root / 'official', private), 0o755)
            env = {k: v for k, v in os.environ.items() if k not in ['TMUX', 'TMUX_SETUP_SOCKET', 'TMUX_OFFICIAL', 'TMUX_BALANCED']}
            def invoke(args, extra=None):
                return subprocess.check_output([launcher] + args, text=True, env=dict(env, **(extra or {}))).splitlines()
            self.assertEqual(invoke(['ls']), ['-L', 'balanced', 'ls'])
            self.assertEqual(invoke(['ls'], {'TMUX': '/tmp/old,1,0'}), ['ls'])
            self.assertEqual(invoke(['-L', 'test', 'ls']), ['-L', 'test', 'ls'])

    def test_backup_restores_existing_and_removes_only_new_managed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            original = home / '.tmux.conf'
            original.write_text('my old config\n')
            saved = setup.backup(home)
            setup.install_configs(home)
            unrelated = home / 'keep.txt'
            unrelated.write_text('untouched')
            with patch.object(Path, 'home', return_value=home):
                setup.restore(argparse.Namespace(backup=str(saved)))
            self.assertEqual(original.read_text(), 'my old config\n')
            self.assertFalse((home / '.local/bin/broot').exists())
            self.assertEqual(unrelated.read_text(), 'untouched')

    def test_broot_does_not_silently_lose_features_when_homebrew_updates(self):
        spec = importlib.util.spec_from_file_location('broot_proxy', setup.ROOT / 'broot-file-import.py')
        proxy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proxy)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            custom = home / '.local/opt/broot-folders/1.61.0/bin/broot'
            custom.parent.mkdir(parents=True)
            custom.touch()
            with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'BROOT_OFFICIAL': '0'}):
                self.assertEqual(proxy.real_broot(), str(custom))


if __name__ == '__main__':
    unittest.main()
