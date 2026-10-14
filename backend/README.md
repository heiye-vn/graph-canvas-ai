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
│   ├── layer_doc.py   图层文档读写（纯函数）；UI 与 Agent 共用同一份「找哪一层」的规则
│   ├── tool_exec.py   工具执行外壳：调一次工具 + 生成给模型的文档摘要
│   └── agent_step.py  单步自然语言：解析 → 执行 → 回执
├── schemas/
│   ├── layer_doc.py  图层文档结构 —— 前端画布与服务端工具之间的契约
├── tools/        工具注册表（M4）——一处定义，同时服务服务端校验与 LLM function schema
│   ├── base.py       ToolSpec / ToolContext / ToolResult；参数错一律 ToolError
│   ├── registry.py   注册与查询；重复注册直接抛错
│   └── builtins.py   13 个内置工具（导入即注册）
├── edits/        图像原子能力（像素 / 遮罩 / 分割 / 拆层 / 渲染 / OCR）
├── agent/        LLM 接入（`llm.py`：schema 派生 + 单次规划）；LangGraph 状态机、
│                 计划校验、prompt 版本在 M8–M9
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
| PUT | `/api/edit-sessions/{id}/doc` | 整份替换图层文档（**不写历史**，绕过撤销栈 —— 只有重建现场时才用） |
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
> 用 diff 表达这些既啰嗦又容易错。

### 撤销栈（M5）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/edit-sessions/{id}/history` | 指针位置 + `can_undo` / `can_redo` + 留存记录（**不含快照**） |
| POST | `/api/edit-sessions/{id}/history/undo` | 退一步；已在初始态 → 409 |
| POST | `/api/edit-sessions/{id}/history/redo` | 前进一步；已在最新 → 409 |

> **快照式而非反向操作**：每条历史存 `before` / `after` 两份整文档，undo 写回
> before、redo 写回 after。反向操作要为 16 个工具各写一份严格对称的 undo 逻辑，
> 任何一处不对称（比如忘了记 reorder 的原索引）都会悄悄改坏文档。
>
> **文档与历史必须在同一个事务里写**。只写历史不写文档 → 「画布没变但栈里多了一条」；
> 只写文档不写历史 → 这一步再也退不回去。这就是为什么工具统一走
> `history.apply_tool_calls()` 而不是各自调 `replace_doc()`。
>
> **UI 上的改动也必须走工具入口**。M3 时图层面板直接改文档（那时还没有历史），
> M5 起改成调 `set_layer_visible` / `switch_current_image` —— 否则用户会发现
> 「有些操作退不回去」，而这恰恰最说不通。
>
> `changed=False` 的历史照样保留，但撤销时跳过：重复设置一个已经成立的值，
> 不该让「按了撤销没反应」。留记录是因为用户在编辑记录里要找得到自己刚才那一下。
>
> 上限 50 条，超了丢最老的且**不重排 seq** —— 重排会让指针一夜之间指向别的条目。
> 撤到边界就停住，比撤到错误的中间态好得多。

### 工具与 Agent（M4）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/tools` | 工具元数据（name / label / group / 参数表单描述），前端表单的唯一来源 |
| POST | `/api/tools/{name}/invoke` | 直接调一个工具（参数错 → 422 `bad_params`） |
| POST | `/api/agent/step` | 一句话 → LLM 选工具 → 执行 → 回执（工具/参数/说明） |

已注册 **16 个**工具：`adjust_color` `set_opacity` `set_layer_visible` `rename_layer`
`reorder_layer` `switch_current_image` `remove_layer` `add_image_layer` `move_layer`
`resize_layer` `rotate_layer` `crop_layer` `reset_crop` `flip_layer` `add_text_layer`
`set_canvas_background`。

> ⚠️ 加字段时**不要升 `DOC_VERSION`**：新字段一律带默认值（见 `crop` / `flip_x`），
> 老文档自然解读为「没有裁剪、没有翻转」。升版本会让存量会话全部读不进来，
> 还得再写一遍洗数据迁移。

> **一处定义三处消费**：工具的入参只写一份 Pydantic Model，同时派生
> ① 服务端校验（`model_validate`）、② LLM function schema、③ `/api/tools` 的表单元数据。
> 三处手工同步必然漂移 —— 那是「新增工具后前端表单对不上」这类 bug 的固定来源。
>
> **`agent_hidden` 是硬边界**：`add_image_layer.asset_id` 标了它，不会出现在给模型的
> schema 里。让模型生成 UUID 只有两种结果：幻觉一个不存在的，或者把上下文里
> 见过的别的 ID 串过来。这类参数由界面选择 / 服务端回填。
>
> **给模型的上下文里没有 UUID**：`summarize_doc()` 只给图层名、类型、可见性与层级序号。
> 模型靠名字指认图层（"把背景调亮"），内部 ID 不该出现在它的世界里。
>
> **参数校验失败必须来自服务端**：模型传错类型时，报的是 Pydantic 的错（含字段与原因），
> 不是模型自己瞎猜后写进文档。这一步在 `ToolSpec.parse()`，所有工具共享。

## 环境变量

见仓库根 `.env.example`。缺必填变量时启动即失败并打印缺失清单，不做静默兜底。
