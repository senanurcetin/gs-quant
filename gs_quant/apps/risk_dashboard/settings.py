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

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ENV_PREFIX = 'RISK_APP_'
LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR')


def default_data_dir() -> Path:
    base = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'gs-quant-risk'


@dataclass(frozen=True)
class Settings:
    """Runtime configuration of the application, read from RISK_APP_* environment variables"""

    host: str = '127.0.0.1'
    port: int = 8000
    database: Path = default_data_dir() / 'runs.db'
    api_token: Optional[str] = None  # when set, every /api/ endpoint except the probes needs 'Authorization: Bearer'
    max_body_bytes: int = 1_000_000
    max_runs: int = 200  # oldest saved runs are dropped beyond this
    log_level: str = 'INFO'

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> 'Settings':
        env = os.environ if environ is None else environ

        def get(name: str) -> Optional[str]:
            value = env.get(ENV_PREFIX + name)
            return value if value not in (None, '') else None

        defaults = cls()
        try:
            settings = cls(
                host=get('HOST') or defaults.host,
                port=int(get('PORT') or defaults.port),
                database=Path(get('DATABASE')) if get('DATABASE') else defaults.database,
                api_token=get('API_TOKEN'),
                max_body_bytes=int(get('MAX_BODY_BYTES') or defaults.max_body_bytes),
                max_runs=int(get('MAX_RUNS') or defaults.max_runs),
                log_level=(get('LOG_LEVEL') or defaults.log_level).upper(),
            )
        except ValueError as e:
            raise ValueError(f'Invalid {ENV_PREFIX}* setting: {e}') from e
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0 < self.port < 65536:
            raise ValueError(f'port must be between 1 and 65535, got {self.port}')
        if self.max_body_bytes < 1_000:
            raise ValueError('max_body_bytes must be at least 1000')
        if self.max_runs < 1:
            raise ValueError('max_runs must be at least 1')
        if self.log_level not in LOG_LEVELS:
            raise ValueError(f'log_level must be one of {", ".join(LOG_LEVELS)}')
        if self.api_token is not None and len(self.api_token) < 16:
            raise ValueError('api_token must be at least 16 characters')

    @property
    def is_local(self) -> bool:
        return self.host in ('127.0.0.1', 'localhost', '::1')
