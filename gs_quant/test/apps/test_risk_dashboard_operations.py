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

import sqlite3
import threading

import pytest

pytest.importorskip('starlette')

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import limits, store as store_module  # noqa: E402
from gs_quant.apps.risk_dashboard.app import ApiGuardMiddleware, create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.limits import FailureLock, SlidingWindowLimiter, client_of  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402
from gs_quant.apps.risk_dashboard.store import SCHEMA_VERSION, RunStore, StoreVersionError  # noqa: E402

TOKEN = 'a-long-enough-test-token'


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ----------------------------------------------------------------------------------------------------------------------
# Limits
# ----------------------------------------------------------------------------------------------------------------------


class TestSlidingWindowLimiter:
    def test_allows_the_limit_then_says_how_long_to_wait(self):
        clock = Clock()
        limiter = SlidingWindowLimiter(3, 60, clock)

        assert [limiter.hit('a') for _ in range(3)] == [None, None, None]
        clock.advance(20)
        assert limiter.hit('a') == pytest.approx(40)  # the oldest request leaves the window in 40 seconds

    def test_the_window_slides(self):
        clock = Clock()
        limiter = SlidingWindowLimiter(2, 60, clock)
        limiter.hit('a')
        clock.advance(30)
        limiter.hit('a')

        assert limiter.hit('a') is not None
        clock.advance(31)  # the first has gone, the second has not
        assert limiter.hit('a') is None and limiter.hit('a') is not None

    def test_callers_are_counted_separately(self):
        limiter = SlidingWindowLimiter(1, 60, Clock())

        assert limiter.hit('a') is None and limiter.hit('b') is None
        assert limiter.hit('a') is not None and limiter.hit('b') is not None

    def test_a_refused_request_is_not_counted(self):
        clock = Clock()
        limiter = SlidingWindowLimiter(1, 60, clock)
        limiter.hit('a')
        for _ in range(100):
            limiter.hit('a')
        clock.advance(60)

        assert limiter.hit('a') is None  # hammering did not extend the wait

    def test_what_is_remembered_is_bounded(self, monkeypatch):
        monkeypatch.setattr(limits, 'MAX_TRACKED_CLIENTS', 50)
        limiter = SlidingWindowLimiter(5, 60, Clock())

        for i in range(500):
            limiter.hit(f'client {i}')

        assert len(limiter._hits) == 50


class TestFailureLock:
    def test_locks_after_the_limit_and_unlocks_after_the_lockout(self):
        clock = Clock()
        lock = FailureLock(3, 300, clock)

        for _ in range(2):
            lock.record('a')
            assert lock.locked('a') is None
        lock.record('a')
        assert lock.locked('a') == pytest.approx(300)
        clock.advance(100)
        assert lock.locked('a') == pytest.approx(200)
        clock.advance(201)
        assert lock.locked('a') is None

    def test_other_callers_are_not_locked(self):
        lock = FailureLock(1, 300, Clock())
        lock.record('a')

        assert lock.locked('a') is not None and lock.locked('b') is None

    def test_old_failures_stop_counting(self):
        clock = Clock()
        lock = FailureLock(2, 300, clock)
        lock.record('a')
        clock.advance(299)
        lock.record('a')
        assert lock.locked('a') is not None
        clock.advance(2)  # the first expired: one failure counts
        assert lock.locked('a') is None

    def test_what_is_remembered_is_bounded(self, monkeypatch):
        monkeypatch.setattr(limits, 'MAX_TRACKED_CLIENTS', 20)
        lock = FailureLock(5, 300, Clock())

        for i in range(200):
            lock.record(f'client {i}')

        assert len(lock._failures) == 20


class TestClientOf:
    @staticmethod
    def scope(headers=(), client=('10.0.0.5', 1234)):
        # an ASGI server lowercases header names
        return {'headers': [(k.lower().encode(), v.encode()) for k, v in headers], 'client': client}

    def test_the_connection_address_when_no_proxy_is_trusted(self):
        scope = self.scope([('X-Forwarded-For', '1.2.3.4')])

        assert client_of(scope, trust_proxy=False) == '10.0.0.5'

    def test_the_address_the_proxy_appended_when_it_is_trusted(self):
        # a caller can write the first entries; only the last one was written by the proxy
        scope = self.scope([('X-Forwarded-For', '6.6.6.6, 7.7.7.7, 203.0.113.9')])

        assert client_of(scope, trust_proxy=True) == '203.0.113.9'

    def test_falls_back_without_the_header_or_the_client(self):
        assert client_of(self.scope(), trust_proxy=True) == '10.0.0.5'
        assert client_of(self.scope(client=None), trust_proxy=False) == 'unknown'
        assert client_of(self.scope([('X-Forwarded-For', ' , ')]), trust_proxy=True) == '10.0.0.5'

    def test_a_long_header_is_cut(self):
        assert len(client_of(self.scope([('X-Forwarded-For', 'x' * 500)]), trust_proxy=True)) == 64


