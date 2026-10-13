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
│   └── layer_doc.py  图层文档读写（纯函数）；UI 与 Agent 共用同一份「找哪一层」的规则
├── schemas/
│   ├── layer_doc.py  图层文档结构 —— 前端画布与服务端工具之间的契约
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

### 编辑会话（M3）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/edit-sessions` | 用素材建会话（至少一张），返回初始图层文档 |
| GET | `/api/edit-sessions` | 本人会话列表（含图层数 / 素材数） |
| GET | `/api/edit-sessions/{id}` | **恢复现场**：文档 + 带预签名 URL 的素材 |
| POST | `/api/edit-sessions/{id}/assets` | 追加素材（幂等：重复加入不产生第二个图层） |
| PUT | `/api/edit-sessions/{id}/doc` | 整份替换图层文档 |
| PATCH | `/api/edit-sessions/{id}` | 改标题 |
| DELETE | `/api/edit-sessions/{id}` | 删除会话 |

> **图层文档三条约定**（`app/schemas/layer_doc.py` 顶部同款注释，改代码前先看）：
> ① `layers` 数组**从下到上**，面板渲染要倒过来；
> ② `id` 必须唯一，`name` 允许重复，按名查找取**最上层**；
> ③ 文档里只放 `asset_id` 引用，绝不入 URL（预签名地址有有效期，落进去就是烂数据）。
>
> **`resolve_layer()` 是唯一的图层定位入口**：UI 的选中态和 Agent 的工具调用都要走它，
> 不指定时取「最上层可见 image 层」。两边各走一套规则时，同一个操作在两个入口会
> 得到不同结果，而且很难复现。
>
> 文档写入走**整份替换**而非 patch：一次操作可能同时改变层级顺序、可见性和载荷，
> 用 diff 表达这些既啰嗦又容易错。乐观并发保护留到 M4 工具入口真正并发时再加。

## 环境变量

见仓库根 `.env.example`。缺必填变量时启动即失败并打印缺失清单，不做静默兜底。
