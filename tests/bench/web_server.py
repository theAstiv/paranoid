"""Serve the real app with the bench call logger installed: `python -m tests.bench.web_server <calls.jsonl> <port>`.

Used by web_driver.py so web/API-path runs get the same per-call log as CLI runs.
"""

import sys
from pathlib import Path

import uvicorn

from tests.bench.run_one import _install_call_logger


if __name__ == "__main__":
    _install_call_logger(Path(sys.argv[1]))
    from backend.main import app

    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="info")
