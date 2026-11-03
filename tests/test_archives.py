from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from archives import Entry, extract_archive
import test_core


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.Tests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def seven(self, files):
        if not shutil.which('7z'): self.fail('Testes 7z exigem o comando 7z (pacote 7zip).')
        source = self.root / 'archive-source'; source.mkdir()
        for name, data in files.items():
            path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        archive = self.root / 'mod.7z'
        subprocess.run(['7z', 'a', '-t7z', str(archive), '.'], cwd=source, check=True, capture_output=True)
        return archive

    def test_solid_7z_plugin_install_disable(self):
        archive = self.seven({'Data/Example.esp': self.fixture.plugin(('Skyrim.esm',)), 'Data/textures/café.dds': b'texture' * 10000})
        mid = self.fixture.lib.import_archive('489830', archive)
        self.assertFalse(self.fixture.lib.mods('489830')[0]['enabled'])
        self.fixture.lib.set_enabled(mid, True)
        self.assertEqual(self.fixture.lib.plugin_config('489830').active(), ['Example.esp'])
        self.assertEqual((self.fixture.game / 'Data/textures/café.dds').read_bytes(), b'texture' * 10000)
        self.fixture.lib.set_enabled(mid, False)
        self.assertFalse((self.fixture.game / 'Data/Example.esp').exists())

    def test_7z_wrapper_normalization(self):
        mid = self.fixture.lib.import_archive('489830', self.seven({'MyMod/Data/textures/test.dds': b'payload'}))
        self.assertEqual((self.fixture.lib.root/'mods'/mid/'textures/test.dds').read_bytes(), b'payload')

    def test_7z_duplicate_names_blocked(self):
        archive = self.seven({'Textures/a.dds': b'a', 'textures/A.dds': b'b'})
        with self.assertRaisesRegex(ValueError, 'duplicados'): self.fixture.lib.import_archive('489830', archive)
        self.assertEqual(self.fixture.lib.mods('489830'), [])

    def test_7z_symbolic_link_blocked(self):
        source = self.root / 'links'; source.mkdir()
        (source/'outside').symlink_to('/etc/passwd')
        archive = self.root / 'links.7z'
        subprocess.run(['7z','a','-t7z','-snl',str(archive),'outside'],cwd=source,check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError, 'Links'): self.fixture.lib.import_archive('489830', archive)
        self.assertEqual(self.fixture.lib.mods('489830'), [])

    def test_7z_password_and_invalid_file(self):
        archive = self.seven({'file.dds': b'payload'})
        encrypted = self.root/'encrypted.7z'
        subprocess.run(['7z','a','-t7z','-ptestpassword',str(encrypted),'file.dds'],cwd=self.root/'archive-source',check=True,capture_output=True)
        with self.assertRaises(ValueError): self.fixture.lib.import_archive('489830', encrypted)
        invalid = self.root/'bad.7z'; invalid.write_bytes(b'not an archive')
        with self.assertRaisesRegex(ValueError, 'Formato'): self.fixture.lib.import_archive('489830', invalid)

    def test_missing_libarchive_actionable_error(self):
        archive = self.seven({'test.dds': b'payload'})
        with patch('archives.ctypes.util.find_library', return_value=None):
            with self.assertRaisesRegex(ValueError, 'instale libarchive'): self.fixture.lib.import_archive('489830',archive)

    def test_shared_path_validation_and_actual_size_limit(self):
        archive=self.seven({'test.dds':b'payload'})
        destination=self.root/'stage';destination.mkdir()
        with patch('archives.entries', return_value=iter([(Entry('../escape',1),None)])):
            with self.assertRaisesRegex(ValueError, 'inseguro'): extract_archive(archive,destination)
        with patch('archives.MAX_SIZE', 2):
            with self.assertRaisesRegex(ValueError, '8 GiB'): extract_archive(archive,destination)

    def test_zip_still_uses_same_import_method(self):
        archive=self.root/'mod.ZIP'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('Data/textures/test.dds',b'zip')
        mid=self.fixture.lib.import_archive('489830',archive)
        self.assertEqual((self.fixture.lib.root/'mods'/mid/'textures/test.dds').read_bytes(),b'zip')
