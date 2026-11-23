"""Run TraceGrid with explicit network and WebSocket bounds."""

import argparse

import uvicorn

from app.config import settings
from app.services.http_security import MAX_WEBSOCKET_MESSAGE_BYTES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()
    if arguments.workers < 1 or (arguments.reload and arguments.workers != 1):
        parser.error("Use at least one worker and disable reload when using multiple workers.")
    uvicorn.run(
        "app.main:app", host=arguments.host, port=arguments.port, workers=arguments.workers, reload=arguments.reload,
        proxy_headers=bool(settings.TRUSTED_PROXY_NETWORKS),
        forwarded_allow_ips=",".join(settings.TRUSTED_PROXY_NETWORKS), access_log=False, log_level="warning",
        ws="wsproto", ws_max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        limit_concurrency=settings.MAX_WEBSOCKETS_PER_WORKER + 64, timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()
