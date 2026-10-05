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

import base64
import hashlib
import re

from . import export

INLINE = re.compile(r'<(script|style)>(.*?)</\1>', re.DOTALL)


def render_run(stored: dict, result: dict) -> str:
    """A saved run as one self-contained HTML file that shows its results without a server

    Everything in it was calculated by the backend: the page only draws the numbers.
    """
    run = {k: stored[k] for k in ('id', 'name', 'kind', 'created_at')}
    payload = {'run': {**run, 'result': result}}
    return export.render(payload, title=f'Risk report: {stored["name"]}')


def content_security_policy(html: str) -> str:
    """A policy that allows exactly the inline script and style elements of the document, by hash, and nothing else"""

    def sources(tag: str) -> str:
        hashes = [
            "'sha256-" + base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode() + "'"
            for name, body in INLINE.findall(html)
            if name == tag
        ]
        return ' '.join(hashes) or "'none'"

    return (
        f"default-src 'none'; script-src {sources('script')}; style-src {sources('style')}; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
