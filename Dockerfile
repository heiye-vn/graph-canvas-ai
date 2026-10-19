# 前端构建产物由后端同源托管，因此在同一镜像内完成构建
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONPATH=/app/backend

COPY backend/pyproject.toml backend/uv.lock ./
# 只装 agent extra：CV 依赖（rembg / onnxruntime / opencv）体积大且 M6 引入 SAM 时才用得上。
# 到 M6 接抠图与选区时，改为：uv sync --frozen --extra agent --extra cv --no-dev
RUN uv sync --frozen --extra agent --no-dev

COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 7402