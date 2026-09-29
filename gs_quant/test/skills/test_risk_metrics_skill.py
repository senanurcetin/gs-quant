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

import re
from pathlib import Path

import pytest

import gs_quant.skills as skills_package

SKILL_DIR = Path(skills_package.__file__).parent / "gs-quant-overview"
FENCE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _python_blocks(name: str) -> list[str]:
    return FENCE.findall((SKILL_DIR / name).read_text(encoding="utf-8"))


def test_risk_metrics_examples_run():
    """The examples are documentation an agent copies from, so they must keep working (blocks build on each other)"""
    blocks = _python_blocks("risk-metrics.md")
    assert len(blocks) == 5

    namespace: dict = {}
    for i, block in enumerate(blocks):
        try:
            exec(compile(block, f"risk-metrics.md[block {i}]", "exec"), namespace)
        except Exception as e:  # pragma: no cover - failure path
            pytest.fail(f"Example block {i} failed: {e!r}\n{block}")

    assert namespace["summary"].observations == 750
    assert namespace["result"].observations == 499  # 750 - 250 ramp up - 1 lag
    assert namespace["var_hist"].iloc[-1] < 0


def test_risk_metrics_skill_is_linked_from_the_overview():
    overview = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "`risk-metrics.md`" in overview


def test_every_skill_file_referenced_by_the_overview_exists():
    overview = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    for name in re.findall(r"^- `([\w-]+\.md)`", overview, flags=re.MULTILINE):
        assert (SKILL_DIR / name).is_file(), name
