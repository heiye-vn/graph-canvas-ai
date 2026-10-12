"""应用配置。

与参考项目 ai-picture-editor 的关键分歧（见 docs/开发计划.md §〇.3）：

    参考项目给 jwt_secret / S3 凭据写了弱默认值，缺配置时「静默用不安全默认值」——
    这会把「配置没传」伪装成「配置传了但不对」，排查方向完全跑偏。

本项目一律 **必填即失败**：没有默认值兜底，缺变量时启动阶段直接抛错并列出缺失项。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# 本地开发兜底：优先 backend/.env，其次仓库根 .env（容器里由 compose 的 env_file 注入）
_BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV), str(_BACKEND_ENV)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用 ----
    app_env: Literal["development", "production", "test"] = "development"
    api_port: int = 7302
    api_prefix: str = "/api"

    # ---- 基础设施（必填）----
    database_url: str = Field(description="postgresql+asyncpg://...")
    redis_url: str = Field(description="redis://...")

    # ---- 对象存储（必填）----
    s3_endpoint: str = Field(description="容器内 http://minio:9000，宿主机 http://127.0.0.1:7313")
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "retouch"
    s3_region: str = "us-east-1"

    # ---- 鉴权（必填）----
    jwt_secret: str
    jwt_ttl_hours: int = 24

    # ---- 模型 Provider ----
    # mock 使用本地占位图，不产生任何调用费用，也不需要 Key
    image_provider: Literal["mock", "dashscope"] = "mock"
    dashscope_api_key: str | None = None
    text_to_image_model: str = "qwen-image"
    image_edit_model: str = "qwen-image-edit"
    planner_model: str = "qwen-plus"

    # ---- 可观测（M9.3 启用，缺失时不阻塞启动）----
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def require_dashscope_key(self) -> str:
        """规划/生图链路真正要用 Key 时才校验，避免 mock 模式下被迫填一堆空变量。"""
        if not self.dashscope_api_key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY 未配置：当前操作需要调用真实模型。"
                "纯本地跑通流程请保持 IMAGE_PROVIDER=mock 且只使用确定性工具。"
            )
        return self.dashscope_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 单元测试要换配置时显式 get_settings.cache_clear()
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def preflight_settings() -> None:
    """在 import 阶段之外做一次显式自检，把 pydantic 的报错翻译成人话。

    uvicorn 启动时调用；缺变量会打印缺失清单后以非零码退出。
    """
    try:
        get_settings()
    except ValidationError as exc:
        missing = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        raise SystemExit(
            "配置自检失败，以下必填环境变量缺失或非法：\n"
            + "\n".join(f"  - {name}" for name in missing)
            + "\n\n请对照 .env.example 补全后重启（容器内由 compose 的 env_file 注入）。"
        ) from None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
