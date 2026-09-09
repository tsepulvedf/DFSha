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
    def __init__(self, connection):
        self.connection = connection

    def get(self, kind, identity):
        row = self.connection.execute('SELECT body FROM objects WHERE kind=? AND id=?',
                                      (kind, identity)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind):
        return [json.loads(r[0]) for r in self.connection.execute(
            'SELECT body FROM objects WHERE kind=? ORDER BY id', (kind,))]

    def children(self, parent):
        return [json.loads(r[0]) for r in self.connection.execute(
            "SELECT body FROM objects WHERE kind='node' AND parent=? AND live=1 ORDER BY name", (parent,))]

    def put(self, kind, value):
        self.connection.execute('INSERT INTO objects(kind,id,body,parent,name,live) VALUES(?,?,?,?,?,?) '
            'ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,parent=excluded.parent,'
            'name=excluded.name,live=excluded.live',
            (kind, value['id'], json.dumps(value, separators=(',', ':')), value.get('parent'),
             value.get('name'), int(value.get('alive', False))))

    def delete(self, kind, identity):
        self.connection.execute('DELETE FROM objects WHERE kind=? AND id=?', (kind, identity))


class SQLiteMetadataStore:
    def __init__(self, path):
        self.path = Path(path)

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
            yield SQLiteUnit(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
