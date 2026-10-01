"""Encrypted offline backup archive, reusing authenticated bounded block records.

Caller must establish a consistent maintenance window. This module does not
claim consistency for live source files or supply filesystem snapshotting.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from dfsha.common.domain import CHUNK, asdict, proto, uid, need
from dfsha.common.protected import MetadataCipher
from dfsha.control.auth import protect
from dfsha.datanode.blocks import EncryptedBlockStore, containment_path
from dfsha.v1.common_pb2 import BlockRef


def create_archive(directory, key, sources, metadata=None):
    directory = Path(directory).resolve()
    need(not directory.exists(), 'ALREADY_EXISTS')
    directory.mkdir(parents=True)
    protect(directory)
    cipher = MetadataCipher(key)
    store = EncryptedBlockStore(directory/'objects', key)
    entries, names = [], set()
    for name, source in sources:
        parts = PurePosixPath(name)
        need(not parts.is_absolute() and '..' not in parts.parts and '\\' not in name
             and ':' not in name and name not in names and name not in ('', '.'), 'INVALID_ARGUMENT')
        names.add(name)
        need(len(names) <= 100000, 'LIMIT_EXCEEDED')
        source = Path(source)
        with source.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').digest()
            length = stream.tell()
            # file_digest may bypass file object's logical position.
            length = os.fstat(stream.fileno()).st_size
            stream.seek(0)
            block = BlockRef(file_id=uid(), block_version_id=uid(), size_bytes=length,
                             plaintext_sha256=digest)
            stored, cipher_digest = store.put(block, iter(lambda: stream.read(CHUNK), b''))
        entries.append(dict(path=name, block=asdict(block), stored=stored, ciphertext_sha256=cipher_digest.hex()))
    payload = json.dumps(dict(schema=1, entries=entries, metadata=metadata or {}),
                         separators=(',', ':')).encode()
    need(len(payload) <= 16*1048576, 'LIMIT_EXCEEDED')
    temporary = directory/'manifest.pending'
    with temporary.open('xb') as out:
        out.write(cipher.seal(payload, b'dfsha-backup-manifest-v1'))
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, directory/'manifest.sealed')
    return dict(files=len(entries), manifest_sha256=hashlib.sha256(payload).hexdigest(),
                archive_key_id=cipher.key_id.hex())


def restore_archive(directory, destination, key):
    directory, destination = Path(directory).resolve(), Path(destination).resolve()
    need(not destination.exists(), 'ALREADY_EXISTS')
    manifest = directory/'manifest.sealed'
    need(manifest.stat().st_size <= 16*1048576+68, 'LIMIT_EXCEEDED')
    payload = MetadataCipher(key).open(manifest.read_bytes(), b'dfsha-backup-manifest-v1')
    document = json.loads(payload)
    need(document['schema'] == 1 and len(document['entries']) <= 100000, 'DATA_LOSS')
    store = EncryptedBlockStore(directory/'objects', key)
    names = set()
    for entry in document['entries']:
        name = entry['path']
        parts = PurePosixPath(name)
        need(not parts.is_absolute() and '..' not in parts.parts and '\\' not in name and ':' not in name
             and name not in ('', '.') and name not in names, 'DATA_LOSS')
        names.add(name)
    destination.mkdir(parents=True)
    protect(destination)
    for entry in document['entries']:
        target = destination/entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        need(containment_path(target.resolve()).is_relative_to(containment_path(destination)), 'PERMISSION_DENIED')
        block = proto(BlockRef, entry['block'])
        encrypted_path = store.path(block.file_id, block.block_version_id)
        with encrypted_path.open('rb') as stream:
            need(os.fstat(stream.fileno()).st_size == entry['stored'] and
                 hashlib.file_digest(stream, 'sha256').hexdigest() == entry['ciphertext_sha256'], 'DATA_LOSS')
        # read_verified validates the entire object before yielding plaintext.
        with target.open('xb') as out:
            for piece in store.read_verified(block):
                out.write(piece)
            out.flush()
            os.fsync(out.fileno())
        protect(target)
    (destination/'RESTORE_COMPLETE').write_text(hashlib.sha256(payload).hexdigest()+'\n', encoding='ascii')
    return document['metadata']
