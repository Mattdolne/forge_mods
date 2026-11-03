from pathlib import Path
import tempfile
import unittest
import zipfile
import struct
from unittest.mock import patch
from skyrim import plugin_info, TextList
from core import Library, discover

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.home = self.root / 'home'
        self.apps = self.home / '.local/share/Steam/steamapps'; self.apps.mkdir(parents=True)
        self.game = self.apps / 'common/Skyrim'; (self.game / 'Data').mkdir(parents=True)
        self.manifest = self.apps / 'appmanifest_489830.acf'
        self.manifest.write_text('"AppState" { "appid" "489830" "name" "Skyrim SE" "installdir" "Skyrim" }')
        self.prefix = self.apps / 'compatdata/489830/pfx'
        self.config = self.prefix / 'drive_c/users/steamuser/AppData/Local/Skyrim Special Edition'
        self.config.mkdir(parents=True)
        (self.game / 'Data/Skyrim.esm').write_bytes(self.plugin(master=True))
        self.lib = Library(self.root / 'library'); self.addCleanup(self.lib.close); self.lib.scan(self.home)
    @staticmethod
    def plugin(masters=(), master=False, light=False):
        payload = b''
        for name in masters:
            value = name.encode('cp1252') + b'\0'
            payload += struct.pack('<4sH', b'MAST', len(value)) + value
        return struct.pack('<4sIIIII', b'TES4', len(payload), int(master) | (0x200 if light else 0), 0, 0, 0) + payload

    def plugin_mod(self, name, masters=('Skyrim.esm',), master=False, light=False):
        path = self.root / (name + '.zip')
        with zipfile.ZipFile(path, 'w') as z: z.writestr(name, self.plugin(masters, master, light))
        return self.lib.import_zip('489830', path)

    def archive(self, name='textures/test.dds'):
        path = self.root / 'mod.zip'
        with zipfile.ZipFile(path, 'w') as z: z.writestr(name, b'test')
        return self.lib.import_zip('489830', path)
    def test_detection_and_history(self):
        self.assertEqual(discover(self.home)[0]['id'], '489830')
        self.archive(); self.manifest.unlink(); self.lib.scan(self.home)
        self.assertFalse(self.lib.games()[0]['installed']); self.assertEqual(len(self.lib.mods('489830')), 1)
    def test_enable_disable_conflict(self):
        mid = self.archive(); self.lib.set_enabled(mid, True)
        target = self.game / 'Data/textures/test.dds'; self.assertEqual(target.read_bytes(), b'test')
        self.lib.set_enabled(mid, False); self.assertFalse(target.exists())
        target.with_name('TEST.dds').write_bytes(b'original')
        with self.assertRaisesRegex(ValueError, 'Conflito'): self.lib.set_enabled(mid, True)
        self.assertEqual(target.with_name('TEST.dds').read_bytes(), b'original')
    def test_external_changes(self):
        mid = self.archive(); self.lib.set_enabled(mid, True)
        target = self.game / 'Data/textures/test.dds'; target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'externamente'): self.lib.set_enabled(mid, False)
        self.assertEqual(target.read_bytes(), b'changed')
    def test_reinstall_profile(self):
        mid = self.archive('Data/textures/test.dds'); self.lib.set_enabled(mid, True)
        self.lib.save_profile('489830', 'Favoritos'); (self.game / 'Data/textures/test.dds').unlink()
        self.lib.scan(self.home); self.assertFalse(self.lib.mods('489830')[0]['enabled'])
        self.lib.restore_profile('489830', 'Favoritos')
        self.assertTrue((self.game / 'Data/textures/test.dds').exists())
    def test_unsafe_archives(self):
        for name in ['../escape', '/tmp/escape', 'C:/escape']:
            with self.subTest(name=name), self.assertRaises(ValueError): self.archive(name)
        path = self.root / 'bad.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('Textures/a', 'one'); z.writestr('textures/A', 'two')
        with self.assertRaises(ValueError): self.lib.import_zip('489830', path)
        with zipfile.ZipFile(path, 'w') as z:
            entry = zipfile.ZipInfo('link'); entry.external_attr = 0o120777 << 16; z.writestr(entry, '/etc/passwd')
        with self.assertRaises(ValueError): self.lib.import_zip('489830', path)
    def test_symlink_target(self):
        mid = self.archive(); other = self.root / 'other'; other.mkdir()
        (self.game / 'Data/textures').symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'simbólico'): self.lib.set_enabled(mid, True)
        self.assertEqual(list(other.iterdir()), [])
    def test_profile_rollback(self):
        a = self.archive('textures/a.dds'); self.lib.set_enabled(a, True)
        self.lib.save_profile('489830', 'A'); self.lib.set_enabled(a, False)
        b = self.archive('textures/b.dds'); self.lib.set_enabled(b, True)
        (self.game / 'Data/textures/a.dds').write_bytes(b'other')
        with self.assertRaises(ValueError): self.lib.restore_profile('489830', 'A')
        self.assertTrue(next(m for m in self.lib.mods('489830') if m['id'] == b)['enabled'])
        self.assertEqual((self.game / 'Data/textures/b.dds').read_bytes(), b'test')

    def test_plugin_install_activation_disable_preserves_others(self):
        original = b'# Preservar comentarios\r\nDisabled.esp\r\n'
        config = self.config / 'Plugins.txt'; config.write_bytes(original)
        mid = self.plugin_mod('Example.esp')
        self.assertEqual(self.lib.activation_issues(mid), [])
        self.lib.set_enabled(mid, True)
        self.assertEqual(config.read_bytes(), original + b'*Example.esp\r\n')
        self.assertTrue((self.game / 'Data/Example.esp').exists())
        self.assertIn(b'Example.esp', (self.config / 'loadorder.txt').read_bytes())
        self.lib.set_enabled(mid, False)
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse((self.game / 'Data/Example.esp').exists())
        self.assertTrue(list((self.lib.root / 'backups').glob('*/paths.json')))

    def test_dependencies_and_master_sort(self):
        master = self.plugin_mod('Required.esm', master=True)
        mod = self.plugin_mod('Dependent.esp', ('Skyrim.esm', 'Required.esm'))
        with self.assertRaisesRegex(ValueError, 'ausente'): self.lib.set_enabled(mod, True)
        self.lib.set_enabled(master, True); self.lib.set_enabled(mod, True)
        names = self.lib.plugin_config('489830').active()
        self.assertEqual(names, ['Required.esm', 'Dependent.esp'])
        with self.assertRaisesRegex(ValueError, 'Desative primeiro'): self.lib.set_enabled(master, False)
        with self.assertRaises(ValueError): self.lib.move_plugin('489830', 'Dependent.esp', -1)
        self.lib.set_enabled(mod, False); self.lib.set_enabled(master, False)

    def test_inactive_master_and_invalid_header(self):
        mid = self.plugin_mod('Dependent.esp', ('Required.esm',))
        (self.game / 'Data/Required.esm').write_bytes(self.plugin(master=True))
        with self.assertRaisesRegex(ValueError, 'inativo'): self.lib.set_enabled(mid, True)
        bad = self.archive('Invalid.esp')
        with self.assertRaisesRegex(ValueError, 'inválido'): self.lib.set_enabled(bad, True)
        self.assertFalse((self.game / 'Data/Dependent.esp').exists())

    def test_manual_order_and_remove(self):
        a = self.plugin_mod('A.esp'); b = self.plugin_mod('B.esp')
        self.lib.set_enabled(a, True); self.lib.set_enabled(b, True)
        self.lib.move_plugin('489830', 'B.esp', -1)
        self.assertEqual(self.lib.plugin_config('489830').active(), ['B.esp', 'A.esp'])
        self.lib.save_profile('489830', 'Both')
        self.lib.remove_mod(b)
        self.assertEqual(self.lib.plugin_config('489830').active(), ['A.esp'])
        self.assertFalse((self.lib.root / 'mods' / b).exists())
        self.assertEqual(len(self.lib.mods('489830')), 1)
        self.assertEqual(len(__import__('json').loads(self.lib.db.execute('SELECT mods FROM profiles').fetchone()[0])), 1)

    def test_config_write_failure_rolls_back_files_and_database(self):
        mid = self.plugin_mod('Example.esp')
        original = b'# Keep me\r\n'
        (self.config / 'Plugins.txt').write_bytes(original)
        import core
        real_write = core.atomic_write
        def fail_order(path, data):
            if Path(path).name == 'loadorder.txt': raise OSError('simulated failure')
            return real_write(path, data)
        with patch('core.atomic_write', side_effect=fail_order):
            with self.assertRaisesRegex(OSError, 'simulated'): self.lib.set_enabled(mid, True)
        self.assertEqual((self.config / 'Plugins.txt').read_bytes(), original)
        self.assertFalse((self.config / 'loadorder.txt').exists())
        self.assertFalse((self.game / 'Data/Example.esp').exists())
        self.assertFalse(self.lib.mods('489830')[0]['enabled'])

    def test_profile_orders_mods_by_dependencies(self):
        master = self.plugin_mod('ZMaster.esm', master=True)
        dependent = self.plugin_mod('APatch.esp', ('ZMaster.esm',))
        self.lib.set_enabled(master, True); self.lib.set_enabled(dependent, True)
        self.lib.save_profile('489830', 'Dependent set')
        self.lib.set_enabled(dependent, False); self.lib.set_enabled(master, False)
        self.lib.restore_profile('489830', 'Dependent set')
        self.assertEqual(self.lib.plugin_config('489830').active(), ['ZMaster.esm', 'APatch.esp'])

    def test_missing_prefix_and_override(self):
        import shutil
        other = self.root / 'custom-prefix'; shutil.move(self.prefix, other)
        mid = self.plugin_mod('Example.esp')
        with self.assertRaisesRegex(ValueError, 'Prefixo Proton'): self.lib.set_enabled(mid, True)
        self.lib.set_prefix('489830', other); self.lib.set_enabled(mid, True)
        self.assertTrue((other / 'drive_c/users/steamuser/AppData/Local/Skyrim Special Edition/plugins.txt').exists())

    def install_fake_skse(self):
        (self.game / 'skse64_loader.exe').write_bytes(b'loader')
        (self.game / 'skse64_1_6_1170.dll').write_bytes(b'runtime')
        scripts = self.game / 'Data/Scripts'; scripts.mkdir(exist_ok=True)
        (scripts / 'SKSE.pex').write_bytes(b'script')

    def test_skse_dll_and_diagnostic(self):
        mid = self.archive('SKSE/Plugins/example.dll')
        self.assertEqual(self.lib.activation_issues(mid), [])
        self.assertIn('Skyrim Script Extender (SKSE64)', self.lib.dependency_issues(mid)[0])
        with self.assertRaisesRegex(ValueError, 'SKSE64'): self.lib.set_enabled(mid, True)
        self.assertFalse(self.lib.mods('489830')[0]['enabled'])
        self.install_fake_skse()
        self.assertEqual(self.lib.dependency_issues(mid), [])
        self.lib.set_enabled(mid, True); self.lib.set_enabled(mid, False)
        self.assertIn('SKSE detectado', self.lib.warnings(mid)[0])

    def test_named_mod_requirement_blocks_and_protects_dependency(self):
        required = self.archive('textures/required.dds')
        self.lib.db.execute("UPDATE mods SET name='Required Mod' WHERE id=?", (required,)); self.lib.db.commit()
        dependent = self.archive('textures/dependent.dds')
        self.lib.set_requirements(dependent, ['Required Mod'])
        with self.assertRaisesRegex(ValueError, 'Required Mod'): self.lib.set_enabled(dependent, True)
        self.lib.set_enabled(required, True); self.lib.set_enabled(dependent, True)
        with self.assertRaisesRegex(ValueError, 'Desative primeiro'): self.lib.set_enabled(required, False)
        with self.assertRaisesRegex(ValueError, 'Desative primeiro'): self.lib.remove_mod(required)
        self.lib.set_enabled(dependent, False); self.lib.set_enabled(required, False)

    def test_skyui_starts_disabled_when_skse_missing(self):
        mid = self.plugin_mod('SkyUI_SE.esp')
        self.assertFalse(self.lib.mods('489830')[0]['enabled'])
        names = [r['name'] for r in self.lib.dependency_report(mid)]
        self.assertIn('Skyrim Script Extender (SKSE64)', names)
        self.assertIn('Skyrim.esm', names)
        with self.assertRaisesRegex(ValueError, 'SKSE64'): self.lib.set_enabled(mid, True)
        self.assertFalse((self.game / 'Data/SkyUI_SE.esp').exists())
        (self.game / 'skse64_loader.exe').write_bytes(b'loader-only')
        self.assertTrue(self.lib.dependency_issues(mid))
        self.install_fake_skse(); self.lib.set_enabled(mid, True)
        self.assertTrue(self.lib.mods('489830')[0]['enabled'])

    def test_classic_plugins_without_asterisks(self):
        self.lib.db.execute("INSERT INTO games VALUES('72850','Skyrim',?,1,'skyrim',1)", (str(self.game),))
        self.lib.db.commit(); self.lib.set_prefix('72850', self.prefix)
        path = self.root / 'classic.zip'
        with zipfile.ZipFile(path, 'w') as z: z.writestr('Classic.esp', self.plugin(('Skyrim.esm',)))
        mid = self.lib.import_zip('72850', path)
        self.lib.set_enabled(mid, True)
        plugin_path = self.config.parent / 'Skyrim/plugins.txt'
        self.assertEqual(plugin_path.read_bytes(), b'Classic.esp\r\n')
        self.lib.set_enabled(mid, False); self.assertEqual(plugin_path.read_bytes(), b'')

    def test_single_instance_lock(self):
        with self.assertRaisesRegex(ValueError, 'Outra instância'): Library(self.lib.root)

    def test_recovery_of_interrupted_operation(self):
        from transactions import FileTransaction
        path = self.game / 'Data/interrupted.txt'; path.write_bytes(b'before')
        transaction = FileTransaction(self.lib, [path]); path.write_bytes(b'after')
        self.lib.close()
        self.lib = Library(self.root / 'library')
        self.addCleanup(self.lib.close)
        self.assertEqual(path.read_bytes(), b'before')
        self.assertFalse(transaction.directory.exists())

    def test_fomod_and_native_files_preserved_with_reasons(self):
        path = self.root / 'complex.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('fomod/ModuleConfig.xml', '<config/>')
            z.writestr('SKSE/Plugins/Example.dll', b'dll')
        mid = self.lib.import_zip('489830', path)
        issues = '\n'.join(self.lib.activation_issues(mid))
        self.assertIn('fomod/ModuleConfig.xml', issues)
        self.assertNotIn('SKSE/Plugins/Example.dll', issues)
        with self.assertRaises(ValueError): self.lib.set_enabled(mid, True)
        self.assertEqual([p.name for p in (self.game / 'Data').iterdir()], ['Skyrim.esm'])

if __name__ == '__main__': unittest.main()
