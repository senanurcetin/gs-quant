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

import uvicorn

from .app import create_app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Serve the risk analytics dashboard')
    parser.add_argument('--host', default='127.0.0.1', help='Interface to bind to (default: localhost only)')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level='info')


if __name__ == '__main__':
    main()
