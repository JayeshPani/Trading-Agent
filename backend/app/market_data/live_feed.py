from __future__ import annotations

from collections.abc import AsyncIterator


async def empty_live_feed() -> AsyncIterator[dict[str, object]]:
    if False:
        yield {}
