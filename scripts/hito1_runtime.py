"""Arranque/parada de procesos H1 aislados para pruebas reproducibles."""
import json
from pathlib import Path
import subprocess
import sys
from runtime import ROOT, PROCESS_FLAGS, wait_until, free_port


class Hito1Process:
    def __init__(self, directory, certs, block_size=4194304, capacity=17179869184):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.certs = Path(certs)
        self.config = self.directory / 'config.toml'
        self.ready = self.directory / 'ready.json'
        self.stop_file = self.directory / 'stop'
        self.faults = self.directory / 'faults'
        self.faults.mkdir(exist_ok=True)
        self.target = f'localhost:{free_port()}'
        self.block_size, self.capacity = block_size, capacity
        self.process = None
        self.write_config()

    def write_config(self):
        text = (ROOT / 'deploy/monolith.example.toml').read_text(encoding='utf-8')
        replacements = {
            '127.0.0.1:17443': '127.0.0.1:' + self.target.rsplit(':', 1)[1],
            '127.0.0.1:17445': '127.0.0.1:0',
            '.runtime/certs': self.certs.resolve().as_posix(),
            '.runtime/hito1': self.directory.resolve().as_posix(),
            'localhost:17443': self.target,
            'block_size_bytes = 4194304': f'block_size_bytes = {self.block_size}',
            'capacity_bytes = 17179869184': f'capacity_bytes = {self.capacity}',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = text.replace('[client]', 'test_fault_dir = ' + json.dumps(self.faults.resolve().as_posix()) + '\n\n[client]')
        self.config.write_text(text, encoding='utf-8')

    def initialize(self):
        result = subprocess.run([sys.executable, '-m', 'dfsha.admin', 'init', '--config', str(self.config),
            '--username', 'admin', '--password-stdin'], input='development-password\n', text=True,
            capture_output=True, cwd=ROOT, creationflags=PROCESS_FLAGS)
        if result.returncode:
            raise RuntimeError(result.stderr)

    def start(self):
        self.write_config()
        self.ready.unlink(missing_ok=True)
        self.stop_file.unlink(missing_ok=True)
        self.log = (self.directory / 'server.log').open('ab')
        self.process = subprocess.Popen([sys.executable, '-m', 'dfsha.control.server', '--config', str(self.config),
            '--ready-file', str(self.ready), '--stop-file', str(self.stop_file)], cwd=ROOT,
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS)

        def ready():
            if self.process.poll() is not None:
                self.log.close()
                raise RuntimeError((self.directory / 'server.log').read_text(encoding='utf-8'))
            if self.ready.exists():
                try:
                    return json.loads(self.ready.read_text(encoding='utf-8'))
                except json.JSONDecodeError:
                    return None
        self.info = wait_until(ready)
        return self

    def stop(self):
        if self.process and self.process.poll() is None:
            self.stop_file.touch()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if hasattr(self, 'log'):
            self.log.close()

    def __enter__(self):
        self.initialize()
        return self.start()

    def __exit__(self, *args):
        self.stop()
