import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'lib/backup.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.original = b.HOME, b.ROOT
        self.addCleanup(self.reset)
        b.HOME = self.root / 'home'
        b.ROOT = self.root / 'repo'
        b.HOME.mkdir()
        (b.ROOT / 'profiles').mkdir(parents=True)
        (b.ROOT / 'profiles/common.txt').write_text('.zshrc\n.config/test\n')
        (b.HOME / '.zshrc').write_text('original')
        (b.HOME / '.config/test').mkdir(parents=True)
        (b.HOME / '.config/test/value').write_text('config')
        self.args = SimpleNamespace(profile='laptop', store=self.root / 'store', dry_run=False)

    def reset(self):
        b.HOME, b.ROOT = self.original

    def save(self):
        b.snapshot(self.args)
        return next(self.args.store.iterdir())

    def test_roundtrip_and_rollback(self):
        source = self.save()
        (b.HOME / '.zshrc').write_text('changed')
        (b.HOME / '.config/test/new').write_text('local')
        self.args.snapshot = source
        b.restore(self.args)
        self.assertEqual((b.HOME / '.zshrc').read_text(), 'original')
        self.assertFalse((b.HOME / '.config/test/new').exists())
        self.args.snapshot = next((b.HOME / '.backup-rollback').iterdir())
        b.restore(self.args)
        self.assertEqual((b.HOME / '.zshrc').read_text(), 'changed')
        self.assertTrue((b.HOME / '.config/test/new').exists())

    def test_dry_save_writes_nothing(self):
        self.args.dry_run = True
        b.snapshot(self.args)
        self.assertFalse(self.args.store.exists())

    def test_dry_restore_writes_nothing(self):
        self.args.snapshot = self.save()
        (b.HOME / '.zshrc').write_text('changed')
        self.args.dry_run = True
        b.restore(self.args)
        self.assertEqual((b.HOME / '.zshrc').read_text(), 'changed')
        self.assertFalse((b.HOME / '.backup-rollback').exists())

    def test_reject_nested_symlink(self):
        (b.HOME / '.config/test/link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            b.snapshot(self.args)
        self.assertFalse(self.args.store.exists())

    def test_save_linked_zshrc_as_portable_file(self):
        dotfiles = b.HOME / 'dotfiles/zsh'
        dotfiles.mkdir(parents=True)
        (dotfiles / '.zshrc').write_text('linked config')
        (b.HOME / '.zshrc').unlink()
        (b.HOME / '.zshrc').symlink_to('dotfiles/zsh/.zshrc')
        source = self.save()
        saved = source / 'files/.zshrc'
        self.assertFalse(saved.is_symlink())
        self.assertEqual(saved.read_text(), 'linked config')
        self.assertTrue((b.HOME / '.zshrc').is_symlink())
        (b.HOME / '.zshrc').unlink()
        self.args.snapshot = source
        b.restore(self.args)
        self.assertEqual((b.HOME / '.zshrc').read_text(), 'linked config')

    def test_nested_link_inside_home_is_materialized(self):
        (b.HOME / 'shared').mkdir()
        (b.HOME / 'shared/value').write_text('shared')
        (b.HOME / '.config/test/link').symlink_to(b.HOME / 'shared')
        source = self.save()
        self.assertEqual((source / 'files/.config/test/link/value').read_text(), 'shared')
        self.assertFalse((source / 'files/.config/test/link').is_symlink())

    def test_reject_broken_link_and_cycle(self):
        link = b.HOME / '.config/test/link'
        for destination in [b.HOME / 'missing', b.HOME / '.config/test']:
            with self.subTest(destination=destination):
                link.symlink_to(destination)
                with self.assertRaises(ValueError):
                    b.snapshot(self.args)
                link.unlink()
        self.assertFalse(self.args.store.exists())

    def test_reject_link_to_credentials(self):
        (b.HOME / '.ssh').mkdir()
        (b.HOME / '.ssh/key').write_text('private')
        (b.HOME / '.config/test/key').symlink_to(b.HOME / '.ssh/key')
        with self.assertRaises(ValueError):
            b.snapshot(self.args)

    def test_reject_link_to_backup_parent(self):
        (b.HOME / 'archive').mkdir()
        self.args.store = b.HOME / 'archive/snapshots'
        (b.HOME / '.config/test/link').symlink_to(b.HOME / 'archive')
        with self.assertRaises(ValueError):
            b.snapshot(self.args)

    def test_restore_rejects_snapshot_symlinks(self):
        source = self.save()
        saved = source / 'files/.zshrc'
        saved.unlink()
        saved.symlink_to(b.HOME / '.zshrc')
        self.args.snapshot = source
        with self.assertRaises(ValueError):
            b.restore(self.args)

    def test_reject_traversal_manifest(self):
        source = self.save()
        (source / 'manifest.json').write_text(json.dumps(dict(version=1, paths=['../outside'])))
        self.args.snapshot = source
        with self.assertRaises(ValueError):
            b.restore(self.args)

    def test_restore_rejects_symlink_parent(self):
        source = self.save()
        import shutil
        shutil.rmtree(b.HOME / '.config')
        external = self.root / 'external'
        external.mkdir()
        (b.HOME / '.config').symlink_to(external)
        self.args.snapshot = source
        with self.assertRaises(ValueError):
            b.restore(self.args)
        self.assertFalse((external / 'test').exists())

    def test_corruption_rejected_before_changes(self):
        source = self.save()
        (source / 'files/.zshrc').write_text('corrupted')
        (b.HOME / '.zshrc').write_text('current')
        self.args.snapshot = source
        with self.assertRaises(ValueError):
            b.restore(self.args)
        self.assertEqual((b.HOME / '.zshrc').read_text(), 'current')
        self.assertFalse((b.HOME / '.backup-rollback').exists())

    def test_overlapping_manifest_rejected(self):
        source = self.save()
        (source / 'manifest.json').write_text(json.dumps(dict(
            version=1, paths=['.config/test', '.config/test/value'])))
        self.args.snapshot = source
        with self.assertRaises(ValueError):
            b.restore(self.args)

    def test_copy_failure_rolls_back(self):
        from unittest.mock import patch
        source = self.save()
        (b.HOME / '.zshrc').write_text('changed')
        self.args.snapshot = source
        with patch.object(b, 'copy', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                b.restore(self.args)
        self.assertEqual((b.HOME / '.zshrc').read_text(), 'changed')


if __name__ == '__main__':
    unittest.main()
