"""The notes of one release, taken from CHANGELOG.md: python deploy/release_notes.py <changelog> <version>

A release is written under a heading such as "## [0.1.0] - 2026-10-05". The command fails if there is none, so a tag cannot
be published without notes.
"""

import re
import sys
from pathlib import Path

HEADING = re.compile(r'^## \[(?P<version>[^\]]+)\]')


def notes_for(changelog: str, version: str) -> str:
    lines = changelog.splitlines()
    start = next((i for i, line in enumerate(lines) if (m := HEADING.match(line)) and m['version'] == version), None)
    if start is None:
        raise LookupError(f'CHANGELOG.md has no section "## [{version}]"')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
    body = '\n'.join(lines[start + 1 : end]).strip()
    if not body:
        raise LookupError(f'The section for {version} in CHANGELOG.md is empty')
    return body + '\n'


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        sys.stdout.write(notes_for(Path(args[0]).read_text(encoding='utf-8'), args[1]))
    except (LookupError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
