import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import sync as syncer


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.remote = self.base / 'remote.git'
        self.home = self.base / 'home'
        self.home.mkdir()
        self.command('git', 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.command('git', 'init', '--initial-branch=main', str(self.repo))
        self.command('git', '-C', str(self.repo), 'config', 'user.name', 'Test')
        self.command('git', '-C', str(self.repo), 'config', 'user.email', 'test@example.invalid')
        self.command('git', '-C', str(self.repo), 'remote', 'add', 'origin', str(self.remote))
        (self.repo / 'files.txt').write_text('.zshrc\n')
        (self.repo / 'packages').mkdir()
        (self.home / '.zshrc').write_text('export EDITOR=nvim\n')
        for obj, attr, value in [(syncer, 'ROOT', self.repo), (syncer, 'HOME', self.home),
                                  (syncer.core, 'ROOT', self.repo), (syncer.core, 'HOME', self.home)]:
            patcher = patch.object(obj, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(syncer, 'inventory', return_value={'pacman': 'zsh\n', 'aur': ''})
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, *args):
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout

    def test_save_push_and_apply_on_other_machine(self):
        syncer.save()
        remote_file = self.command('git', '--git-dir', str(self.remote), 'show', 'main:dotfiles/files/.zshrc')
        self.assertEqual(remote_file, 'export EDITOR=nvim\n')
        other = self.base / 'desktop-repo'
        self.command('git', 'clone', str(self.remote), str(other))
        desktop = self.base / 'desktop-home'
        desktop.mkdir()
        (desktop / '.zshrc').write_text('previous')
        with patch.object(syncer, 'ROOT', other), patch.object(syncer, 'HOME', desktop), \
             patch.object(syncer.core, 'HOME', desktop), \
             patch.object(syncer, 'install_packages') as install, patch.object(syncer, 'shell_tools'):
            syncer.apply_local()
            install.assert_called_once_with(False)
        self.assertEqual((desktop / '.zshrc').read_text(), remote_file)
        self.assertEqual(next((desktop / '.backup-rollback').glob('*/files/.zshrc')).read_text(), 'previous')
        self.assertEqual(self.command('git', '-C', str(self.repo), 'status', '--porcelain'), '')

    def test_second_save_without_changes_needs_no_commit(self):
        syncer.save()
        before = self.command('git', '-C', str(self.repo), 'rev-parse', 'HEAD')
        syncer.save()
        self.assertEqual(self.command('git', '-C', str(self.repo), 'rev-parse', 'HEAD'), before)

    def test_missing_config_preserves_shared_version(self):
        syncer.save()
        (self.home / '.zshrc').unlink()
        syncer.save()
        self.assertTrue((self.repo / 'dotfiles/files/.zshrc').is_file())

    def test_secret_blocks_commit_and_push(self):
        (self.home / '.zshrc').write_text('export API_KEY="' + 'x' * 30 + '"\n')
        with self.assertRaises(ValueError):
            syncer.save()
        self.assertFalse((self.repo / 'dotfiles').exists())

    def test_dry_run_does_not_write(self):
        syncer.save(True)
        self.assertFalse((self.repo / 'dotfiles').exists())
        self.assertFalse((self.repo / '.git/index').exists())

    def test_restoration_keeps_recoverable_copy_of_existing_link(self):
        syncer.save()
        actual = self.home / 'actual-zshrc'
        actual.write_text('old linked config')
        (self.home / '.zshrc').unlink()
        (self.home / '.zshrc').symlink_to(actual)
        with patch.object(syncer, 'install_packages'), patch.object(syncer, 'shell_tools'):
            syncer.apply_local()
        rollback = next((self.home / '.backup-rollback').iterdir())
        self.assertTrue((rollback / 'originals/.zshrc').is_symlink())
        self.assertEqual((rollback / 'files/.zshrc').read_text(), 'old linked config')
        args = type('Args', (), dict(snapshot=rollback, dry_run=False))()
        syncer.core.restore(args)
        self.assertEqual((self.home / '.zshrc').read_text(), 'old linked config')
        self.assertEqual(actual.read_text(), 'old linked config')

    def test_no_package_removal(self):
        syncer.save()
        result = subprocess.CompletedProcess(['pacman'], 0, stdout='zsh\nextra\n')
        with patch.object(syncer.subprocess, 'run', return_value=result), \
             patch.object(syncer.shutil, 'which', return_value='/usr/bin/tool'), \
             patch.object(syncer.core, 'run') as runner:
            syncer.install_packages()
        runner.assert_not_called()
