"""Start the API. On Windows psycopg async needs a SelectorEventLoop (default Proactor is unsupported)."""
import argparse
import asyncio
import selectors
import sys

import uvicorn

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args()

    server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(server.serve())
