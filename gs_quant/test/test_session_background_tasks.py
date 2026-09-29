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

import asyncio
from unittest.mock import MagicMock

import pytest

from gs_quant import session as session_module
from gs_quant.session import GsSession, _run_in_background


@pytest.fixture(autouse=True)
def _clean_background_tasks():
    session_module._background_tasks.clear()
    yield
    session_module._background_tasks.clear()


@pytest.mark.asyncio
async def test_background_task_is_referenced_until_done():
    release = asyncio.Event()

    async def work():
        await release.wait()
        return "done"

    task = _run_in_background(asyncio.get_running_loop(), work())

    assert task in session_module._background_tasks
    release.set()
    assert await task == "done"
    await asyncio.sleep(0)  # let the done callback run
    assert task not in session_module._background_tasks


@pytest.mark.asyncio
async def test_failed_background_task_is_still_released():
    async def fail():
        raise RuntimeError("boom")

    task = _run_in_background(asyncio.get_running_loop(), fail())
    await asyncio.wait([task])
    await asyncio.sleep(0)

    assert task.exception() is not None
    assert task not in session_module._background_tasks


def _fake_session(close_async):
    fake = MagicMock()
    fake._GsSession__close_on_exit_async = True
    fake._GsSession__close_on_exit = False
    fake._has_async_session.return_value = True
    fake._close_async = close_async
    return fake


@pytest.mark.asyncio
async def test_on_exit_keeps_a_reference_to_the_async_close_task():
    release = asyncio.Event()
    closed = []

    async def close_async():
        await release.wait()
        closed.append(True)

    GsSession._on_exit(_fake_session(close_async), None, None, None)

    assert len(session_module._background_tasks) == 1
    release.set()
    await asyncio.sleep(0.01)
    assert closed == [True]
    assert not session_module._background_tasks


def test_on_exit_without_running_loop_closes_synchronously():
    closed = []

    async def close_async():
        closed.append(True)

    GsSession._on_exit(_fake_session(close_async), None, None, None)

    assert closed == [True]
    assert not session_module._background_tasks