# ----------------------------------------------------------------------------------------------------------------------
# The guard in front of an application
# ----------------------------------------------------------------------------------------------------------------------


def guarded(clock, **options) -> TestClient:
    async def ok(request):
        return JSONResponse({'ok': True})

    inner = Starlette(routes=[Route('/api/x', ok), Route('/api/health', ok), Route('/page', ok)])
    return TestClient(ApiGuardMiddleware(inner, clock=clock, **options))


class TestGuard:
    def test_requests_beyond_the_limit_get_a_429_with_retry_after(self):
        clock = Clock()
        client = guarded(clock, rate_limit=3)

        assert [client.get('/api/x').status_code for _ in range(3)] == [200, 200, 200]
        refused = client.get('/api/x')

        assert refused.status_code == 429 and refused.json() == {'error': 'Too many requests: try again in 60 seconds'}
        assert refused.headers['retry-after'] == '60' and 'x-request-id' in refused.headers
        clock.advance(61)
        assert client.get('/api/x').status_code == 200

    def test_probes_and_pages_are_never_limited(self):
        client = guarded(Clock(), rate_limit=1, max_auth_failures=1, api_token=TOKEN)

        for _ in range(20):
            assert client.get('/api/health').status_code == 200
            assert client.get('/page').status_code == 200

    def test_zero_means_no_limit(self):
        client = guarded(Clock(), rate_limit=0, max_auth_failures=0, api_token=TOKEN)

        statuses = {
            client.get('/api/x', headers={'Authorization': 'Bearer wrong-token-of-length'}).status_code
            for _ in range(50)
        }

        assert statuses == {401}

    def test_repeated_wrong_tokens_lock_the_caller_out_even_for_the_right_one(self):
        clock = Clock()
        client = guarded(clock, api_token=TOKEN, max_auth_failures=3, lockout_seconds=300)
        wrong = {'Authorization': 'Bearer wrong-token-of-length'}
        right = {'Authorization': f'Bearer {TOKEN}'}

        assert [client.get('/api/x', headers=wrong).status_code for _ in range(3)] == [401, 401, 401]
        locked = client.get('/api/x', headers=right)

        assert locked.status_code == 429 and locked.headers['retry-after'] == '300'
        assert 'failed attempts' in locked.json()['error']
        clock.advance(301)
        assert client.get('/api/x', headers=right).status_code == 200

    def test_the_right_token_is_not_a_failure(self):
        client = guarded(Clock(), api_token=TOKEN, max_auth_failures=2)
        right = {'Authorization': f'Bearer {TOKEN}'}

        assert all(client.get('/api/x', headers=right).status_code == 200 for _ in range(20))

    def test_a_missing_token_counts_as_a_failure(self):
        client = guarded(Clock(), api_token=TOKEN, max_auth_failures=2)

        assert [client.get('/api/x').status_code for _ in range(3)] == [401, 401, 429]

    def test_callers_behind_a_trusted_proxy_are_told_apart(self):
        client = guarded(Clock(), rate_limit=1, trust_proxy=True)

        first = client.get('/api/x', headers={'X-Forwarded-For': '203.0.113.1'})
        second = client.get('/api/x', headers={'X-Forwarded-For': '203.0.113.2'})
        again = client.get('/api/x', headers={'X-Forwarded-For': '203.0.113.1'})

        assert (first.status_code, second.status_code, again.status_code) == (200, 200, 429)

    def test_a_header_that_is_not_trusted_cannot_be_used_to_dodge_the_limit(self):
        client = guarded(Clock(), rate_limit=1)

        statuses = [client.get('/api/x', headers={'X-Forwarded-For': f'203.0.113.{i}'}).status_code for i in range(3)]

        assert statuses == [200, 429, 429]

    def test_the_whole_application_is_guarded(self, tmp_path):
        settings = Settings(
            database=tmp_path / 'runs.db', api_token=TOKEN, max_auth_failures=2, rate_limit=5, market_data=None
        )
        client = TestClient(create_app(settings))
        right = {'Authorization': f'Bearer {TOKEN}'}

        assert [client.get('/api/runs', headers=right).status_code for _ in range(5)] == [200] * 5
        assert client.get('/api/runs', headers=right).status_code == 429
        assert client.get('/api/health').status_code == 200  # probes stay available


