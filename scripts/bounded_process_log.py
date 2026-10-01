"""Drain native stderr/stdout without unbounded files or an unbounded pipe buffer."""
import logging
from logging.handlers import RotatingFileHandler
import threading


class BoundedProcessLog:
    def __init__(self, stream, path, max_bytes=2*1048576):
        self.stream = stream
        self.handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=2, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.thread = threading.Thread(target=self.drain, daemon=True, name='native-log-drain')
        self.thread.start()

    def drain(self):
        try:
            while line := self.stream.readline(8192):
                record = logging.LogRecord('native', logging.INFO, '', 0,
                    line.decode('utf-8', errors='replace').rstrip('\r\n'), (), None)
                self.handler.emit(record)
        finally:
            self.handler.close()
            self.stream.close()

    def close(self):
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError('Native output reader did not finish after process shutdown')
