# 后端（FastAPI）

自然语言驱动的多模态图像编辑工作台的服务端。

## 分层

```
app/
├── main.py       入口：lifespan 做配置自检 + ensure_bucket，生产环境同源托管前端 dist
├── config.py     pydantic-settings；必填项缺失即失败（无不安全默认值兜底）
├── db.py         SQLAlchemy 异步引擎与会话
├── routers/      只做校验与响应组装
├── services/     业务编排与基础设施适配（执行外壳 / 编排 / 会话 / 选区 / 存储 / 事件）
├── tools/        工具注册表（M4）——一处定义，同时服务服务端校验与 LLM function schema
├── edits/        图像原子能力（像素 / 遮罩 / 分割 / 拆层 / 渲染 / OCR）
├── agent/        LangGraph 状态机、计划校验、prompt 版本（M8–M9）
├── providers/    模型 Provider（mock / dashscope），用 Protocol 而非 ABC
└── eval/         Agent 规划质量评测集（M10）
```

## 依赖分层

```bash
uv sync                    # 核心：能跑 API 与确定性工具
uv sync --extra agent      # + LLM / LangGraph
uv sync --extra cv         # + rembg / onnxruntime / opencv（体积大，M6 才需要）
uv sync --extra dev        # + 测试与 lint
```

## 常用命令

```bash
uv run uvicorn app.main:app --port 7302 --reload     # API
uv run arq app.worker.WorkerSettings                 # 异步任务 worker（M2 起，必须与 API 同时跑）
alembic revision --autogenerate -m "..."      # 生成迁移
alembic upgrade head                          # 应用迁移
pytest                                        # 测试（需要 PG / Redis / 对象存储在线）
```

> 三条数据流（M2 定型）：HTTP 只负责**建任务并返回 202**；
> worker 通过 Redis Pub/Sub 推进度；前端由 `/events/runs/{id}` 订阅。
> 少跑 worker 的表现是任务永远停在 `queued` —— 不是接口坏了。

## 环境变量

见仓库根 `.env.example`。缺必填变量时启动即失败并打印缺失清单，不做静默兜底。
