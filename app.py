#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QInputDialog, QTabWidget, QTextEdit, QSplitter)
from core import Library

STYLE = '''
QWidget { background: #4c5844; color: #e0e3d6; font-family: 'Tahoma', 'DejaVu Sans'; font-size: 12px; }
QMainWindow { background: #4c5844; }
QLabel#brand { color: #ffae38; font-family: 'DejaVu Sans Mono'; font-size: 27px; font-weight: bold; padding: 9px 0; }
QLabel#title { color: #f0efdc; font-size: 21px; font-weight: bold; }
QLabel#muted { color: #bcc4ad; }
QPushButton { background: #59664f; border-top: 1px solid #8b977e; border-left: 1px solid #8b977e; border-bottom: 1px solid #283323; border-right: 1px solid #283323; padding: 8px 14px; border-radius: 0; }
QPushButton:hover { background: #657258; color: #fff3c7; }
QPushButton:pressed { background: #414c39; border-top-color: #283323; border-left-color: #283323; border-bottom-color: #8b977e; border-right-color: #8b977e; }
QPushButton:disabled { color: #929b86; background: #4c5844; }
QPushButton#primary { color: #ffbc55; font-weight: bold; }
QPushButton:focus { outline: 1px dotted #e0e3d6; }
QLineEdit, QTextEdit { background: #343e2e; border-top: 1px solid #283323; border-left: 1px solid #283323; border-bottom: 1px solid #859176; border-right: 1px solid #859176; padding: 8px; border-radius: 0; selection-background-color: #788850; }
QListWidget { background: #3e4936; border-top: 1px solid #283323; border-left: 1px solid #283323; border-bottom: 1px solid #859176; border-right: 1px solid #859176; }
QListWidget::item { padding: 9px 7px; border-bottom: 1px solid #4c5844; }
QListWidget::item:selected { background: #74844e; color: #fff6d2; }
QTableWidget { background: #343e2e; alternate-background-color: #394431; border-top: 1px solid #283323; border-left: 1px solid #283323; border-bottom: 1px solid #859176; border-right: 1px solid #859176; gridline-color: #4c5844; selection-background-color: #74844e; selection-color: #fff6d2; }
QTableWidget::item { padding: 7px; }
QHeaderView::section { background: #59664f; color: #e0e3d6; padding: 7px; border-top: 1px solid #8b977e; border-left: 1px solid #8b977e; border-right: 1px solid #283323; border-bottom: 1px solid #283323; }
QTabWidget::pane { border: 1px solid #859176; background: #4c5844; padding: 10px; }
QTabBar::tab { padding: 8px 20px; background: #414c39; border-top: 1px solid #859176; border-left: 1px solid #859176; border-right: 1px solid #283323; }
QTabBar::tab:selected { background: #59664f; color: #ffbc55; }
QStatusBar { background: #414c39; color: #bcc4ad; border-top: 1px solid #859176; }
QScrollBar:vertical { background: #343e2e; width: 15px; margin: 0; }
QScrollBar::handle:vertical { background: #657258; min-height: 24px; border: 1px solid #859176; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #343e2e; }
QToolTip { background: #e0dfba; color: #283323; border: 1px solid #283323; padding: 4px; }
'''



