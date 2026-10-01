"""Repositorio SQLite autoritativo. UoW cortas; jamás se retienen durante streams."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Protocol
from dfsha.common.ports import MetadataStore


class UnitOfWork(Protocol):
    def get(self, kind, identity): ...
    def all(self, kind): ...
    def put(self, kind, value): ...
    def delete(self, kind, identity): ...


class SQLiteUnit:
    def __init__(self, connection, cipher=None):
        self.connection, self.cipher = connection, cipher

    def decode(self, kind, identity, body):
        from dfsha.common.domain import need
        from dfsha.common.protected import MAGIC
        need(self.cipher is not None or not isinstance(body, bytes) or not body.startswith(MAGIC), 'DATA_LOSS')
        if self.cipher:
            body = self.cipher.open(body, (kind+'\0'+identity).encode())
        return json.loads(body)

    def get(self, kind, identity):
        row = self.connection.execute('SELECT body FROM objects WHERE kind=? AND id=?',
                                      (kind, identity)).fetchone()
        return self.decode(kind, identity, row[0]) if row else None

    def all(self, kind):
        return [self.decode(kind, r[0], r[1]) for r in self.connection.execute(
            'SELECT id,body FROM objects WHERE kind=? ORDER BY id', (kind,))]

    def children(self, parent):
        return sorted([self.decode('node', r[0], r[1]) for r in self.connection.execute(
            "SELECT id,body FROM objects WHERE kind='node' AND parent=? AND live=1", (parent,))], key=lambda v: v['name'])

    def put(self, kind, value):
        body = json.dumps(value, separators=(',', ':'))
        name = value.get('name')
        if self.cipher:
            body = self.cipher.seal(body.encode(), (kind+'\0'+value['id']).encode())
            name = self.cipher.address(('name\0'+name).encode()) if name is not None else None
        self.connection.execute('INSERT INTO objects(kind,id,body,parent,name,live) VALUES(?,?,?,?,?,?) '
            'ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,parent=excluded.parent,'
            'name=excluded.name,live=excluded.live',
            (kind, value['id'], body, value.get('parent'), name, int(value.get('alive', False))))

    def delete(self, kind, identity):
        self.connection.execute('DELETE FROM objects WHERE kind=? AND id=?', (kind, identity))


class SQLiteMetadataStore:
    def __init__(self, path, cipher=None):
        self.path, self.cipher = Path(path), cipher

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('CREATE TABLE IF NOT EXISTS objects(kind TEXT NOT NULL,id TEXT NOT NULL,'
                'body TEXT NOT NULL,parent TEXT,name TEXT,live INTEGER,PRIMARY KEY(kind,id));'
                "CREATE UNIQUE INDEX IF NOT EXISTS names ON objects(parent,name) WHERE kind='node' AND live=1;"
                'CREATE INDEX IF NOT EXISTS children ON objects(kind,parent,live,name);')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @contextmanager
    def transaction(self, write=False):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield SQLiteUnit(db, self.cipher)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
