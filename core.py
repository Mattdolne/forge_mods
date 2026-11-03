"""Local-first mod library. No Steam credentials or external dependencies."""
from pathlib import Path, PurePosixPath
import hashlib
import fcntl
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from skyrim import PluginConfig, plugin_info, EXTENSIONS, BASE_SE, child, atomic_write
from transactions import FileTransaction

SUPPORTED = {'489830': 'skyrimspecialedition', '72850': 'skyrim'}


def vdf(text):
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', text)
    root, stack, key = {}, [], None
    current = root
    for value, brace in tokens:
        if brace == '{':
            child = {}; current[key] = child; stack.append(current); current = child; key = None
        elif brace == '}':
            current = stack.pop(); key = None
        elif key is None:
            key = value.replace('\\\\', '\\')
        else:
            current[key] = value.replace('\\\\', '\\'); key = None
    return root


def discover(home=None):
    home = Path(home or Path.home())
    roots = [home / '.local/share/Steam', home / '.steam/steam',
             home / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
    libraries = set()
    for root in roots:
        if not root.exists(): continue
        libraries.add(root.resolve())
        try:
            folders = vdf((root / 'steamapps/libraryfolders.vdf').read_text())['libraryfolders']
            for entry in folders.values():
                if isinstance(entry, dict) and 'path' in entry: libraries.add(Path(entry['path']).resolve())
        except (OSError, KeyError, ValueError, IndexError): pass
    games = {}
    for library in sorted(libraries):
        for manifest in (library / 'steamapps').glob('appmanifest_*.acf'):
            try:
                info = vdf(manifest.read_text())['AppState']
                path = library / 'steamapps/common' / info['installdir']
                if not path.is_dir(): continue
                appid = info['appid']
                games[appid] = dict(id=appid, name=info['name'], path=str(path), installed=True,
                                    nexus=SUPPORTED.get(appid, ''), supported=appid in SUPPORTED)
            except (OSError, KeyError, ValueError, IndexError): continue
    return sorted(games.values(), key=lambda x: x['name'].lower())


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


class Library:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('FORGE_DATA_DIR') or
                         Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'forge-mods')
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = (self.root / '.lock').open('a+')
        try: fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise ValueError('Outra instância do Forge está usando esta biblioteca. Feche-a antes de continuar.')
        self.db = sqlite3.connect(self.root / 'library.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY, name TEXT, path TEXT, installed INTEGER, nexus TEXT, supported INTEGER);
        CREATE TABLE IF NOT EXISTS mods(id TEXT PRIMARY KEY, game TEXT, name TEXT, source TEXT, enabled INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS files(mod TEXT, path TEXT, hash TEXT, PRIMARY KEY(mod,path));
        CREATE TABLE IF NOT EXISTS deployed(mod TEXT, path TEXT, hash TEXT, PRIMARY KEY(mod,path));
        CREATE TABLE IF NOT EXISTS profiles(game TEXT,name TEXT,mods TEXT,PRIMARY KEY(game,name));
        CREATE TABLE IF NOT EXISTS events(at TEXT DEFAULT CURRENT_TIMESTAMP,game TEXT,action TEXT,detail TEXT);
        ''')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings(game TEXT, key TEXT, value TEXT, PRIMARY KEY(game,key))')
        self.db.execute('CREATE TABLE IF NOT EXISTS fs_commits(id TEXT PRIMARY KEY)')
        self.db.execute('CREATE TABLE IF NOT EXISTS requirements(mod TEXT,name TEXT,PRIMARY KEY(mod,name))')
        self.db.commit()
        FileTransaction.recover(self)

    def close(self):
        self.db.close()
        self._lock.close()

    def event(self, game, action, detail):
        self.db.execute('INSERT INTO events(game,action,detail) VALUES(?,?,?)', (game, action, detail))

    def scan(self, home=None):
        games = discover(home)
        self.db.execute('UPDATE games SET installed=0')
        for g in games:
            self.db.execute('INSERT OR REPLACE INTO games VALUES(:id,:name,:path,:installed,:nexus,:supported)', g)
        # An uninstall removes deployed files, but keeps archives and profiles.
        for mod in self.db.execute('SELECT * FROM mods WHERE enabled=1').fetchall():
            paths = [Path(r[0]) for r in self.db.execute('SELECT path FROM deployed WHERE mod=?', (mod['id'],))]
            if paths and all(not p.exists() and not p.is_symlink() for p in paths):
                self.db.execute('UPDATE mods SET enabled=0 WHERE id=?', (mod['id'],))
                self.db.execute('DELETE FROM deployed WHERE mod=?', (mod['id'],))
                self.event(mod['game'], 'Arquivos ausentes', mod['name'] + ' — biblioteca preservada; restaure um perfil para reinstalar.')
        self.db.commit()
        return self.games()

    def games(self): return [dict(x) for x in self.db.execute('SELECT * FROM games ORDER BY name')]
    def mods(self, game): return [dict(x) for x in self.db.execute('SELECT * FROM mods WHERE game=? ORDER BY name', (game,))]

    def import_zip(self, game, archive, source=''):
        archive = Path(archive)
        mod_id = uuid.uuid4().hex
        target = self.root / 'mods' / mod_id
        target.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            stage = Path(tmp)
            with zipfile.ZipFile(archive) as z:
                members = [x for x in z.infolist() if not x.is_dir()]
                if not members: raise ValueError('O arquivo está vazio.')
                if sum(x.file_size for x in members) > 8 * 1024**3: raise ValueError('Limite de 8 GiB descompactados por mod.')
                names = []
                for item in members:
                    name = item.filename.replace('\\', '/')
                    p = PurePosixPath(name)
                    if p.is_absolute() or '..' in p.parts or ':' in name or not p.parts:
                        raise ValueError('O ZIP contém um caminho inseguro.')
                    if stat.S_ISLNK(item.external_attr >> 16): raise ValueError('Links simbólicos não são aceitos.')
                    names.append(p)
                # Accept Data/... or a single wrapper directory containing Data/...
                prefix = 0
                if all(p.parts[0].lower() == 'data' for p in names): prefix = 1
                elif all(len(p.parts) >= 3 and p.parts[0] == names[0].parts[0] and p.parts[1].lower() == 'data' for p in names): prefix = 2
                seen = set()
                for item, p in zip(members, names):
                    parts = p.parts[prefix:]
                    if not parts: continue
                    relative = '/'.join(parts)
                    if relative.casefold() in seen: raise ValueError('Arquivos duplicados por diferença de maiúsculas/minúsculas.')
                    seen.add(relative.casefold())
                    dest = stage.joinpath(*parts); dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, dest.open('wb') as out: shutil.copyfileobj(src, out)
            shutil.copytree(stage, target)
        try:
            with self.db:
                self.db.execute('INSERT INTO mods(id,game,name,source) VALUES(?,?,?,?)', (mod_id, game, archive.stem, source))
                for path in target.rglob('*'):
                    if path.is_file(): self.db.execute('INSERT INTO files VALUES(?,?,?)', (mod_id, path.relative_to(target).as_posix(), digest(path)))
                self.event(game, 'Importado', archive.name)
        except Exception:
            shutil.rmtree(target); raise
        return mod_id

    def activation_issues(self, mod_id):
        """Import preserves all content; deployment requires a supported format."""
        issues = []
        for row in self.db.execute('SELECT path FROM files WHERE mod=? ORDER BY path', (mod_id,)):
            path = PurePosixPath(row['path'])
            if any(part.casefold() == 'fomod' for part in path.parts):
                reason = 'instalador FOMOD ainda não suportado'
            elif path.suffix.lower() in EXTENSIONS and len(path.parts) != 1:
                reason = 'plugin fora da raiz de Data; reorganize o pacote antes de ativar'
            elif path.suffix.lower() in {'.exe', '.bat', '.sh'} or (path.suffix.lower() == '.dll' and tuple(p.casefold() for p in path.parts[:2]) != ('skse', 'plugins')):
                reason = 'executável ou plugin nativo: instalação específica ainda não implementada'
            else:
                continue
            issues.append(f'{row["path"]} — {reason}')
        return issues

    def target(self, game):
        g = self.db.execute('SELECT * FROM games WHERE id=?', (game,)).fetchone()
        if not g or not g['installed']: raise ValueError('O jogo não está instalado. O histórico permanece disponível.')
        if not g['supported']: raise ValueError('Ativação disponível apenas para Skyrim e Skyrim Special Edition nesta versão.')
        root = Path(g['path'])
        data = next((p for p in root.iterdir() if p.name.casefold() == 'data'), root / 'Data')
        if data.is_symlink(): raise ValueError('A pasta Data não pode ser um link simbólico.')
        if not data.is_dir(): raise ValueError('Pasta Data não encontrada.')
        return data

    @staticmethod
    def resolve(root, relative):
        current = root
        for part in PurePosixPath(relative).parts:
            if current.is_dir():
                matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()]
                if len(matches) > 1: raise ValueError('Colisão de nomes no Linux: ' + str(current / part))
                current = matches[0] if matches else current / part
            else: current = current / part
            if current.is_symlink(): raise ValueError('Link simbólico encontrado: ' + str(current))
        return current

    def plugin_directory(self, game):
        g = self.db.execute('SELECT * FROM games WHERE id=?', (game,)).fetchone()
        override = self.db.execute("SELECT value FROM settings WHERE game=? AND key='prefix'", (game,)).fetchone()
        if override:
            prefixes = [Path(override[0])]
        else:
            library = Path(g['path']).parent.parent.parent
            roots = [library, Path.home() / '.local/share/Steam', Path.home() / '.steam/steam',
                     Path.home() / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
            prefixes = list(dict.fromkeys(root.resolve() / 'steamapps/compatdata' / game / 'pfx' for root in roots))
            prefixes = [p for p in prefixes if (p / 'drive_c').is_dir()]
            if len(prefixes) > 1:
                primary = library / 'steamapps/compatdata' / game / 'pfx'
                if primary in prefixes: prefixes = [primary]
                else: raise ValueError('Mais de um prefixo Proton encontrado. Selecione o correto em Plugins > Selecionar prefixo.')
        if len(prefixes) != 1 or not (prefixes[0] / 'drive_c').is_dir():
            raise ValueError('Prefixo Proton não encontrado. Inicie o jogo uma vez pela Steam ou selecione a pasta pfx na aba Plugins.')
        users = prefixes[0] / 'drive_c/users'
        user = users / 'steamuser'
        if not user.is_dir():
            candidates = [p for p in users.iterdir() if p.is_dir() and p.name.casefold() not in {'public', 'default', 'default user', 'all users'}]
            if len(candidates) != 1: raise ValueError('Não foi possível identificar o usuário do prefixo Proton.')
            user = candidates[0]
        local = child(child(user, 'AppData'), 'Local')
        if not local.is_dir(): raise ValueError('AppData/Local não existe no prefixo. Inicie o jogo pela Steam primeiro.')
        return child(local, 'Skyrim Special Edition' if game == '489830' else 'Skyrim')

    def set_prefix(self, game, path):
        path = Path(path).resolve()
        if not (path / 'drive_c/users').is_dir(): raise ValueError('Selecione a pasta pfx que contém drive_c/users.')
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,'prefix',?)", (game, str(path)))

    def plugin_config(self, game): return PluginConfig(self.plugin_directory(game), special=game == '489830')

    def implicit_plugins(self, game, data):
        names = set(BASE_SE if game == '489830' else {'skyrim.esm', 'update.esm'})
        ccc = self.resolve(data.parent, 'Skyrim.ccc')
        if game == '489830' and ccc.is_file():
            names.update(line.strip().casefold() for line in ccc.read_text(encoding='utf-8-sig').splitlines() if line.strip())
        return {name for name in names if self.resolve(data, name).is_file()}

    def mod_plugins(self, mod_id):
        return [plugin_info(self.root / 'mods' / mod_id / row[0]) for row in
                self.db.execute('SELECT path FROM files WHERE mod=? ORDER BY path', (mod_id,))
                if PurePosixPath(row[0]).suffix.lower() in EXTENSIONS and len(PurePosixPath(row[0]).parts) == 1]

    def plugin_inventory(self, data):
        result = {}
        for path in data.iterdir():
            if path.suffix.lower() in EXTENSIONS and path.is_file():
                if path.is_symlink(): raise ValueError('Plugin em link simbólico: ' + path.name)
                key = path.name.casefold()
                if key in result: raise ValueError('Plugins duplicados por maiúsculas/minúsculas: ' + path.name)
                result[key] = plugin_info(path)
        return result

    def validate_plugins(self, game, data, config, incoming=()):
        inventory = self.plugin_inventory(data)
        inventory.update((p['name'].casefold(), p) for p in incoming)
        implicit = self.implicit_plugins(game, data)
        active = [n.casefold() for n in config.active() if n.casefold() not in implicit]
        if len(active) != len(set(active)): raise ValueError('Plugins.txt contém plugins duplicados; corrija antes de ativar.')
        positions = {name: i for i,name in enumerate(active)}
        regular_seen = False
        for name in active:
            if name not in inventory: raise ValueError('Plugin ativo não encontrado em Data: ' + name)
            info = inventory[name]
            if game != '489830' and (info['light'] or Path(name).suffix.lower() == '.esl'):
                raise ValueError('Plugins ESL exigem Skyrim Special Edition.')
            if info['master'] and regular_seen: raise ValueError('Um master precisa carregar antes de plugins comuns: ' + info['name'])
            regular_seen = regular_seen or not info['master']
            for master in info['masters']:
                key = master.casefold()
                if key not in inventory: raise ValueError('Dependência ausente: ' + info['name'] + ' precisa de ' + master)
                if key not in implicit and key not in positions: raise ValueError('Dependência inativa: ' + master + ' exigida por ' + info['name'])
                if key in positions and positions[key] >= positions[name]: raise ValueError('Ordem inválida: ' + master + ' precisa carregar antes de ' + info['name'])
        full = sum(not inventory[n]['light'] for n in set(active) | implicit if n in inventory)
        light = sum(inventory[n]['light'] for n in set(active) | implicit if n in inventory)
        if full > (254 if game == '489830' else 255) or light > 4096:
            raise ValueError('Limite de plugins ativos excedido.')
        return inventory

    @staticmethod
    def sort_incoming(infos):
        by_name = {i['name'].casefold(): i for i in infos}; result = []; visiting = set(); done = set()
        def visit(key):
            if key in visiting: raise ValueError('Dependências cíclicas entre plugins do mod.')
            if key in done: return
            visiting.add(key)
            for master in by_name[key]['masters']:
                if master.casefold() in by_name: visit(master.casefold())
            visiting.remove(key); done.add(key); result.append(by_name[key])
        for info in sorted(infos, key=lambda i: not i['master']): visit(info['name'].casefold())
        return result

    def backup_configs(self, changes):
        if not changes: return
        folder = self.root / 'backups' / uuid.uuid4().hex; folder.mkdir(parents=True)
        manifest = []
        for i,(path, _) in enumerate(changes):
            if path.exists(): shutil.copy2(path, folder / str(i))
            manifest.append({'path': str(path), 'backup': str(i) if path.exists() else None})
        (folder / 'paths.json').write_text(json.dumps(manifest, indent=2))

    def declared_requirements(self, mod_id):
        return [r[0] for r in self.db.execute('SELECT name FROM requirements WHERE mod=? ORDER BY name', (mod_id,))]

    def set_requirements(self, mod_id, names):
        mod = self.db.execute('SELECT * FROM mods WHERE id=?', (mod_id,)).fetchone()
        if not mod: raise ValueError('Mod não encontrado.')
        if mod['enabled']: raise ValueError('Desative o mod antes de alterar as dependências declaradas.')
        cleaned = sorted({name.strip() for name in names if name.strip()}, key=str.casefold)
        if any(len(name) > 250 or '\n' in name or '\r' in name for name in cleaned): raise ValueError('Nome de dependência inválido.')
        with self.db:
            self.db.execute('DELETE FROM requirements WHERE mod=?', (mod_id,))
            self.db.executemany('INSERT INTO requirements VALUES(?,?)', [(mod_id,name) for name in cleaned])
            self.event(mod['game'], 'Dependências declaradas', mod['name'] + ': ' + ', '.join(cleaned))

    def dependency_report(self, mod_id):
        mod = self.db.execute('SELECT * FROM mods WHERE id=?', (mod_id,)).fetchone()
        if not mod: return []
        g = self.db.execute('SELECT * FROM games WHERE id=?', (mod['game'],)).fetchone()
        data = self.target(mod['game']) if g and g['installed'] and g['supported'] else None
        infos = self.mod_plugins(mod_id)
        own = {p['name'].casefold() for p in infos}
        report = []
        try: active = {n.casefold() for n in self.plugin_config(mod['game']).active()} if data else set()
        except ValueError: active = set()
        implicit = self.implicit_plugins(mod['game'], data) if data else set()
        for master in sorted({name for info in infos for name in info['masters']}, key=str.casefold):
            key = master.casefold()
            if key in own: continue
            present = bool(data and self.resolve(data, master).is_file())
            report.append(dict(name=master, kind='plugin', satisfied=present and key in active | implicit,
                               reason='ausente' if not present else ('ativo' if key in active | implicit else 'instalado, mas inativo')))
        paths = [r[0].casefold() for r in self.db.execute('SELECT path FROM files WHERE mod=?', (mod_id,))]
        if any(name in {'skyui_se.esp', 'skyui.esp'} or name.startswith('skse/plugins/') for name in paths):
            special = mod['game'] == '489830'
            loader = 'skse64_loader.exe' if special else 'skse_loader.exe'
            root = Path(g['path']) if g else None
            runtime = re.compile(r'skse64_\d+_\d+_\d+\.dll' if special else r'skse_\d+_\d+_\d+\.dll')
            present = bool(data and root and self.resolve(root, loader).is_file()
                           and any(p.is_file() and runtime.fullmatch(p.name.casefold()) for p in root.iterdir())
                           and self.resolve(data, 'Scripts/SKSE.pex').is_file())
            report.append(dict(name='Skyrim Script Extender (SKSE64)' if special else 'Skyrim Script Extender (SKSE)',
                               kind='skse', satisfied=present, reason='arquivos detectados; versão e execução não verificadas' if present else 'instalação ausente ou incompleta'))
        mods = self.mods(mod['game'])
        for name in self.declared_requirements(mod_id):
            matches = [m for m in mods if m['id'] != mod_id and m['name'].casefold() == name.casefold()]
            enabled = any(m['enabled'] for m in matches)
            report.append(dict(name=name,kind='mod',satisfied=enabled,reason='ativo' if enabled else ('importado, mas inativo' if matches else 'não importado')))
        return report

    def dependency_issues(self, mod_id):
        return [r['name'] + ' — ' + r['reason'] for r in self.dependency_report(mod_id) if not r['satisfied']]

    def readiness_issues(self, mod_id):
        try: return self.activation_issues(mod_id) + self.dependency_issues(mod_id)
        except (ValueError, OSError) as exc: return [str(exc)]

    def warnings(self, mod_id):
        if any(r['kind'] == 'skse' and r['satisfied'] for r in self.dependency_report(mod_id)):
            return ['SKSE detectado. Inicie o jogo pelo carregador SKSE compatível com a versão do jogo.']
        return []

    def set_enabled(self, mod_id, enabled):
        mod = self.db.execute('SELECT * FROM mods WHERE id=?', (mod_id,)).fetchone()
        if not mod: raise ValueError('Mod não encontrado.')
        if bool(mod['enabled']) == enabled: return
        data = self.target(mod['game'])
        rows = self.db.execute('SELECT * FROM files WHERE mod=?', (mod_id,)).fetchall()
        infos = self.mod_plugins(mod_id)
        config = self.plugin_config(mod['game']) if infos else None
        changes = []
        if enabled:
            issues = self.readiness_issues(mod_id)
            if issues: raise ValueError('Ativação bloqueada. Resolva os requisitos abaixo:\n' + '\n'.join(issues[:10]))
            plan = [(r, self.resolve(data, r['path'])) for r in rows]
            for r, dst in plan:
                if dst.exists(): raise ValueError('Conflito: ' + str(dst) + '\nNenhum arquivo existente será substituído.')
                if digest(self.root / 'mods' / mod_id / r['path']) != r['hash']:
                    raise ValueError('Arquivo do mod alterado: ' + r['path'])
            if config:
                inventory = self.plugin_inventory(data)
                config.master_names = {name for name, info in inventory.items() if info['master']}
                config.master_names.update(i['name'].casefold() for i in infos if i['master'])
                config.enable(self.sort_incoming(infos))
                self.validate_plugins(mod['game'], data, config, infos)
                changes = config.changes()
            paths = [dst for _,dst in plan]
        else:
            for dependent in self.mods(mod['game']):
                if dependent['enabled'] and dependent['id'] != mod_id and mod['name'].casefold() in {n.casefold() for n in self.declared_requirements(dependent['id'])}:
                    alternatives = [m for m in self.mods(mod['game']) if m['id'] != mod_id and m['enabled'] and m['name'].casefold() == mod['name'].casefold()]
                    if not alternatives: raise ValueError('Desative primeiro ' + dependent['name'] + ': depende de ' + mod['name'])
            deployed = self.db.execute('SELECT * FROM deployed WHERE mod=?', (mod_id,)).fetchall()
            paths = []
            for row in deployed:
                path = self.resolve(data, Path(row['path']).relative_to(data).as_posix())
                if path.exists() and (not path.is_file() or digest(path) != row['hash']):
                    raise ValueError('Arquivo alterado externamente; desativação cancelada: ' + str(path))
                paths.append(path)
            if config:
                names = {i['name'].casefold() for i in infos}
                inventory = self.plugin_inventory(data)
                for active in config.active():
                    info = inventory.get(active.casefold())
                    if info and active.casefold() not in names:
                        required = names.intersection(m.casefold() for m in info['masters'])
                        if required: raise ValueError('Desative primeiro ' + active + ': depende de ' + ', '.join(sorted(required)))
                config.disable(names); changes = config.changes()
        self.backup_configs(changes)
        transaction = FileTransaction(self, paths + [path for path,_ in changes])
        try:
            with self.db:
                if enabled:
                    for r, dst in plan:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        with dst.open('xb') as out, (self.root / 'mods' / mod_id / r['path']).open('rb') as inp:
                            shutil.copyfileobj(inp, out)
                        self.db.execute('INSERT INTO deployed VALUES(?,?,?)', (mod_id, str(dst), r['hash']))
                else:
                    for path in paths: path.unlink(missing_ok=True)
                    self.db.execute('DELETE FROM deployed WHERE mod=?', (mod_id,))
                for path, content in changes: atomic_write(path, content)
                self.db.execute('UPDATE mods SET enabled=? WHERE id=?', (int(enabled), mod_id))
                self.event(mod['game'], 'Ativado' if enabled else 'Desativado', mod['name'])
                transaction.commit_record()
        except Exception:
            transaction.rollback(); raise
        transaction.cleanup()

    def plugins(self, game):
        data = self.target(game); config = self.plugin_config(game)
        inventory = self.plugin_inventory(data); implicit = self.implicit_plugins(game, data)
        result = []
        for name, active in config.plugins.entries():
            info = inventory.get(name.casefold(), {'name': name, 'masters': [], 'master': False, 'light': False})
            result.append(dict(info, active=active, present=name.casefold() in inventory, implicit=name.casefold() in implicit))
        return result

    def move_plugin(self, game, name, direction):
        if direction not in {-1, 1}: raise ValueError('Direção inválida.')
        data = self.target(game); config = self.plugin_config(game)
        config.reorder(name, direction)
        self.validate_plugins(game, data, config)
        changes = config.changes(); self.backup_configs(changes)
        transaction = FileTransaction(self, [p for p,_ in changes])
        try:
            with self.db:
                for path,content in changes: atomic_write(path, content)
                self.event(game, 'Ordem alterada', name)
                transaction.commit_record()
        except Exception:
            transaction.rollback(); raise
        transaction.cleanup()

    def remove_mod(self, mod_id):
        mod = self.db.execute('SELECT * FROM mods WHERE id=?', (mod_id,)).fetchone()
        if not mod: raise ValueError('Mod não encontrado.')
        if mod['enabled']: self.set_enabled(mod_id, False)
        folder = self.root / 'mods' / mod_id
        trash = self.root / ('removed-' + uuid.uuid4().hex)
        folder.rename(trash)
        try:
            with self.db:
                for row in self.db.execute('SELECT name,mods FROM profiles WHERE game=?', (mod['game'],)).fetchall():
                    ids = [mid for mid in json.loads(row['mods']) if mid != mod_id]
                    self.db.execute('UPDATE profiles SET mods=? WHERE game=? AND name=?', (json.dumps(ids), mod['game'], row['name']))
                self.db.execute('DELETE FROM requirements WHERE mod=?', (mod_id,))
                self.db.execute('DELETE FROM files WHERE mod=?', (mod_id,))
                self.db.execute('DELETE FROM mods WHERE id=?', (mod_id,))
                self.event(mod['game'], 'Removido da biblioteca', mod['name'])
        except Exception:
            trash.rename(folder); raise
        shutil.rmtree(trash)

    def save_profile(self, game, name):
        if not name.strip(): raise ValueError('Informe um nome para o perfil.')
        ids = [m['id'] for m in self.mods(game) if m['enabled']]
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO profiles VALUES(?,?,?)', (game, name.strip(), json.dumps(ids)))
            self.event(game, 'Perfil salvo', name.strip())

    def profiles(self, game):
        return [x[0] for x in self.db.execute('SELECT name FROM profiles WHERE game=? ORDER BY name', (game,))]

    def restore_profile(self, game, name):
        row = self.db.execute('SELECT mods FROM profiles WHERE game=? AND name=?', (game, name)).fetchone()
        if not row: raise ValueError('Perfil não encontrado.')
        wanted = set(json.loads(row[0])); mods = self.mods(game)
        previous = {m['id'] for m in mods if m['enabled']}
        mods = [m for m in mods if m['id'] in previous | wanted]
        by_id = {m['id']: m for m in mods}
        owners = {p['name'].casefold(): m['id'] for m in mods for p in self.mod_plugins(m['id'])}
        ordered = []; visiting = set(); done = set()
        def visit(mid):
            if mid in visiting: raise ValueError('Dependências cíclicas no perfil.')
            if mid in done: return
            visiting.add(mid)
            for required in self.declared_requirements(mid):
                owner = next((m['id'] for m in mods if m['name'].casefold() == required.casefold() and m['id'] != mid), None)
                if owner: visit(owner)
            for plugin in self.mod_plugins(mid):
                for master in plugin['masters']:
                    owner = owners.get(master.casefold())
                    if owner and owner != mid and owner in by_id: visit(owner)
            visiting.remove(mid); done.add(mid); ordered.append(by_id[mid])
        for m in mods: visit(m['id'])
        changed = []
        try:
            for m in reversed(ordered):
                if m['id'] in previous - wanted: self.set_enabled(m['id'], False); changed.append((m['id'], True))
            for m in ordered:
                if m['id'] in wanted - previous: self.set_enabled(m['id'], True); changed.append((m['id'], False))
        except Exception as exc:
            failures = []
            for mid, state in reversed(changed):
                try: self.set_enabled(mid, state)
                except Exception as rollback: failures.append(str(rollback))
            if failures: raise ValueError(str(exc) + '\nRestauração incompleta: ' + '; '.join(failures)) from exc
            raise
        with self.db: self.event(game, 'Perfil restaurado', name)

    def history(self, game):
        return [dict(r) for r in self.db.execute('SELECT * FROM events WHERE game=? ORDER BY rowid DESC LIMIT 300', (game,))]