class Window(QMainWindow):
    def __init__(self, lib):
        super().__init__(); self.lib = lib; self.game = None
        self.setWindowTitle('Forge - Organizador de mods'); self.resize(1240, 790); self.setMinimumSize(1050, 680)
        container = QWidget(); self.setCentralWidget(container)
        layout = QHBoxLayout(container); layout.setContentsMargins(14, 12, 14, 12); layout.setSpacing(16)
        sidebar = QVBoxLayout(); layout.addLayout(sidebar, 1)
        brand = QLabel('λ  FORGE'); brand.setObjectName('brand'); sidebar.addWidget(brand)
        sidebar.addWidget(QLabel('BIBLIOTECA  /  JOGOS STEAM'))
        self.search = QLineEdit(); self.search.setPlaceholderText('Buscar jogo…'); self.search.textChanged.connect(self.filter_games); sidebar.addWidget(self.search)
        self.games = QListWidget(); self.games.setWordWrap(True); self.games.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.games.currentItemChanged.connect(self.select_game); sidebar.addWidget(self.games, 1)
        self.button(sidebar, 'Atualizar biblioteca', self.scan)
        footer = QLabel('FORGE v0.3  |  LINUX\nARQUIVO LOCAL DE MODIFICAÇÕES'); footer.setObjectName('muted'); sidebar.addWidget(footer)
        content = QVBoxLayout(); layout.addLayout(content, 3)
        self.title = QLabel('Sua biblioteca de mods'); self.title.setObjectName('title'); content.addWidget(self.title)
        self.info = QLabel('Selecione um jogo para começar.'); self.info.setWordWrap(True); self.info.setObjectName('muted'); content.addWidget(self.info)
        self.tabs = QTabWidget(); content.addWidget(self.tabs, 1)
        mods_widget = QWidget(); mods_layout = QVBoxLayout(mods_widget); mods_layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout(); mods_layout.addLayout(actions)
        self.import_button = self.button(actions, '+  Importar mod', self.import_mod, primary=True)
        self.enable_button = self.button(actions, 'Ativar', lambda: self.toggle(True))
        self.disable_button = self.button(actions, 'Desativar', lambda: self.toggle(False))
        self.dependency_button = self.button(actions, 'Dependências...', self.edit_requirements)
        self.remove_button = self.button(actions, 'Remover...', self.remove_mod)
        self.nexus_button = self.button(actions, 'Nexus Mods...', self.open_nexus)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(['MOD', 'ESTADO', 'ORIGEM'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().hide(); self.table.itemSelectionChanged.connect(self.update_actions)
        mods_layout.addWidget(self.table, 1)
        self.details = QLabel(''); self.details.setWordWrap(True); self.details.setObjectName('muted'); mods_layout.addWidget(self.details)
        self.empty = QLabel('Nenhum mod importado. Baixe um ZIP ou 7z no Nexus e adicione à biblioteca.'); self.empty.setWordWrap(True); mods_layout.addWidget(self.empty)
        note = QLabel('Skyrim: arquivos de dados, ESP/ESM/ESL e DLLs em SKSE/Plugins. Ativação gerenciada no Proton. FOMOD e instaladores de raiz ainda exigem suporte específico.\nAtivação copia arquivos para Data; conflitos são bloqueados sem substituir arquivos existentes.')
        note.setWordWrap(True); note.setObjectName('muted'); mods_layout.addWidget(note)
        self.tabs.addTab(mods_widget, 'Mods')
        profile_widget = QWidget(); pl = QVBoxLayout(profile_widget)
        pl.addWidget(QLabel('Guarde o conjunto de mods ativos e restaure após reinstalar o jogo.'))
        self.profile_list = QListWidget(); pl.addWidget(self.profile_list)
        row = QHBoxLayout(); pl.addLayout(row)
        self.save_button = self.button(row, 'Salvar conjunto atual', self.save_profile)
        self.restore_button = self.button(row, 'Restaurar perfil selecionado', self.restore_profile)
        self.tabs.addTab(profile_widget, 'Perfis')
        plugins_widget = QWidget(); plugins_layout = QVBoxLayout(plugins_widget)
        self.plugin_info_label = QLabel(''); self.plugin_info_label.setWordWrap(True); plugins_layout.addWidget(self.plugin_info_label)
        self.plugin_table = QTableWidget(0, 3); self.plugin_table.setHorizontalHeaderLabels(['PLUGIN', 'ESTADO', 'MASTERS EXIGIDOS'])
        self.plugin_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.plugin_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plugin_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.plugin_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        plugins_layout.addWidget(self.plugin_table)
        plugin_actions = QHBoxLayout(); plugins_layout.addLayout(plugin_actions)
        self.button(plugin_actions, 'Subir na ordem', lambda: self.move_plugin(-1))
        self.button(plugin_actions, 'Descer na ordem', lambda: self.move_plugin(1))
        self.button(plugin_actions, 'Selecionar prefixo Proton...', self.select_prefix)
        order_note = QLabel('A ordem existente é preservada. Mudanças que violam dependências são bloqueadas. Esta versão não aplica as regras adicionais do LOOT.')
        order_note.setWordWrap(True); order_note.setObjectName('muted'); plugins_layout.addWidget(order_note)
        self.tabs.addTab(plugins_widget, 'Plugins')
        self.history = QTextEdit(); self.history.setReadOnly(True); self.tabs.addTab(self.history, 'Histórico')
        self.statusBar().showMessage('Dados: ' + str(self.lib.root))
        self.scan()

    def button(self, layout, text, action, primary=False):
        button = QPushButton(text); button.clicked.connect(action)
        if primary: button.setObjectName('primary')
        layout.addWidget(button); return button

    def guard(self, fn):
        try: fn()
        except Exception as exc: QMessageBox.warning(self, 'Operação não concluída', str(exc))
        self.refresh()

    def scan(self):
        previous = self.game['id'] if self.game else None
        self.lib.scan(); self.games.clear()
        for game in self.lib.games():
            item = QListWidgetItem(game['name'] + ('\nInstalado' if game['installed'] else '\nNão instalado • histórico preservado'))
            item.setData(Qt.ItemDataRole.UserRole, game); self.games.addItem(item)
            if game['id'] == previous: self.games.setCurrentItem(item)
        if not self.games.currentItem() and self.games.count():
            preferred = next((self.games.item(i) for i in range(self.games.count()) if self.games.item(i).data(Qt.ItemDataRole.UserRole)['id'] == '489830'), self.games.item(0))
            self.games.setCurrentItem(preferred)
        self.filter_games(self.search.text()); self.refresh()

    def filter_games(self, text):
        for i in range(self.games.count()):
            item = self.games.item(i); item.setHidden(text.casefold() not in item.text().casefold())

    def select_game(self, item, previous):
        self.game = item.data(Qt.ItemDataRole.UserRole) if item else None; self.refresh()

    def refresh(self):
        self.table.setRowCount(0); self.profile_list.clear(); self.history.clear(); self.plugin_table.setRowCount(0); self.plugin_info_label.clear()
        if not self.game:
            self.title.setText('Sua biblioteca de mods'); self.info.setText('Nenhum jogo selecionado.'); self.update_actions(); return
        self.title.setText(self.game['name'])
        self.info.setText(('Instalado' if self.game['installed'] else 'Não instalado') + '  ·  Steam ' + self.game['id'] + '\n' + self.game['path'])
        mods = self.lib.mods(self.game['id'])
        for mod in mods:
            row = self.table.rowCount(); self.table.insertRow(row)
            title = QTableWidgetItem(mod['name']); title.setData(Qt.ItemDataRole.UserRole, mod)
            self.table.setItem(row, 0, title)
            issues = self.lib.readiness_issues(mod['id'])
            state = QTableWidgetItem('● Ativo' if mod['enabled'] else ('! Requisitos pendentes' if issues else '○ Na biblioteca'))
            state.setToolTip('\n'.join(issues) if issues else 'Requisitos conhecidos atendidos. Pronto para ativar.')
            self.table.setItem(row, 1, state)
            self.table.setItem(row, 2, QTableWidgetItem(mod['source'] or 'Arquivo local'))
            self.table.setRowHeight(row, 46)
        self.empty.setVisible(not mods)
        self.profile_list.addItems(self.lib.profiles(self.game['id']))
        if self.game['installed'] and self.game['supported']:
            try:
                self.plugin_info_label.setText('Configuração Proton: ' + str(self.lib.plugin_directory(self.game['id'])))
                for plugin in self.lib.plugins(self.game['id']):
                    row = self.plugin_table.rowCount(); self.plugin_table.insertRow(row)
                    values = [plugin['name'], ('Ativo' if plugin['active'] else 'Inativo') if plugin['present'] else 'Arquivo ausente', ', '.join(plugin['masters']) or '—']
                    for column, value in enumerate(values): self.plugin_table.setItem(row, column, QTableWidgetItem(value))
            except Exception as exc: self.plugin_info_label.setText(str(exc))
        self.history.setPlainText('\n\n'.join(f"{e['at']} UTC  ·  {e['action']}\n{e['detail']}" for e in self.lib.history(self.game['id'])) or 'Nenhum evento registrado.')
        self.update_actions()

    def selected(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def update_actions(self):
        g = self.game; mod = self.selected()
        self.import_button.setEnabled(bool(g)); self.nexus_button.setEnabled(bool(g)); self.remove_button.setEnabled(bool(mod)); self.dependency_button.setEnabled(bool(mod and not mod['enabled']))
        supported = bool(g and g['installed'] and g['supported'])
        issues = self.lib.readiness_issues(mod['id']) if mod else []
        self.enable_button.setEnabled(bool(supported and mod and not mod['enabled'] and not issues))
        self.enable_button.setToolTip('Ativação indisponível: veja os arquivos indicados abaixo.' if issues else '')
        if issues:
            self.details.setText('Mod mantido desativado. Resolva os requisitos para ativar:\n' + '\n'.join(issues[:4]) + ('\n… Passe o mouse sobre o estado para ver todos os arquivos.' if len(issues) > 4 else ''))
        else:
            report = self.lib.dependency_report(mod['id']) if mod else []
            self.details.setText('\n'.join(['Requisito atendido: ' + r['name'] for r in report] + (self.lib.warnings(mod['id']) if mod else [])))
        self.disable_button.setEnabled(bool(supported and mod and mod['enabled']))
        self.save_button.setEnabled(bool(g)); self.restore_button.setEnabled(supported)

    def import_mod(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar mod', str(Path.home() / 'Downloads'), 'Mods ZIP e 7z (*.zip *.ZIP *.7z *.7Z)')
        if not path: return
        source, ok = QInputDialog.getText(self, 'Origem do mod', 'Link do mod no Nexus (opcional):')
        if ok:
            def import_and_report():
                mod_id = self.lib.import_archive(self.game['id'], path, source.strip())
                issues = self.lib.readiness_issues(mod_id)
                if issues:
                    message = QMessageBox(self)
                    message.setWindowTitle('Mod importado na biblioteca')
                    message.setIcon(QMessageBox.Icon.Information)
                    message.setText('O mod foi importado e permanece desativado. Os requisitos abaixo precisam ser resolvidos antes de ativar.')
                    message.setInformativeText('Nenhum arquivo foi instalado no jogo. Consulte os detalhes abaixo.')
                    message.setDetailedText('\n'.join(issues))
                    message.exec()
            self.guard(import_and_report)

    def toggle(self, enabled):
        mod = self.selected()
        if not mod: return
        def apply():
            self.lib.set_enabled(mod['id'], enabled)
            warnings = self.lib.warnings(mod['id']) if enabled else []
            if warnings: QMessageBox.information(self, 'Mod instalado e ativado', '\n'.join(warnings))
        self.guard(apply)

    def edit_requirements(self):
        mod = self.selected()
        if not mod: return
        automatic = self.lib.dependency_report(mod['id'])
        label = 'Dependências detectadas: ' + (', '.join(r['name'] for r in automatic if r['kind'] != 'mod') or 'nenhuma')
        label += '\nOutros requisitos informados pelo autor: um nome de mod por linha, igual ao nome exibido na biblioteca.\nA detecção automática lê masters do plugin e reconhece SKSE; requisitos apenas descritos no Nexus precisam ser cadastrados aqui.'
        text, ok = QInputDialog.getMultiLineText(self, 'Dependências do mod', label, '\n'.join(self.lib.declared_requirements(mod['id'])))
        if ok: self.guard(lambda: self.lib.set_requirements(mod['id'], text.splitlines()))

    def remove_mod(self):
        mod = self.selected()
        if not mod: return
        answer = QMessageBox.question(self, 'Remover mod', 'Remover ' + mod['name'] + '? Se estiver ativo, será desativado. A cópia da biblioteca e as referências nos perfis serão removidas; o histórico permanece.')
        if answer == QMessageBox.StandardButton.Yes: self.guard(lambda: self.lib.remove_mod(mod['id']))

    def select_prefix(self):
        if not self.game: return
        path = QFileDialog.getExistingDirectory(self, 'Selecione a pasta pfx do Proton')
        if path: self.guard(lambda: self.lib.set_prefix(self.game['id'], path))

    def move_plugin(self, direction):
        row = self.plugin_table.currentRow()
        if row < 0 or not self.game: return
        name = self.plugin_table.item(row, 0).text()
        self.guard(lambda: self.lib.move_plugin(self.game['id'], name, direction))
        for i in range(self.plugin_table.rowCount()):
            if self.plugin_table.item(i, 0).text() == name: self.plugin_table.selectRow(i); break

    def open_nexus(self):
        mod = self.selected()
        url = mod['source'] if mod and mod['source'].startswith('https://www.nexusmods.com/') else 'https://www.nexusmods.com/' + self.game['nexus']
        QDesktopServices.openUrl(QUrl(url))

    def save_profile(self):
        name, ok = QInputDialog.getText(self, 'Salvar perfil', 'Nome do perfil:')
        if ok: self.guard(lambda: self.lib.save_profile(self.game['id'], name))

    def restore_profile(self):
        item = self.profile_list.currentItem()
        if item: self.guard(lambda: self.lib.restore_profile(self.game['id'], item.text()))


if __name__ == '__main__':
    app = QApplication(sys.argv); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    lib = Library(); window = Window(lib); window.show()
    if '--screenshot' in sys.argv:
        from PySide6.QtCore import QTimer
        def capture():
            window.grab().save(sys.argv[sys.argv.index('--screenshot') + 1]); app.quit()
        QTimer.singleShot(400, capture)
    result = app.exec(); lib.close(); sys.exit(result)
