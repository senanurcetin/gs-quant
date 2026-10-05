"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import datetime as dt
import json
import sqlite3
import uuid
import zlib
from contextlib import closing
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    headline    TEXT NOT NULL,
    request     BLOB NOT NULL
)
"""
SCHEMA_INDEX = 'CREATE INDEX IF NOT EXISTS runs_created ON runs (created_at DESC)'


class RunStore:
    """Saved analyses in a SQLite file. Only the request is stored: a run is recomputed when it is opened, so a saved run
    always reflects the current model code, and the file stays small (the request is compressed)."""

    def __init__(self, path: Path, max_runs: int = 200):
        self.path = Path(path)
        self.max_runs = max_runs
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self._connect()) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute(SCHEMA)
            db.execute(SCHEMA_INDEX)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _meta(row: sqlite3.Row) -> dict:
        return {
            'id': row['id'],
            'name': row['name'],
            'kind': row['kind'],
            'created_at': row['created_at'],
            'headline': json.loads(row['headline']),
        }

    def add(self, name: str, kind: str, request: dict, headline: dict) -> dict:
        run_id = uuid.uuid4().hex
        created = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        blob = zlib.compress(json.dumps(request, separators=(',', ':')).encode('utf-8'))
        with closing(self._connect()) as db, db:
            db.execute(
                'INSERT INTO runs (id, name, kind, created_at, headline, request) VALUES (?, ?, ?, ?, ?, ?)',
                (run_id, name, kind, created, json.dumps(headline), blob),
            )
            db.execute(
                'DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?)',
                (self.max_runs,),
            )
        return {'id': run_id, 'name': name, 'kind': kind, 'created_at': created, 'headline': headline}

    def list(self) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                'SELECT id, name, kind, created_at, headline FROM runs ORDER BY created_at DESC, rowid DESC'
            ).fetchall()
        return [self._meta(row) for row in rows]

    def get(self, run_id: str) -> Optional[dict]:
        """The run's metadata and its stored request, or None"""
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
        if row is None:
            return None
        return {**self._meta(row), 'request': json.loads(zlib.decompress(row['request']))}

    def delete(self, run_id: str) -> bool:
        with closing(self._connect()) as db, db:
            return db.execute('DELETE FROM runs WHERE id = ?', (run_id,)).rowcount > 0

    def ping(self) -> None:
        with closing(self._connect()) as db:
            db.execute('SELECT 1 FROM runs LIMIT 1').fetchall()
