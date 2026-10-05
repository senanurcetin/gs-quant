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

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .settings import ENV_PREFIX, Settings

LOGGER = 'gs_quant.apps.risk_dashboard'


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger = logging.getLogger(LOGGER)
    logger.handlers[:] = [handler]
    logger.setLevel(level)
    logger.propagate = False


def build_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='gs-quant-risk',
        description=f'Risk analytics application. Configuration comes from {ENV_PREFIX}* environment variables.',
    )
    commands = parser.add_subparsers(dest='command')

    serve = commands.add_parser('serve', help='Serve the application (the default command)')
    serve.add_argument('--host', default=settings.host, help='Interface to bind to (default: localhost only)')
    serve.add_argument('--port', type=int, default=settings.port)
    serve.add_argument('--database', type=Path, default=settings.database, help='SQLite file for saved analyses')
    serve.add_argument(
        '--no-auth',
        action='store_true',
        help=f'Allow a non-local --host without {ENV_PREFIX}API_TOKEN. Anyone who can reach the port can then read and '
        'delete saved analyses.',
    )

    export = commands.add_parser('export', help='Write the dashboard as one self-contained HTML file')
    export.add_argument('-o', '--output', default='risk_dashboard.html', type=Path)
    export.add_argument('--observations', type=int, default=1000)
    export.add_argument('--seed', type=int, default=7)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ('serve', 'export', '-h', '--help'):
        argv.insert(0, 'serve')  # `python -m gs_quant.apps.risk_dashboard --port 9000` keeps working
    try:
        settings = Settings.from_env()
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    args = build_parser(settings).parse_args(argv)

    if args.command == 'export':
        from . import export

        export.main(['-o', str(args.output), '--observations', str(args.observations), '--seed', str(args.seed)])
        return 0

    try:
        settings = Settings(
            host=args.host,
            port=args.port,
            database=args.database,
            api_token=settings.api_token,
            max_body_bytes=settings.max_body_bytes,
            max_runs=settings.max_runs,
            log_level=settings.log_level,
        )
        settings.validate()
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    if not settings.is_local and settings.api_token is None and not args.no_auth:
        print(
            f'error: refusing to listen on {settings.host} without an access token. Set {ENV_PREFIX}API_TOKEN '
            '(16 characters or more), or pass --no-auth if the network is trusted.',
            file=sys.stderr,
        )
        return 2

    import uvicorn

    from .app import create_app

    configure_logging(settings.log_level)
    logging.getLogger(LOGGER).info(
        'Serving on http://%s:%d, saved analyses in %s, access token %s',
        settings.host,
        settings.port,
        settings.database,
        'required' if settings.api_token else 'not required',
    )
    # the application logs its own access lines, with request ids
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level='warning', access_log=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
