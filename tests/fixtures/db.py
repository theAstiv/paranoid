"""Real read-only reader connections for the test database fixtures."""

import asyncio

import aiosqlite


_TEST_READER_POOL_SIZE = 2


async def open_reader_pool(
    db_path: str, extension_path: str | None = None
) -> asyncio.Queue[aiosqlite.Connection]:
    """Open `mode=ro` connections like ConnectionManager.initialize does.

    Separate connections, not the writer: a read through db.reader() then
    sees only committed rows, as in the app. Two of them, so two readers can
    be checked out at once (a single shared one hung any nested reader()).
    """
    pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
    for _ in range(_TEST_READER_POOL_SIZE):
        reader = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
        reader.row_factory = aiosqlite.Row
        await reader.execute("PRAGMA busy_timeout = 5000;")
        if extension_path is not None:
            await reader.enable_load_extension(True)
            await reader.load_extension(extension_path)
        pool.put_nowait(reader)
    return pool


async def close_reader_pool(pool: asyncio.Queue[aiosqlite.Connection] | None) -> None:
    """Close every connection still in the pool."""
    if pool is None:
        return
    while not pool.empty():
        await pool.get_nowait().close()
