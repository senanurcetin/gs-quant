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
import os
import shutil
import sqlite3
import time
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
SCHEMA_PORTFOLIOS = """
CREATE TABLE IF NOT EXISTS portfolios (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    name_key    TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    definition  TEXT NOT NULL
)
"""
SCHEMA_PRICES = """
CREATE TABLE IF NOT EXISTS prices (
    provider    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    series      BLOB NOT NULL,
    PRIMARY KEY (provider, symbol)
)
"""

# The database is versioned with SQLite's user_version. A change to the tables is a new entry here, never an edit of an old
# one: a database is brought up one version at a time, whatever release created it. Version 0 is a new file, or one made
# before versions were kept: its tables are created only if they are missing, so both are handled by the same steps.
MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (SCHEMA, SCHEMA_INDEX)),
    (2, (SCHEMA_PORTFOLIOS,)),
    (3, (SCHEMA_PRICES,)),
)
SCHEMA_VERSION = MIGRATIONS[-1][0]
MIGRATION_ATTEMPTS = 100
MAX_PRICE_SERIES = 300  # the saved copies of prices: the least recently fetched are dropped past this


class StoreFull(Exception):
    """No room for another item: the caller should delete one first"""


class StoreVersionError(Exception):
    """The database was written by a newer release than this one: it is left alone"""


class RunStore:
    """Saved analyses in a SQLite file. Only the request is stored: a run is recomputed when it is opened, so a saved run
    always reflects the current model code, and the file stays small (the request is compressed)."""

    def __init__(self, path: Path, max_runs: int = 200, max_portfolios: int = 50):
        self.path = Path(path)
        self.max_runs = max_runs
        self.max_portfolios = max_portfolios
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for attempt in range(MIGRATION_ATTEMPTS):
            try:
                self._migrate()
                break
            except sqlite3.OperationalError as e:
                # a second process starting at the same moment holds the lock: SQLite does not wait for every statement
                if 'locked' not in str(e) or attempt == MIGRATION_ATTEMPTS - 1:
                    raise
                time.sleep(0.1)

    def _migrate(self) -> None:
        """Brings the file up to SCHEMA_VERSION, copying it aside first if it holds anything and has to change"""
        with closing(self._connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            current = db.execute('PRAGMA user_version').fetchone()[0]
            if current > SCHEMA_VERSION:
                raise StoreVersionError(
                    f'{self.path} was written by a newer version of this application (database version {current}, '
                    f'this one understands {SCHEMA_VERSION}). Upgrade the application, or use another file.'
                )
            if current == SCHEMA_VERSION:
                return
            if db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]:
                db.close()
                backup = f'{self.path}.bak-v{current}'
                if not os.path.exists(backup):  # the first copy is the one that matters: never replace it
                    shutil.copy2(self.path, backup)
        with closing(self._connect()) as db:
            db.isolation_level = (
                None  # explicit transactions: the steps and the new version are applied together or not at all
            )
            db.execute('BEGIN IMMEDIATE')
            try:
                current = db.execute('PRAGMA user_version').fetchone()[0]  # another process may have got here first
                for version, statements in MIGRATIONS:
                    if version > current:
                        for statement in statements:
                            db.execute(statement)
                        db.execute(f'PRAGMA user_version = {version}')
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def schema_version(self) -> int:
        with closing(self._connect()) as db:
            return db.execute('PRAGMA user_version').fetchone()[0]

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

    # ---- named portfolios: what to load, not what was found (prices are fetched fresh when one is opened)

    @staticmethod
    def _portfolio_meta(row: sqlite3.Row) -> dict:
        definition = json.loads(row['definition'])
        return {
            'id': row['id'],
            'name': row['name'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'symbols': definition['symbols'],
            'base': definition.get('base'),
            'benchmark': definition.get('benchmark'),
        }

    def save_portfolio(self, name: str, definition: dict) -> tuple[dict, bool]:
        """Keeps a portfolio under a name, replacing the one that has it (names are compared ignoring case)

        :return: the portfolio's metadata, and whether it is new
        """
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        key = name.casefold()
        text = json.dumps(definition, separators=(',', ':'))
        with closing(self._connect()) as db, db:
            existing = db.execute('SELECT id FROM portfolios WHERE name_key = ?', (key,)).fetchone()
            if existing is not None:
                db.execute(
                    'UPDATE portfolios SET name = ?, updated_at = ?, definition = ? WHERE id = ?',
                    (name, now, text, existing['id']),
                )
                portfolio_id, created = existing['id'], False
            else:
                if db.execute('SELECT COUNT(*) FROM portfolios').fetchone()[0] >= self.max_portfolios:
                    raise StoreFull(f'You can keep at most {self.max_portfolios} portfolios: delete one first')
                portfolio_id, created = uuid.uuid4().hex, True
                db.execute(
                    'INSERT INTO portfolios (id, name, name_key, created_at, updated_at, definition) VALUES (?, ?, ?, ?, ?, ?)',
                    (portfolio_id, name, key, now, now, text),
                )
            row = db.execute('SELECT * FROM portfolios WHERE id = ?', (portfolio_id,)).fetchone()
        return self._portfolio_meta(row), created

    def list_portfolios(self) -> 'list[dict]':  # quoted: the method named list shadows the type in this class
        with closing(self._connect()) as db:
            rows = db.execute('SELECT * FROM portfolios ORDER BY name_key').fetchall()
        return [self._portfolio_meta(row) for row in rows]

    def get_portfolio(self, portfolio_id: str) -> Optional[dict]:
        """The portfolio's metadata and its definition, or None"""
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM portfolios WHERE id = ?', (portfolio_id,)).fetchone()
        if row is None:
            return None
        return {**self._portfolio_meta(row), 'definition': json.loads(row['definition'])}

    def delete_portfolio(self, portfolio_id: str) -> bool:
        with closing(self._connect()) as db, db:
            return db.execute('DELETE FROM portfolios WHERE id = ?', (portfolio_id,)).rowcount > 0

    # ---- the last prices fetched from a provider: what is shown, with its date, when the provider cannot be reached

    def save_prices(self, provider: str, symbol: str, series: dict) -> None:
        """Keeps the latest series of a symbol ({'currency', 'dates', 'values'}), replacing the previous one"""
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        blob = zlib.compress(json.dumps(series, separators=(',', ':')).encode('utf-8'))
        with closing(self._connect()) as db, db:
            db.execute(
                'INSERT INTO prices (provider, symbol, fetched_at, series) VALUES (?, ?, ?, ?) '
                'ON CONFLICT (provider, symbol) DO UPDATE SET fetched_at = excluded.fetched_at, series = excluded.series',
                (provider, symbol, now, blob),
            )
            db.execute(
                'DELETE FROM prices WHERE rowid NOT IN (SELECT rowid FROM prices ORDER BY fetched_at DESC, rowid DESC LIMIT ?)',
                (MAX_PRICE_SERIES,),
            )

    def load_prices(self, provider: str, symbol: str) -> Optional[tuple[dict, str]]:
        """The saved series of a symbol and when it was fetched (UTC, ISO format), or None"""
        with closing(self._connect()) as db:
            row = db.execute(
                'SELECT fetched_at, series FROM prices WHERE provider = ? AND symbol = ?', (provider, symbol)
            ).fetchone()
        if row is None:
            return None
        return json.loads(zlib.decompress(row['series'])), row['fetched_at']

    def ping(self) -> None:
        with closing(self._connect()) as db:
            db.execute('SELECT 1 FROM runs LIMIT 1').fetchall()
