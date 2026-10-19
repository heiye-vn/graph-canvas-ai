import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

from app.config import get_settings
from app.main import app

if __name__ == "__main__":
    # 端口只认配置（API_PORT，默认 7402），避免这里和 .env 各写一份真相
    uvicorn.run(app, host="127.0.0.1", port=get_settings().api_port, log_level="info")
