"""Validated, streaming ZIP and 7z extraction. Never use native disk extraction."""
from contextlib import contextmanager
import ctypes as C
import ctypes.util
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

MAX_SIZE = 8 * 1024**3
MAX_ENTRIES = 100_000


@dataclass(frozen=True)
class Entry:
    name: str
    size: int
    directory: bool = False
    unsafe: bool = False


@contextmanager
def seven_reader(path):
    name = ctypes.util.find_library('archive')
    if not name:
        raise ValueError('Para importar 7z, instale libarchive pelo gerenciador de pacotes do Linux (Ubuntu/Debian: libarchive-dev).')
    try: lib = C.CDLL(name)
    except OSError as exc: raise ValueError('Não foi possível carregar libarchive para importar 7z.') from exc
    signatures = {
        'archive_read_new': (C.c_void_p, []),
        'archive_read_support_filter_all': (C.c_int, [C.c_void_p]),
        'archive_read_support_format_7zip': (C.c_int, [C.c_void_p]),
        'archive_read_open_filename': (C.c_int, [C.c_void_p, C.c_char_p, C.c_size_t]),
        'archive_read_next_header': (C.c_int, [C.c_void_p, C.POINTER(C.c_void_p)]),
        'archive_read_data': (C.c_ssize_t, [C.c_void_p, C.c_void_p, C.c_size_t]),
        'archive_read_free': (C.c_int, [C.c_void_p]),
        'archive_error_string': (C.c_char_p, [C.c_void_p]),
        'archive_entry_pathname': (C.c_char_p, [C.c_void_p]),
        'archive_entry_size': (C.c_int64, [C.c_void_p]),
        'archive_entry_filetype': (C.c_uint, [C.c_void_p]),
        'archive_entry_symlink': (C.c_char_p, [C.c_void_p]),
        'archive_entry_hardlink': (C.c_char_p, [C.c_void_p]),
        'archive_entry_is_encrypted': (C.c_int, [C.c_void_p]),
    }
    for function, (restype, args) in signatures.items():
        fn = getattr(lib, function); fn.restype = restype; fn.argtypes = args
    archive = lib.archive_read_new()
    if not archive: raise ValueError('Não foi possível iniciar a leitura do 7z.')
    def check(result):
        if result < 0:
            reason = lib.archive_error_string(archive)
            raise ValueError('Não foi possível ler o 7z (arquivo danificado, protegido por senha ou formato não suportado): ' + (os.fsdecode(reason) if reason else 'erro de leitura'))
        return result
    try:
        check(lib.archive_read_support_filter_all(archive))
        check(lib.archive_read_support_format_7zip(archive))
        check(lib.archive_read_open_filename(archive, os.fsencode(path), 10240))
        yield lib, archive, check
    finally: lib.archive_read_free(archive)


def entries(path, kind, content=False):
    if kind == 'zip':
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                mode = stat.S_IFMT(info.external_attr >> 16)
                entry = Entry(info.filename, info.file_size, info.is_dir(), mode not in {0, stat.S_IFREG, stat.S_IFDIR})
                def chunks(info=info):
                    with archive.open(info) as stream:
                        while data := stream.read(1024 * 1024): yield data
                yield entry, chunks() if content and not entry.directory else None
    else:
        with seven_reader(path) as (lib, archive, check):
            header = C.c_void_p()
            while True:
                result = check(lib.archive_read_next_header(archive, C.byref(header)))
                if result == 1: break  # ARCHIVE_EOF
                raw = lib.archive_entry_pathname(header)
                if raw is None: raise ValueError('O 7z contém uma entrada sem nome.')
                if lib.archive_entry_is_encrypted(header): raise ValueError('Arquivos 7z protegidos por senha ainda não são suportados.')
                mode = lib.archive_entry_filetype(header)
                unsafe = mode not in {stat.S_IFREG, stat.S_IFDIR} or lib.archive_entry_symlink(header) is not None or lib.archive_entry_hardlink(header) is not None
                entry = Entry(os.fsdecode(raw), lib.archive_entry_size(header), mode == stat.S_IFDIR, unsafe)
                def chunks():
                    buffer = C.create_string_buffer(1024 * 1024)
                    while length := check(lib.archive_read_data(archive, buffer, len(buffer))):
                        yield buffer.raw[:length]
                yield entry, chunks() if content and not entry.directory else None


def safe_path(entry):
    name = entry.name.replace('\\', '/')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or ':' in name or '\0' in name or (not path.parts and not entry.directory):
        raise ValueError('O arquivo compactado contém um caminho inseguro: ' + repr(entry.name))
    if entry.unsafe: raise ValueError('Links simbólicos, hard links e arquivos especiais não são aceitos: ' + entry.name)
    if entry.size < 0: raise ValueError('Tamanho inválido no arquivo compactado.')
    return path


def extract_archive(archive, destination):
    archive, destination = Path(archive), Path(destination)
    if zipfile.is_zipfile(archive): kind = 'zip'
    else:
        with archive.open('rb') as stream: magic = stream.read(6)
        if magic != b"7z\xbc\xaf\x27\x1c": raise ValueError('Formato inválido ou não suportado. Selecione um arquivo ZIP ou 7z válido.')
        kind = '7z'
    manifest, paths = [], []
    total = 0
    for entry, _ in entries(archive, kind):
        if len(manifest) >= MAX_ENTRIES: raise ValueError('Limite de 100 mil entradas por mod.')
        path = safe_path(entry)
        manifest.append(entry)
        if not entry.directory:
            total += entry.size; paths.append(path)
            if total > MAX_SIZE: raise ValueError('Limite de 8 GiB descompactados por mod.')
    if not paths: raise ValueError('O arquivo está vazio.')
    prefix = 0
    if all(p.parts[0].casefold() == 'data' for p in paths): prefix = 1
    elif all(len(p.parts) >= 3 and p.parts[0] == paths[0].parts[0] and p.parts[1].casefold() == 'data' for p in paths): prefix = 2
    seen = set(); files = []
    for path in paths:
        parts = path.parts[prefix:]
        if not parts: raise ValueError('Nome de arquivo inválido na raiz de Data.')
        relative = '/'.join(parts)
        if relative.casefold() in seen: raise ValueError('Arquivos duplicados por diferença de maiúsculas/minúsculas.')
        seen.add(relative.casefold()); files.append(parts)
    index, file_index, actual_total = 0, 0, 0
    for entry, chunks in entries(archive, kind, content=True):
        if index >= len(manifest) or entry != manifest[index]: raise ValueError('O arquivo compactado foi alterado durante a importação.')
        index += 1
        if entry.directory: continue
        target = destination.joinpath(*files[file_index]); file_index += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with target.open('xb') as out:
            for block in chunks:
                written += len(block); actual_total += len(block)
                if written > entry.size or actual_total > MAX_SIZE: raise ValueError('Conteúdo descompactado excede o tamanho declarado ou o limite de 8 GiB.')
                out.write(block)
        if written != entry.size: raise ValueError('Conteúdo truncado no arquivo compactado: ' + entry.name)
    if index != len(manifest): raise ValueError('O arquivo compactado foi alterado durante a importação.')
