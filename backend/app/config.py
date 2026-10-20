"""应用配置。

配置策略：**必填即失败**。

给 jwt_secret / S3 凭据写弱默认值，缺配置时「静默用不安全默认值」，
会把「配置没传」伪装成「配置传了但不对」，排查方向完全跑偏。

因此这里一律没有默认值兜底：缺变量时启动阶段直接抛错并列出缺失项。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator
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
    api_port: int = 7402
    api_prefix: str = "/api"

    # ---- 基础设施（必填）----
    database_url: str = Field(description="postgresql+asyncpg://...")
    redis_url: str = Field(description="redis://...")

    # ---- 对象存储（必填）----
    s3_endpoint: str = Field(description="容器内 http://minio:9000，宿主机 http://127.0.0.1:7413")
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "retouch"
    s3_region: str = "us-east-1"

    # ---- 鉴权（必填）----
    jwt_secret: str
    jwt_ttl_hours: int = 24

    # ---- 素材上传 ----
    # backend：文件过一遍本服务（便于服务端做内容校验）；presigned：直传对象存储
    asset_upload_mode: Literal["backend", "presigned"] = "backend"
    asset_max_size_mb: int = 20

    # ---- 模型 Provider ----
    # mock 使用本地占位图，不产生任何调用费用，也不需要 Key
    # dashscope 走阿里云百炼原生生图端点
    # openai 走第三方中转站/标准 OpenAI /v1/images/generations 端点
    image_provider: Literal["mock", "dashscope", "openai"] = "mock"
    dashscope_api_key: str | None = None
    # 中转站 / OpenAI 兼容生图端点与独立 Key（若留空则自动 fallback 到通用 key）
    image_base_url: str | None = None
    image_api_key: str | None = None
    # 生图/编辑模型名（百炼可用 qwen-image-3.0 等；中转站可用 gpt-image-2 / gemini-3-pro-image 等）
    text_to_image_model: str = "qwen-image-3.0"
    image_edit_model: str = "qwen-image-3.0"
    planner_model: str = "qwen-plus"

    # ---- 选区分割（M6）----
    # sam：rembg 的 SAM 模型（首次点击算 embedding，后续只跑 decoder，需要 cv extra）
    # circle：纯 Pillow 画圆，零依赖兜底
    # auto：先试 SAM，任何异常降级画圆 —— 演示环境不为可选依赖崩掉
    matting_provider: Literal["auto", "sam", "circle"] = "auto"

    # ---- 文字检测（M7）----
    # rapidocr：rapidocr-onnxruntime（cv extra）；none：不检测；
    # auto：装了就用，任何异常静默返回空（拆层不因 OCR 挂掉）
    ocr_provider: Literal["auto", "rapidocr", "none"] = "auto"

    # ---- Agent（M4）----
    # OpenAI 兼容端点；国内网络默认走百炼的兼容模式，换自建/其它厂商只改这一个变量
    llm_base_url: str | None = None
    llm_temperature: float = 0.0

    # ---- 可观测：可选 Langfuse 旁路导出（不配则完全跳过，本地 trace 表照常）----
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _check_secret_strength(self) -> Settings:
        """HS256 的密钥强度等于其字节长度，短于 32 字节等于自废武功。

        开发/测试环境不拦（避免挡住本地跑通流程），生产环境一律拒绝弱密钥。
        """
        if self.is_production and len(self.jwt_secret.encode()) < 32:
            raise ValueError(
                f"JWT_SECRET 仅 {len(self.jwt_secret)} 字节，生产环境至少需要 32 字节（建议 64）"
            )
        return self

    def require_llm_config(self) -> tuple[str, str, str]:
        """Agent 链路真正要调模型时才校验（base_url, api_key, model）。

        与 `require_dashscope_key` 同一口径：**缺配置立即失败**，
        不静默降级到「假装理解了」的假规划。
        """
        key = self.require_dashscope_key()
        base = self.llm_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return base, key, self.planner_model

    def require_dashscope_key(self) -> str:
        """规划/百炼生图链路真正要用 Key 时才校验，避免 mock 模式下被迫填一堆空变量。"""
        if not self.dashscope_api_key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY 未配置：当前操作需要调用阿里云百炼模型。"
                "纯本地跑通流程请保持 IMAGE_PROVIDER=mock 且只使用确定性工具。"
            )
        return self.dashscope_api_key

    def require_image_api_key(self) -> str:
        """中转站生图链路要用 Key 时才校验。优先 IMAGE_API_KEY，缺省回退 DASHSCOPE_API_KEY。"""
        key = self.image_api_key or self.dashscope_api_key
        if not key:
            raise RuntimeError(
                "IMAGE_API_KEY 未配置：当前 IMAGE_PROVIDER=openai 需要中转站生图 Key。"
                "请在 .env 中配置 IMAGE_API_KEY。"
            )
        return key


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
