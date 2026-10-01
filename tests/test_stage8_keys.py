"""Key separation, immutable old-version reads and encrypted backup recovery."""
import hashlib
import os

import pytest

from dfsha.common.backup_archive import create_archive, restore_archive
from dfsha.common.domain import Fault, uid
from dfsha.datanode.blocks import EncryptedBlockStore
from dfsha.v1.common_pb2 import BlockRef


def test_old_key_reads_new_active_key_and_ciphertext_copy(tmp_path):
    old, new = os.urandom(32), os.urandom(32)
    original = EncryptedBlockStore(tmp_path/'node-a', old)
    block = BlockRef(file_id=uid(), block_version_id=uid(), size_bytes=7,
                     plaintext_sha256=hashlib.sha256(b'olddata').digest())
    size, digest = original.put(block, [b'olddata'])
    raw = original.path(block.file_id, block.block_version_id).read_bytes()
    rotated = EncryptedBlockStore(tmp_path/'node-a', new, [old])
    assert b''.join(rotated.read_verified(block)) == b'olddata'
    assert rotated.object_key_id(block) == hashlib.sha256(old).hexdigest()
    assert rotated.path(block.file_id, block.block_version_id).read_bytes() == raw
    replica = EncryptedBlockStore(tmp_path/'node-b', new, [old])
    replica.import_ciphertext(block, [raw], size, digest)
    assert b''.join(replica.read_verified(block)) == b'olddata'
    no_old = EncryptedBlockStore(tmp_path/'node-b', new)
    with pytest.raises(Fault, match='DATA_LOSS'):
        next(no_old.read_verified(block))
    next_block = BlockRef(file_id=block.file_id, block_version_id=uid(), size_bytes=7,
                          plaintext_sha256=block.plaintext_sha256)
    rotated.put(next_block, [b'olddata'])
    assert rotated.object_key_id(next_block) == hashlib.sha256(new).hexdigest()


def test_backup_requires_key_and_recovers_independent_environment(tmp_path):
    source = tmp_path/'private.key'
    value = os.urandom(32)
    source.write_bytes(value)
    data = tmp_path/'data'
    data.write_bytes(b'private-backup-content'*20000)
    key = os.urandom(32)
    archive = tmp_path/'backup'
    result = create_archive(archive, key, [('secrets/content.key', source), ('payload/data', data)],
                            metadata={'policy': 'R3/W2'})
    assert result['files'] == 2
    with pytest.raises(Fault, match='DATA_LOSS'):
        restore_archive(archive, tmp_path/'unauthorized', os.urandom(32))
    assert not (tmp_path/'unauthorized').exists()
    metadata = restore_archive(archive, tmp_path/'restored', key)
    assert metadata['policy'] == 'R3/W2'
    assert (tmp_path/'restored/secrets/content.key').read_bytes() == value
    assert (tmp_path/'restored/payload/data').read_bytes() == data.read_bytes()
    assert (tmp_path/'restored/RESTORE_COMPLETE').exists()
    obj = next((archive/'objects').rglob('*.blk'))
    raw = bytearray(obj.read_bytes())
    raw[-1] ^= 1
    obj.write_bytes(raw)
    with pytest.raises(Fault, match='DATA_LOSS'):
        restore_archive(archive, tmp_path/'damaged', key)
    assert not (tmp_path/'damaged/RESTORE_COMPLETE').exists()
