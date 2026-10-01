"""At-rest protection: cryptographic rejection, identity binding and real HA."""
import json
import os
import sqlite3

import pytest

from dfsha.common.domain import Fault
from dfsha.common.protected import MetadataCipher, MAGIC
from dfsha.control.metadata import SQLiteMetadataStore


def test_metadata_cipher_rejects_tamper_wrong_key_and_identity():
    cipher = MetadataCipher(os.urandom(32))
    raw = cipher.seal(b'sensitive metadata', b'user:alice')
    assert cipher.open(raw, b'user:alice') == b'sensitive metadata'
    assert raw != cipher.seal(b'sensitive metadata', b'user:alice')
    for data, context, decoder in (
        (raw[:-1]+bytes([raw[-1] ^ 1]), b'user:alice', cipher),
        (raw, b'user:bob', cipher),
        (raw, b'user:alice', MetadataCipher(os.urandom(32))),
        (b'sensitive metadata', b'user:alice', cipher),
    ):
        with pytest.raises(Fault, match='DATA_LOSS'):
            decoder.open(data, context)


def test_sqlite_encrypted_bodies_and_names_survive_restart(tmp_path):
    cipher = MetadataCipher(os.urandom(32))
    store = SQLiteMetadataStore(tmp_path/'inventory.sqlite3', cipher)
    store.initialize()
    with store.transaction(True) as tx:
        for name in ('zeta-secret', 'alfa-secret'):
            tx.put('node', dict(id=name[:4], name=name, parent='parent', alive=True))
    with store.transaction() as tx:
        assert [n['name'] for n in tx.children('parent')] == ['alfa-secret', 'zeta-secret']
    with sqlite3.connect(store.path) as db:
        rows = db.execute('SELECT body,name FROM objects').fetchall()
        assert all(body.startswith(MAGIC) and 'secret' not in name for body, name in rows)
        with pytest.raises(sqlite3.IntegrityError):
            with store.transaction(True) as tx:
                tx.put('node', dict(id='duplicate', name='zeta-secret', parent='parent', alive=True))
    reopened = SQLiteMetadataStore(store.path, MetadataCipher(os.urandom(32)))
    with reopened.transaction() as tx, pytest.raises(Fault, match='DATA_LOSS'):
        tx.get('node', 'zeta')
    # Both main database and live WAL store the protected representation.
    with store.connect() as reader:
        reader.execute('BEGIN')
        reader.execute('SELECT count(*) FROM objects').fetchone()
        with store.transaction(True) as tx:
            tx.put('user', dict(id='u1', username='wal-sensitive-value'))
        wal = store.path.with_name(store.path.name+'-wal')
        assert wal.exists() and b'wal-sensitive-value' not in wal.read_bytes()
    assert b'zeta-secret' not in store.path.read_bytes()


def test_protected_metadata_real_ha(run_dir, tmp_path, record_property):
    from ha_runtime import HACluster
    from dfsha.control.etcd_metadata import EtcdMetadataStore
    from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb
    from dfsha.common.etcd_probe_client import prefix_end
    with HACluster(run_dir/'protected-ha', protected=True) as lab:
        first, second = lab.client(0), lab.client(1)
        store = lab.metadata()
        try:
            first.mkdir('/home/admin/private-name')
            assert second.stat('/home/admin/private-name').object_id
            source = tmp_path/'source'
            source.write_bytes(b'authenticated protected storage'*1000)
            first.send(source, '/home/admin/private-name/data')
            second.receive('/home/admin/private-name/data', tmp_path/'output')
            assert (tmp_path/'output').read_bytes() == source.read_bytes()
            prefix = store.prefix+b'pages/'
            pages = store.rpc(store.kv.Range, pb.RangeRequest(key=prefix, range_end=prefix_end(prefix))).kvs
            assert pages and all(p.value.startswith(MAGIC) for p in pages)
            assert all(b'private-name' not in p.value for p in pages)
            wrong_cfg = dict(store.cfg)
            key = tmp_path/'wrong.key'
            key.write_bytes(os.urandom(32))
            wrong_cfg['metadata_key_path'] = str(key)
            wrong = EtcdMetadataStore(wrong_cfg)
            try:
                with pytest.raises(Fault, match='DATA_LOSS'), wrong.transaction():
                    pytest.fail('Wrong metadata key accepted')
            finally:
                wrong.channel.close()
            record_property('encrypted_pages_verified', len(pages))
            record_property('topology', '3CN/3etcd/3DN; real TLS and shared encrypted authority')
        finally:
            first.shutdown()
            second.shutdown()
            store.channel.close()
