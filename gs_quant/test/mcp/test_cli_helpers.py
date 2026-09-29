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

from unittest.mock import MagicMock

import pytest
import typer

from gs_quant.mcp import __main__ as cli


class TestParseHeaderKv:
    def test_none_and_empty(self):
        assert cli._parse_header_kv(None) == {}
        assert cli._parse_header_kv([]) == {}

    def test_colon_and_equals_separators(self):
        assert cli._parse_header_kv(["X-A: one", "X-B=two"]) == {"X-A": "one", "X-B": "two"}

    def test_only_first_separator_splits(self):
        assert cli._parse_header_kv(["Authorization: Bearer a:b=c"]) == {"Authorization": "Bearer a:b=c"}

    def test_colon_wins_over_equals(self):
        assert cli._parse_header_kv(["k=v: w"]) == {"k=v": "w"}

    def test_later_duplicates_win(self):
        assert cli._parse_header_kv(["A: 1", "A: 2"]) == {"A": "2"}

    def test_missing_separator_is_rejected(self):
        with pytest.raises(typer.BadParameter, match="--header must be"):
            cli._parse_header_kv(["nonsense"])


class TestGetTools:
    def test_discovers_each_non_blank_package(self, monkeypatch):
        discover = MagicMock()
        monkeypatch.setattr(cli, "registry_discover_tools", discover)
        monkeypatch.setattr(cli, "get_registered_tools", lambda: {"tool": object})

        result = cli.get_tools("pkg.one, pkg.two", "extra.pkg,,")

        assert [c.args[0] for c in discover.call_args_list] == ["pkg.one", "pkg.two", "extra.pkg"]
        assert result == {"tool": object}

    def test_blank_packages_are_skipped(self, monkeypatch):
        discover = MagicMock()
        monkeypatch.setattr(cli, "registry_discover_tools", discover)
        monkeypatch.setattr(cli, "get_registered_tools", dict)

        assert cli.get_tools("", "") == {}
        discover.assert_not_called()
