import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=7302, log_level="info")
