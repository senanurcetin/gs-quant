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

import collections
import time
from typing import Callable, Optional

MAX_TRACKED_CLIENTS = 10_000  # what is remembered about callers is bounded: an attacker cannot grow it without limit


class SlidingWindowLimiter:
    """At most `limit` hits per client in any `window` seconds"""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: collections.OrderedDict[str, collections.deque] = collections.OrderedDict()

    def hit(self, client: str) -> Optional[float]:
        """Counts a request. None if it is allowed, else the seconds to wait until it would be"""
        now = self._clock()
        hits = self._hits.pop(client, None) or collections.deque()
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        wait = None
        if len(hits) >= self.limit:
            wait = self.window - (now - hits[0])
        else:
            hits.append(now)
        self._hits[client] = hits  # most recently seen last
        while len(self._hits) > MAX_TRACKED_CLIENTS:
            self._hits.popitem(last=False)
        return wait


class FailureLock:
    """Locks a client out for `lockout` seconds after `limit` failures within that time"""

    def __init__(self, limit: int, lockout: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.lockout = lockout
        self._clock = clock
        self._failures: collections.OrderedDict[str, collections.deque] = collections.OrderedDict()

    def _recent(self, client: str) -> collections.deque:
        now = self._clock()
        failures = self._failures.get(client)
        if failures is None:
            return collections.deque()
        while failures and now - failures[0] >= self.lockout:
            failures.popleft()
        return failures

    def locked(self, client: str) -> Optional[float]:
        """None if the client may try, else the seconds until the oldest failure that counts has expired"""
        failures = self._recent(client)
        if len(failures) < self.limit:
            return None
        return max(self.lockout - (self._clock() - failures[0]), 1.0)

    def record(self, client: str) -> None:
        failures = self._recent(client)
        failures.append(self._clock())
        self._failures.pop(client, None)
        self._failures[client] = failures
        while len(self._failures) > MAX_TRACKED_CLIENTS:
            self._failures.popitem(last=False)


def client_of(scope: dict, trust_proxy: bool) -> str:
    """Who is calling. Behind a reverse proxy every connection comes from the proxy, so the address it appended to
    X-Forwarded-For (the last one: earlier ones are written by the caller) is used when the proxy is trusted."""
    if trust_proxy:
        for name, value in scope['headers']:
            if name == b'x-forwarded-for':
                last = value.decode('latin-1').split(',')[-1].strip()
                if last:
                    return last[:64]
    client = scope.get('client')
    return client[0] if client else 'unknown'
