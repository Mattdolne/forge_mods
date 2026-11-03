"""Filesystem rollback journal coordinated with the SQLite commit."""
from pathlib import Path
import json
import shutil
import uuid
from skyrim import atomic_write


class FileTransaction:
    def __init__(self, library, paths):
        self.library = library; self.id = uuid.uuid4().hex
        self.directory = library.root / 'transactions' / self.id
        self.directory.mkdir(parents=True)
        self.items = []
        for i, path in enumerate(dict.fromkeys(Path(p) for p in paths)):
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError('Destino inválido: ' + str(path))
            existed = path.exists()
            if existed: shutil.copy2(path, self.directory / str(i))
            self.items.append({'path': str(path), 'backup': str(i) if existed else None})
        atomic_write(self.directory / 'journal.json', json.dumps(self.items).encode())

    def rollback(self):
        for item in reversed(self.items):
            path = Path(item['path'])
            if path.is_symlink(): raise ValueError('Recuperação interrompida por link simbólico: ' + str(path))
            if item['backup'] is None: path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.directory / item['backup'], path)
        shutil.rmtree(self.directory)

    def commit_record(self):
        self.library.db.execute('INSERT INTO fs_commits VALUES(?)', (self.id,))

    def cleanup(self):
        shutil.rmtree(self.directory)
        with self.library.db: self.library.db.execute('DELETE FROM fs_commits WHERE id=?', (self.id,))

    @classmethod
    def recover(cls, library):
        for folder in (library.root / 'transactions').glob('*'):
            journal = folder / 'journal.json'
            if not journal.exists():
                shutil.rmtree(folder); continue  # No mutations precede a persisted journal.
            obj = object.__new__(cls); obj.library = library; obj.id = folder.name
            obj.directory = folder; obj.items = json.loads(journal.read_text())
            committed = library.db.execute('SELECT 1 FROM fs_commits WHERE id=?', (obj.id,)).fetchone()
            if committed: obj.cleanup()
            else: obj.rollback()
