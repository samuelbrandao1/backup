"""Testa arquivos em HOME temporário e Git local, sem instalar pacotes."""
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('backup_tool', str(Path(__file__).resolve().parents[1] / 'backup'))
spec = importlib.util.spec_from_loader(loader.name, loader)
backup = importlib.util.module_from_spec(spec)
loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repo'
        self.home = self.base / 'home'
        self.root.mkdir()
        self.home.mkdir()
        (self.root / 'files.txt').write_text('.zshrc\n.config/test\n')
        (self.root / 'packages').mkdir()
        (self.root / 'packages/pacman.txt').write_text('neovim\nzsh\n')
        (self.root / 'packages/aur.txt').write_text('')
        (self.root / 'dotfiles/.config/test').mkdir(parents=True)
        (self.root / 'dotfiles/.zshrc').write_text('shared')
        (self.root / 'dotfiles/.config/test/value').write_text('shared config')
        (self.home / '.zshrc').write_text('local')
        for name, value in [('ROOT', self.root), ('HOME', self.home)]:
            patcher = patch.object(backup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def command(self, *args):
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout

    def test_git_save_and_apply_on_other_machine(self):
        remote = self.base / 'remote.git'
        self.command('git', 'init', '--bare', '--initial-branch=main', str(remote))
        self.command('git', 'init', '--initial-branch=main', str(self.root))
        for key, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
            self.command('git', '-C', str(self.root), 'config', key, value)
        self.command('git', '-C', str(self.root), 'remote', 'add', 'origin', str(remote))
        backup.save()
        lists = (self.root / 'packages/pacman.txt').read_text()
        self.assertEqual(lists, 'neovim\nzsh\n')
        self.assertEqual(self.command('git', '--git-dir', str(remote), 'show', 'main:dotfiles/.zshrc'), 'local')
        clone = self.base / 'desktop-repo'
        self.command('git', 'clone', str(remote), str(clone))
        desktop = self.base / 'desktop-home'
        desktop.mkdir()
        with patch.object(backup, 'ROOT', clone), patch.object(backup, 'HOME', desktop), \
             patch.object(backup, 'prepare_zsh'), patch.object(backup, 'install_packages'):
            backup.apply()
        self.assertEqual((desktop / '.zshrc').read_text(), 'local')
        self.assertEqual((desktop / '.config/test/value').read_text(), 'shared config')
        backup.save()
        self.assertEqual(backup.git('rev-list', '--count', 'HEAD'), '1')

    def test_collect_link_content_and_keep_original(self):
        actual = self.home / 'dotfiles/zshrc'
        actual.parent.mkdir()
        actual.write_text('linked')
        (self.home / '.zshrc').unlink()
        (self.home / '.zshrc').symlink_to('dotfiles/zshrc')
        target = self.base / 'staged'
        backup.collect_configs(target)
        self.assertEqual((target / '.zshrc').read_text(), 'linked')
        self.assertFalse((target / '.zshrc').is_symlink())
        self.assertTrue((self.home / '.zshrc').is_symlink())
        self.assertEqual((target / '.config/test/value').read_text(), 'shared config')

    def test_link_cycle_and_private_targets_rejected(self):
        link = self.home / '.zshrc'
        link.unlink()
        (self.home / '.ssh').mkdir()
        (self.home / '.ssh/key').write_text('private')
        for destination in [link, self.home / 'missing', self.home / '.ssh/key', Path('/etc/passwd')]:
            with self.subTest(destination=destination):
                link.symlink_to(destination)
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    backup.collect_configs(self.base / 'staged')
                link.unlink()

    def test_linked_parent_outside_home_rejected(self):
        (self.home / '.config').symlink_to(self.root / 'dotfiles/.config')
        with self.assertRaises(ValueError):
            backup.apply_configs()
        self.assertEqual((self.home / '.zshrc').read_text(), 'local')

    def test_reject_unsafe_selection(self):
        for text in ['../escape', '/etc/passwd', '.', '.ssh/key']:
            with self.subTest(text=text):
                (self.root / 'files.txt').write_text(text)
                with self.assertRaises(ValueError):
                    backup.config_paths()

    def test_apply_preserves_original_link_and_its_target(self):
        actual = self.home / 'original'
        actual.write_text('original')
        (self.home / '.zshrc').unlink()
        (self.home / '.zshrc').symlink_to('original')
        backup.apply_configs()
        self.assertEqual((self.home / '.zshrc').read_text(), 'shared')
        self.assertEqual(actual.read_text(), 'original')
        previous = next((self.home / '.backup-rollback').glob('*/.zshrc'))
        self.assertTrue(previous.is_symlink())
        self.assertEqual(str(previous.readlink()), 'original')

    def test_failure_during_copy_restores_original_files(self):
        original_copy = backup.copy
        def fail_for_zsh(source, destination):
            if destination.name == '.zshrc':
                raise OSError('disk full')
            original_copy(source, destination)
        with patch.object(backup, 'copy', side_effect=fail_for_zsh):
            with self.assertRaises(OSError):
                backup.apply_configs()
        self.assertEqual((self.home / '.zshrc').read_text(), 'local')
        self.assertFalse((self.home / '.config/test').exists())

    def test_apply_dry_run_changes_nothing(self):
        backup.apply_configs(True)
        self.assertFalse((self.home / '.backup-rollback').exists())
        self.assertEqual((self.home / '.zshrc').read_text(), 'local')

    def test_secret_blocks_capture(self):
        (self.home / '.zshrc').write_text('export API_KEY="' + 'a' * 30 + '"')
        with self.assertRaises(ValueError):
            backup.collect_configs(self.base / 'staged')

    def test_provider_is_considered_installed(self):
        # pacman -T reports only unsatisfied names; neovim-git provides neovim.
        result = subprocess.CompletedProcess([], 127, stdout='zsh\n')
        with patch.object(backup, 'run', return_value=result) as run:
            self.assertEqual(backup.missing_packages('pacman.txt'), ['zsh'])
        run.assert_called_once_with('pacman', '-T', '--', 'neovim', 'zsh', capture=True, check=False)

    def test_failed_transaction_reports_failure_without_force_or_retry(self):
        result = subprocess.CompletedProcess([], 1)
        with patch.object(backup.shutil, 'which', return_value='/usr/bin/tool'), \
             patch.object(backup, 'missing_packages', side_effect=[['zsh'], []]), \
             patch.object(backup, 'run', return_value=result) as run:
            with self.assertRaisesRegex(ValueError, 'instalação falhou'):
                backup.install_packages()
        run.assert_called_once_with('sudo', 'pacman', '-Syu', '--needed', '--', 'zsh', check=False)

    def test_configs_apply_even_when_package_transaction_fails(self):
        with patch.object(backup, 'prepare_zsh'), \
             patch.object(backup, 'install_packages', side_effect=ValueError('conflict')):
            with self.assertRaises(ValueError):
                backup.apply()
        self.assertEqual((self.home / '.zshrc').read_text(), 'shared')

    def test_curated_list_excludes_machine_system_packages(self):
        project = Path(__file__).resolve().parents[1]
        packages = backup.read_list(project / 'packages/pacman.txt')
        for name in ['linux', 'limine', 'intel-ucode', 'vulkan-intel', 'hyprland', 'mariadb-libs']:
            self.assertNotIn(name, packages)
        self.assertNotIn('omarchy-walker', backup.read_list(project / 'packages/aur.txt'))
