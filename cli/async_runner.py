"""Run a CLI command's coroutine and always release the shared DB connection."""

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """`asyncio.run()` for CLI commands that may touch `backend.db`.

    aiosqlite runs every connection on a non-daemon thread, so a command that
    opens the shared `db` singleton (writer + reader pool) and never closes it
    prints its result and then hangs instead of exiting. Closing in a
    `finally` inside the same event loop covers the success, CLIError and
    SystemExit paths alike; `db.close()` is a no-op when nothing was opened.
    """

    async def _with_db_cleanup() -> T:
        try:
            return await coro
        finally:
            from backend.db.connection import db

            await db.close()

    return asyncio.run(_with_db_cleanup())
