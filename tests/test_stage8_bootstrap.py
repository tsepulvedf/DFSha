import os

import pytest

from dfsha.common.domain import Fault
from dfsha.common.protected import MetadataCipher
from dfsha.control.auth import initialize
from dfsha.control.metadata import SQLiteMetadataStore


def test_protected_bootstrap_is_idempotent_without_reset(tmp_path):
    metadata_key = tmp_path/'metadata.key'
    metadata_key.write_bytes(os.urandom(32))
    cfg = dict(sqlite_path=str(tmp_path/'data/metadata.sqlite'), key_path=str(tmp_path/'keys/master.key'),
               block_path=str(tmp_path/'blocks'), metadata_key_path=str(metadata_key))
    initialize(cfg, 'admin', 'initial-password')
    store = SQLiteMetadataStore(cfg['sqlite_path'], MetadataCipher.configured(cfg))
    with store.transaction() as tx:
        original = tx.all('user')
        system = tx.get('settings', 'system')
    initialize(cfg, 'admin', 'initial-password')
    with store.transaction() as tx:
        assert tx.all('user') == original and tx.get('settings', 'system') == system
    with pytest.raises(Fault, match='ALREADY_EXISTS'):
        initialize(cfg, 'admin', 'different-password')
    with store.transaction(True) as tx:
        user = tx.get('user', original[0]['id'])
        user.update(disabled=True, admin=False)
        tx.put('user', user)
    with pytest.raises(Fault, match='ALREADY_EXISTS'):
        initialize(cfg, 'admin', 'initial-password')
    with store.transaction() as tx:
        assert tx.get('user', user['id']) == user
    with store.transaction(True) as tx:
        tx.delete('user', user['id'])
    with pytest.raises(Fault, match='ALREADY_EXISTS'):
        initialize(cfg, 'admin', 'initial-password')
    with store.transaction() as tx:
        assert not tx.all('user')
