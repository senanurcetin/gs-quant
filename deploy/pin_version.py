"""Fixes the version of an installation made from a source tree that has no git history, such as a Docker build.

versioneer reads the version from git tags; without them it reports 0+unknown. This writes gs_quant/_version.py as a
file in versioneer's format that reports the version it is given, in the copy being installed. Usage: python deploy/pin_version.py 1.2.3
"""

import json
import re
import sys
from pathlib import Path

VERSION = re.compile(r'^\d+\.\d+\.\d+([.-]?[0-9A-Za-z.]+)?$')
# versioneer's own format: it reads the version back from this file when it builds, and writes the file again from what it
# read. A stub with a get_versions() of its own would be replaced by versioneer's "0+unknown" in the built package.
STUB = '''# Written by deploy/pin_version.py: this copy was built without git history

import json

version_json = \'\'\'
{json}
\'\'\'  # END VERSION_JSON


def get_versions():
    return json.loads(version_json)
'''


def pin(version: str, root: Path) -> Path:
    if not VERSION.match(version):
        raise ValueError(f'{version!r} is not a version such as 1.2.3')
    target = root / 'gs_quant' / '_version.py'
    if not target.parent.is_dir():
        raise FileNotFoundError(f'{target.parent} does not exist: run this from the root of the source tree')
    details = {'date': None, 'dirty': False, 'error': None, 'full-revisionid': None, 'version': version}
    target.write_text(STUB.format(json=json.dumps(details, indent=1, sort_keys=True)), encoding='utf-8')
    return target


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(f'Pinned {pin(args[0], Path.cwd())} to {args[0]}')
    except (ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
