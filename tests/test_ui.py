"""Exercise real Qt actions with synthetic game files, never the user's games."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import subprocess
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QInputDialog
from app import Window, STYLE
import test_core


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.fixture = test_core.Tests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.lib.scan = lambda: self.fixture.lib.games()

    def window(self):
        window = Window(self.fixture.lib); window.show(); self.app.processEvents()
        self.addCleanup(window.close)
        return window

    def test_missing_dependency_blocks_button_and_names_requirement(self):
        self.fixture.plugin_mod('SkyUI_SE.esp')
        window = self.window(); window.table.selectRow(0)
        self.assertFalse(window.enable_button.isEnabled())
        self.assertIn('SKSE64', window.details.text())
        self.assertIn('Requisitos pendentes', window.table.item(0,1).text())
        self.fixture.install_fake_skse(); window.refresh(); window.table.selectRow(0)
        self.assertTrue(window.enable_button.isEnabled())
        with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok):
            window.enable_button.click()
        self.assertTrue(self.fixture.lib.mods('489830')[0]['enabled'])
        self.assertEqual(self.fixture.lib.plugin_config('489830').active(), ['SkyUI_SE.esp'])
        window.table.selectRow(0); window.disable_button.click()
        self.assertFalse(self.fixture.lib.mods('489830')[0]['enabled'])
        self.assertEqual(self.fixture.lib.plugin_config('489830').active(), [])

    def test_filter_and_remove(self):
        self.fixture.archive()
        window = self.window(); window.search.setText('No such game')
        self.assertTrue(window.games.item(0).isHidden())
        window.search.clear(); window.table.selectRow(0)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            window.remove_button.click()
        self.assertEqual(self.fixture.lib.mods('489830'), [])

    def test_import_picker_accepts_7z(self):
        root = self.fixture.root
        source = root / 'ui-source'; source.mkdir(); (source / 'test.dds').write_bytes(b'texture')
        archive = root / 'ui-mod.7z'
        subprocess.run(['7z', 'a', '-t7z', str(archive), 'test.dds'], cwd=source, check=True, capture_output=True)
        window = self.window()
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(archive), '')) as picker, patch.object(QInputDialog, 'getText', return_value=('', True)):
            window.import_button.click()
        self.assertIn('*.7z', picker.call_args.args[3])
        self.assertEqual(self.fixture.lib.mods('489830')[0]['name'], 'ui-mod')
        window.table.selectRow(0); window.enable_button.click()
        self.assertEqual((self.fixture.game/'Data/test.dds').read_bytes(), b'texture')
