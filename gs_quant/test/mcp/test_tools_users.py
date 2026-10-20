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

from gs_quant.mcp.tools.users import tools


def test_current_user_info_returns_only_whitelisted_fields():
    profile = {
        "id": "u1",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "city": "London",
        "title": "Quant",
        "departmentName": "Strats",
        "tokens": ["secret"],  # never exposed
        "password": "hunter2",
    }

    result = tools.current_user_info(user_profile=profile)

    assert result["id"] == "u1"
    assert result["departmentName"] == "Strats"
    assert "tokens" not in result and "password" not in result


def test_current_user_info_fills_missing_fields_with_none():
    result = tools.current_user_info(user_profile={"id": "u1"})

    assert set(result) == {
        "id",
        "name",
        "email",
        "city",
        "region",
        "company",
        "internal",
        "title",
        "divisionName",
        "departmentName",
    }
    assert result["name"] is None


def test_whois_searches_within_the_user_session(monkeypatch):
    search = MagicMock(return_value=[{"name": "Jane Doe"}])
    monkeypatch.setattr(tools.GsUsersApi, "search", search)
    session = MagicMock()

    assert tools.whois("jane", user_session=session) == [{"name": "Jane Doe"}]

    search.assert_called_once_with("jane")
    session.__enter__.assert_called_once()
    session.__exit__.assert_called_once()