class TestSettings:
    def test_defaults_are_generous_and_protective(self):
        settings = Settings.from_env({})

        assert (settings.rate_limit, settings.max_auth_failures, settings.lockout_seconds) == (600, 10, 300)
        assert settings.trust_proxy is False

    def test_reads_the_environment(self):
        settings = Settings.from_env(
            {
                'RISK_APP_RATE_LIMIT': '30',
                'RISK_APP_MAX_AUTH_FAILURES': '3',
                'RISK_APP_LOCKOUT_SECONDS': '60',
                'RISK_APP_TRUST_PROXY': 'True',
            }
        )

        assert (settings.rate_limit, settings.max_auth_failures, settings.lockout_seconds, settings.trust_proxy) == (
            30,
            3,
            60,
            True,
        )

    @pytest.mark.parametrize(
        'environ, message',
        [
            ({'RISK_APP_RATE_LIMIT': '-1'}, 'cannot be negative'),
            ({'RISK_APP_MAX_AUTH_FAILURES': '-1'}, 'cannot be negative'),
            ({'RISK_APP_LOCKOUT_SECONDS': '-5'}, 'lockout_seconds'),
            ({'RISK_APP_RATE_LIMIT': 'many'}, 'Invalid RISK_APP_'),
        ],
    )
    def test_rejects_invalid_values(self, environ, message):
        with pytest.raises(ValueError, match=message):
            Settings.from_env(environ)


# ----------------------------------------------------------------------------------------------------------------------
# Database versions
# ----------------------------------------------------------------------------------------------------------------------


def legacy_database(path, with_portfolios=False):
    """A database as the releases before versions made it"""
    db = sqlite3.connect(path)
    db.execute(store_module.SCHEMA)
    db.execute(store_module.SCHEMA_INDEX)
    if with_portfolios:
        db.execute(store_module.SCHEMA_PORTFOLIOS)
    db.execute("INSERT INTO runs VALUES ('abc', 'Old run', 'single', '2026-01-01T00:00:00+00:00', '{}', x'00')")
    db.commit()
    db.close()


class TestMigrations:
    def test_a_new_file_gets_the_latest_version_and_no_backup(self, tmp_path):
        store = RunStore(tmp_path / 'runs.db')

        assert store.schema_version() == SCHEMA_VERSION
        assert list(tmp_path.glob('*.bak*')) == []

    def test_a_database_from_before_versions_is_upgraded_and_copied_aside_first(self, tmp_path):
        path = tmp_path / 'runs.db'
        legacy_database(path)
        before = path.read_bytes()

        store = RunStore(path)

        assert store.schema_version() == SCHEMA_VERSION
        assert [r['name'] for r in store.list()] == ['Old run']  # nothing was lost
        assert store.save_portfolio('x', {'symbols': ['A']})[1] is True  # the table of the later version is there
        backup = tmp_path / 'runs.db.bak-v0'
        assert backup.exists() and sqlite3.connect(backup).execute('PRAGMA user_version').fetchone()[0] == 0
        assert len(before) > 0

    def test_opening_it_again_changes_nothing_and_makes_no_new_copy(self, tmp_path):
        path = tmp_path / 'runs.db'
        legacy_database(path, with_portfolios=True)
        RunStore(path)
        (backup,) = tmp_path.glob('*.bak*')
        stamp = backup.stat().st_mtime_ns

        RunStore(path)

        assert list(tmp_path.glob('*.bak*')) == [backup] and backup.stat().st_mtime_ns == stamp

    def test_a_database_from_a_newer_release_is_refused_and_left_alone(self, tmp_path):
        path = tmp_path / 'runs.db'
        RunStore(path)
        db = sqlite3.connect(path)
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION + 1}')
        db.commit()
        db.close()
        before = path.read_bytes()

        with pytest.raises(StoreVersionError, match='newer version'):
            RunStore(path)

        assert path.read_bytes() == before and list(tmp_path.glob('*.bak*')) == []

    def test_a_step_that_fails_leaves_the_version_and_the_data_as_they_were(self, tmp_path, monkeypatch):
        path = tmp_path / 'runs.db'
        legacy_database(path)
        broken = store_module.MIGRATIONS + ((SCHEMA_VERSION + 1, ('CREATE TABLE good (x)', 'THIS IS NOT SQL')),)
        monkeypatch.setattr(store_module, 'MIGRATIONS', broken)
        monkeypatch.setattr(store_module, 'SCHEMA_VERSION', SCHEMA_VERSION + 1)

        with pytest.raises(sqlite3.Error):
            RunStore(path)

        db = sqlite3.connect(path)
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert 'good' not in tables and 'runs' in tables  # all or nothing

    def test_later_steps_only_run_on_what_is_missing(self, tmp_path, monkeypatch):
        path = tmp_path / 'runs.db'
        RunStore(path)
        monkeypatch.setattr(
            store_module, 'MIGRATIONS', store_module.MIGRATIONS + ((SCHEMA_VERSION + 1, ('CREATE TABLE extra (x)',)),)
        )
        monkeypatch.setattr(store_module, 'SCHEMA_VERSION', SCHEMA_VERSION + 1)

        store = RunStore(path)

        assert store.schema_version() == SCHEMA_VERSION + 1
        assert (tmp_path / 'runs.db.bak-v2').exists()
        assert sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE name = 'extra'").fetchone()

    def test_two_processes_starting_together_are_safe(self, tmp_path):
        path = tmp_path / 'runs.db'
        legacy_database(path)
        errors = []

        def start():
            try:
                RunStore(path)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=start) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        assert errors == [] and RunStore(path).schema_version() == SCHEMA_VERSION

    def test_ready_reports_the_version(self, tmp_path):
        client = TestClient(create_app(Settings(database=tmp_path / 'runs.db', market_data=None)))

        assert client.get('/api/ready').json() == {'status': 'ready', 'schema': SCHEMA_VERSION}


