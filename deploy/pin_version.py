"""Fixes the version of an installation made from a source tree that has no git history, such as a Docker build.

versioneer reads the version from git tags; without them it reports 0+unknown. This writes gs_quant/_version.py as a
stub that reports the version it is given, in the copy being installed. Usage: python deploy/pin_version.py 1.2.3
"""

import re
import sys
from pathlib import Path

VERSION = re.compile(r'^\d+\.\d+\.\d+([.-]?[0-9A-Za-z.]+)?$')
STUB = '''# Written by deploy/pin_version.py: this copy was built without git history
def get_versions():
    return {{"version": {version!r}, "full-revisionid": None, "dirty": False, "error": None, "date": None}}
'''


def pin(version: str, root: Path) -> Path:
    if not VERSION.match(version):
        raise ValueError(f'{version!r} is not a version such as 1.2.3')
    target = root / 'gs_quant' / '_version.py'
    if not target.parent.is_dir():
        raise FileNotFoundError(f'{target.parent} does not exist: run this from the root of the source tree')
    target.write_text(STUB.format(version=version), encoding='utf-8')
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
