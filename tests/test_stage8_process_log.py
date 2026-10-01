import subprocess
import sys

from bounded_process_log import BoundedProcessLog
from runtime import PROCESS_FLAGS


def test_native_output_is_drained_and_retention_bounded(tmp_path):
    process = subprocess.Popen([sys.executable, '-c', "for n in range(1000): print('safe-native-message-' + str(n) + ':' + 'x'*100)"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS)
    log = BoundedProcessLog(process.stdout, tmp_path/'native.log', max_bytes=1024)
    assert process.wait(timeout=10) == 0
    log.close()
    files = list(tmp_path.glob('native.log*'))
    assert len(files) == 3 and all(p.stat().st_size <= 1024 for p in files)
    assert b'safe-native-message-999:' in (tmp_path/'native.log').read_bytes()
