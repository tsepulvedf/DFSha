"""Windows realpath: real filesystem race, coordinated without changing OS results."""
import os
import threading
from uuid import uuid4
from pathlib import Path
import pytest
from dfsha.datanode.blocks import EncryptedBlockStore


@pytest.mark.skipif(os.name != 'nt', reason='Specific Windows realpath namespace race')
def test_new_file_directory_created_during_resolution(tmp_path, monkeypatch, record_property):
    import ntpath
    store = EncryptedBlockStore(tmp_path/'blocks', os.urandom(32))
    file_id, block_id = str(uuid4()), str(uuid4())
    target = store.root/file_id/(block_id+'.blk')
    original = ntpath._getfinalpathname
    original_realpath = ntpath.realpath
    missing, created = threading.Event(), threading.Event()
    observed = []
    resolutions = []
    def creator():
        assert missing.wait(5)
        target.parent.mkdir()
        created.set()
    worker = threading.Thread(target=creator)
    worker.start()
    def resolve(path):
        try:
            return original(path)
        except OSError as exc:
            if str(path) == str(target):
                observed.append(exc.winerror)
                if not missing.is_set():
                    missing.set()
                    assert created.wait(5)
            raise
    monkeypatch.setattr(ntpath, '_getfinalpathname', resolve)
    def realpath(path, **kwargs):
        result = original_realpath(path, **kwargs)
        resolutions.append(str(result))
        return result
    monkeypatch.setattr(ntpath, 'realpath', realpath)
    try:
        actual = store.path(file_id, block_id)
        assert actual == target
    finally:
        worker.join(5)
        record_property('real_windows_errors', str(observed))
        record_property('root', str(store.root))
        record_property('resolved_paths', str(resolutions))


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction security check')
def test_junction_outside_block_root_is_denied(tmp_path):
    import _winapi
    from dfsha.common.domain import Fault
    store = EncryptedBlockStore(tmp_path/'blocks', os.urandom(32))
    external = tmp_path/'outside'
    external.mkdir()
    file_id = str(uuid4())
    junction = store.root/file_id
    _winapi.CreateJunction(str(external), str(junction))
    try:
        with pytest.raises(Fault, match='PERMISSION_DENIED'):
            store.path(file_id, str(uuid4()))
        assert not list(external.iterdir())
    finally:
        # Remove only the junction, never its target or a recursive tree.
        junction.rmdir()