class TestStartupCheck:
    @pytest.fixture
    def serve(self, monkeypatch, tmp_path):
        from gs_quant.apps.risk_dashboard import __main__ as cli

        served = {}
        monkeypatch.setattr('uvicorn.run', lambda app, **kwargs: served.update(app=app))
        for name in ('HOST', 'PORT', 'API_TOKEN'):
            monkeypatch.delenv(f'RISK_APP_{name}', raising=False)
        return cli, served, tmp_path

    def test_a_usable_database_is_created_before_serving(self, serve, monkeypatch):
        cli, served, tmp_path = serve
        monkeypatch.setenv('RISK_APP_DATABASE', str(tmp_path / 'new' / 'runs.db'))

        assert cli.main([]) == 0 and (tmp_path / 'new' / 'runs.db').exists() and 'app' in served

    def test_a_database_from_a_newer_release_stops_the_start_with_a_message(self, serve, monkeypatch, capsys):
        cli, served, tmp_path = serve
        path = tmp_path / 'runs.db'
        RunStore(path)
        db = sqlite3.connect(path)
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION + 5}')
        db.commit()
        db.close()
        monkeypatch.setenv('RISK_APP_DATABASE', str(path))

        assert cli.main([]) == 2

        assert 'newer version' in capsys.readouterr().err and 'app' not in served

    def test_a_database_that_cannot_be_created_stops_the_start_with_a_message(self, serve, monkeypatch, capsys):
        cli, served, tmp_path = serve
        blocked = tmp_path / 'file'
        blocked.write_text('not a directory')
        monkeypatch.setenv('RISK_APP_DATABASE', str(blocked / 'runs.db'))

        assert cli.main([]) == 2

        assert 'cannot use the database' in capsys.readouterr().err and 'app' not in served

    def test_command_line_options_keep_every_other_setting(self, serve, monkeypatch):
        cli, served, tmp_path = serve
        monkeypatch.setenv('RISK_APP_DATABASE', str(tmp_path / 'runs.db'))
        monkeypatch.setenv('RISK_APP_RATE_LIMIT', '77')
        monkeypatch.setenv('RISK_APP_MAX_PORTFOLIOS', '9')
        monkeypatch.setenv('RISK_APP_TRUST_PROXY', '1')

        assert cli.main(['--port', '9100']) == 0

        middleware = served['app'].user_middleware[0].kwargs
        assert middleware['rate_limit'] == 77 and middleware['trust_proxy'] is True
        assert served['app'].state.application.settings.max_portfolios == 9
