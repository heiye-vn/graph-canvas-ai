# ai-picture-editor（AI 修图智能体）项目分析报告

> 分析日期：2026-10-10 | 分析人：小W
> 被分析对象：`D:/ZSP/Study/Ai Agent/ai-picture-editor`（源自编程导航付费教程，仓库 `yuyuanweb/ai-retouch-agent`）
> **定位：这是 `graph-canvas-ai`（图画智能体）项目的参考项目。** 本报告第六、七、八章均按「如何复用到 graph-canvas-ai」来写。

---

## 〇、一页 verdict

| 维度 | 评分 | 说明 |
|---|---|---|
| 代码真实性 | ★★★★★ | 全链路真落地，无 mock 假链路；唯一 mock 是刻意设计的 provider 实现 |
| 架构设计 | ★★★★☆ | 分层干净、抽象到位；有几处经典的复杂取舍处理得相当漂亮 |
| Agent 深度 | ★★★☆☆ | 「智能」集中在一次性规划，没有观察-反思循环，LangGraph 只用了骨架 |
| 前端工程 | ★★★★☆ | react-konva 画布引擎是真货；组件偶有臃肿（CanvasStage 1087 行） |
| 工程完备度 | ★★★★☆ | 测试/迁移/容器/评测都有；缺 CI 与可观测 |
| 简历价值 | ★★★★★ | 可讲的技术点密度极高，且远高于 CRUD 项目的区分度 |

**一句话**：这是一个**工程质量明显高于大多数付费教程项目**的真实全栈 Agent 应用。它的价值不在「AI 有多聪明」，而在**「怎么把一个会让 LLM 失控的业务做安全」**——服务端计划校验、依赖拓扑排序、人机确认、乐观锁、去重任务队列，这套东西才是你拿去面试时能压住人的部分。

---

## 一、规模与基本盘

| 项 | 数据 |
|---|---|
| 后端 Python | **9,483 行**（其中约 2,600 行测试） |
| 前端 TS/TSX | **7,840 行** |
| 工具数量 | **22 个**（README 宣称 21，实际 22） |
| REST 端点 | **32 个** + 1 个 SSE 流 |
| 数据表 | 7 张（users / assets / tool_runs / edit_sessions / agent_runs / edit_history / session_assets） |
| 提交历史 | 33 次，2026-08-26 → 2026-09-16（约 3 周迭代） |

### 技术栈

```
前端   React 19 + react-konva 10 + Konva + TanStack Query 5 + Zustand 5
       Vite 8 + Tailwind 4 + TypeScript 6 + oxlint
后端   Python 3.13 + FastAPI + SQLAlchemy 2 (asyncpg) + Alembic
       LangChain Core / langchain-openai + LangGraph
       ARQ + Redis(Pub/Sub) + boto3/MinIO + Pillow
CV     rembg(SAM-onnx) + onnxruntime + opencv-headless + rapidocr-onnxruntime
基建   Docker 多阶段构建 + Compose profile + uv
```

注意到 CV 依赖全部放在 `optional-dependencies.cv`，AI 依赖在 `.agent`——**用 optional extra 隔离重依赖**，这是很克制的选择，`uv sync` 默认不装 onnx/rembg，本地跑流程零成本。

---

## 二、架构骨架

```
┌──────────────────── frontend (React 19) ────────────────────┐
│ Landing │ Create │ Candidates │ EditorPage │ Batch │ Marketing│
│                    CanvasStage (Konva 1087行)                │
│            Zustand: canvasView / editorUi / toasts           │
└─────── REST ───────────────┬────────────── SSE ──────────────┘
                             │        /events/runs/{id}
┌────── FastAPI (7302) ──────▼─────────────────────────────────┐
│ routers/  →  services/   →   tools/         →  edits/        │
│ auth      │  tools.py(执行外壳)  base.py(ToolSpec) pixels    │
│ assets    │  agent.py(编排)      22个spec    mask/segment    │
│ sessions  │  sessions.py(历史)              split/render/ocr │
│ runs      │  selections.py(选区)                             │
│ batches   │  images/assets/storage                           │
├───────────┼──────────────────────────────────────────────────┤
│ agent/    │ graph.py(plan→verify)  llm.py(bind_tools)        │
│           │ plan.py(校验/环检测/拓扑/settle)                  │
└───────────┴──────────────────────────────────────────────────┘
       │                    │                      │
   PostgreSQL+JSONB     Redis(ARQ队列           MinIO(S3)
   (业务+计划+文档)      +Pub/Sub+选区缓存)      (图片/遮罩)
                            │
                    ┌───────▼────────┐
                    │  ARQ Worker    │ max_jobs=4, timeout=300s
                    │  app.worker    │
                    └────────────────┘
```

三条独立数据流要分清：

1. **同步 REST**：参数校验 → 执行 → 落库 → 返回。用于「只改 LayerDocument」的轻量工具（翻转/层级/透明度）。
2. **异步 ARQ**：重像素工具（生成/抠图/局部重绘）→ `enqueue(run_tool, run.id)` → Worker 执行 → 每步 `runs.report()` 更新 progress/stage → `events.publish()` → SSE 推给前端。
3. **前端 SSE 订阅**：`GET /events/runs/{run_id}`，先发快照再流式推送，15s 心跳，600s 断开让客户端重连。

---

## 三、6 个真正值钱的设计

### 1. 一处定义、三处消费的工具注册表

`ToolSpec` 的 `params` 是一个 Pydantic Model，它被同时用于：

| 消费方 | 位置 | 用途 |
|---|---|---|
| 服务端校验 | `services/tools.validate()` | `model_validate` 统一入参校验，UI 与 Agent 走同一套规则 |
| LLM function schema | `agent/llm._schema_of()` | `convert_to_openai_function(spec.params)` 生成工具签名 |
| 执行入口 | `ToolSpec.handler` | 统一签名的异步 handler |

**这才是真正的「不漂移」**——不是手写两份 JSON Schema，而是**从同一个 Pydantic 类派生**出模型签名和校验规则。你在 `agentic` monorepo 里做工具时，这是可以直接搬的模式。

配套的 `agent_hidden` 机制尤其值得注意：

```python
# tools/base.py
HIDDEN_MASK = ("mask_asset_id", "revision")

# agent/llm.py
for hidden in spec.agent_hidden:
    parameters.get("properties", {}).pop(hidden, None)
parameters["required"] = [n for n in parameters["required"] if n not in spec.agent_hidden]
```

**素材 UUID、修订号这类内部 ID 绝不暴露给模型**，由服务端从上下文回填（`services/agent._pin_selection()`）。理由写在注释里很实在：选区会在第一步执行后被清除、revision 会自增，不显式钉住后续步骤就拿不到同一块区域了。

### 2. 计划即数据：LLM 输出必须过服务端关卡

这是整个项目最重要的工程判断。链路：

```
LLM tool_calls → [{tool, params}, ...]
   ↓ plan.validate()
     ① spec_of() 工具存在性（未注册直接 UnknownTool）
     ② params model_validate 参数合法性
   ↓ plan.assemble()
     ③ 补全 step id / 默认串行依赖（后步依赖前步）
     ④ 长度上限 MAX_STEPS=8
     ⑤ 依赖存在性检查
     ⑥ Kahn 算法环检测
   ↓ 落库到 agent_runs.plan (JSONB)
   ↓ needs_confirm(steps) → len>1 即转 QUEUED 等人确认
```

`_verify` 节点是 LangGraph 图里的第二个节点——**模型给的计划一律不直接执行**。异常统一转成 `plan=[]` + 一句人话，而不是崩掉。

**这是所有 Agent 产品都应该有但没有的东西。** LLM 会幻觉出工具名、会传错类型、会构造循环依赖，靠 prompt 约束是不可靠的，必须服务端结构性地挡住。

### 3. 图层 × 选区的正交目标模型

```
layer_id      → 改哪一层（纵向）
选区 mask      → 改哪块区域（横向）
两者交集       → 实际作用范围
```

`resolve_layer()` 支持按 id 或**按图层名**查找（`的物体2」`能直接用），没指定时取「最上层可见图像层」——这个默认值同时服务 UI 和 Agent，两边行为一致。

### 4. revision 乐观锁

`EditSession.revision` 每次 `apply_edit` 自增。选区缓存 key 是 `selection:{session_id}`，payload 里带 revision：

```python
async def get(session_id, revision):
    payload = json.loads(raw)
    if payload.get("revision") != revision:
        return None   # 静默失效
```

`_guard()` 里则直接抛 `StaleSelection`。**画布一变，旧选区自动作废**——避免了「图已经变了但遮罩还在，一改就把新图搞坏」。遮罩资产尺寸与画布尺寸不符也显式判为失效，而不是拉伸。

### 5. 去重任务队列 + 幂等

```python
async def enqueue(task, run_id):
    await pool.enqueue_job(task, run_id, _job_id=str(run_id))
```

**run id 直接作为 ARQ job id**，重复投递同一 run 不会产生第二次执行。这个技巧成本极低收益极高。

配合统一的执行外壳 `services/tools.execute()`：状态流转、`ProviderError/ToolError/UnknownTool` 分级捕获、异常统一 rollback、**最后调用 `continue_plan()` 推进下一步**——所有失败兜底集中在一处，具体工具只管返回结果。

### 6. before/after 快照式撤销

`edit_history` 每条记录 `params.before`（操作前快照）和 `result`（操作后快照）。

- `undo`：读当前 seq 的 `before` → `_restore`
- `redo`：读 seq+1 的 `result` → `_restore`
- 新操作时先 `DELETE ... WHERE seq > history_seq`（截断重做分支）
- `HISTORY_LIMIT` 滚动清理

典型的 **command + memento**，比「维护一堆逆向操作」稳健得多。而且 `_append_history` 里有一段很细的产品判断：

> "结果只进图片墙时画布没变，但仍要留一条记录，否则用户在编辑记录里找不到这次生成"

---

## 四、做得好的细节（易被忽略）

| 细节 | 位置 | 为什么好 |
|---|---|---|
| Provider 抽象 Protocol | `providers/base.py` | `ImageProvider` 用 `typing.Protocol` 而非 ABC，结构化子类型；`mock`/`dashscope` 一行配置切换，本地跑通全流程零费用 |
| 参考图一律 base64 内联 | `dashscope._payload` | 注释放得很清楚：本地对象存储模型服务访问不到。这是踩过坑才会写的注释 |
| 结果 URL 立即转存 | `dashscope._download` | 百炼结果 URL 有效期 24h，必须取回转存自有 S3 |
| 编辑接口边长限制 | `_fit_edit_size` | 主动 clamp 到 [512, 2048]，避免服务端报错 |
| CV/OCR 失败降级 | `split._cv_inpaint` → `_blur_inpaint` | OpenCV 不装时用边缘均值+多轮高斯模糊抹平空洞，功能不残废 |
| SAM embedding LRU 缓存 | `segment._embeddings` | 上限 4 条 + OrderedDict + Lock；首次点击算 embedding，后续点击只跑 decoder |
| 同步/异步混跑不闪烁 | `agent._advance` 注释 | "同步的下一步跟这次一起提交，前端不会捞到『上一步完了、下一步还没开始』" |
| 测试独占 Redis DB 1 | `conftest.isolated_redis` | 开发 worker 只听默认库，不会把测试任务抢走 |
| 测试前缀用户 + 定向删除 | `conftest.cleanup_users` | 只删 `test_` 前缀，不会误清开发库真实数据 |
| SSE 不挂 /api 前缀 | `main.py` 注释 | "便于反向代理单独关闭缓冲" + `X-Accel-Buffering: no` |
| 先订阅再读快照 | `events.stream_run` | 避免任务在两步之间结束导致连接一直空等 |

---

## 五、问题与缺口（诚实清单）

### P1 —— 结构性问题

**1. Agent 没有「观察-反思」循环，本质是 one-shot planner**

`graph.py` 只有 `plan → verify → END` 两个节点的线性图。**没有条件边、没有循环、没有 checkpointer**，`langgraph-checkpoint-postgres` 装在 pyproject 里**完全没被使用**（全仓 grep 只有 `langgraph.graph` 一个 import）。

后果：
- 工具执行失败后，用户只能手动点「单步重试」，模型不会看到错误重新规划
- 无法基于执行结果调整后续步骤
- 对话 Agent 每轮独立，不复用之前轮的上下文（靠 `agent_runs` 表存历史但 planner 不读）

这也意味着：**LangGraph 在这里是被大材小用的**，用普通函数调用完全等价。面试时如果被追问「为什么用 LangGraph」，需要有更充分的答案。

**2. 前端工具元数据硬编码，注册表「统一」只统一了一半**

README 宣称「一处定义同时服务 UI 和 Agent」，但工具元**没有通过 API 下发**：

```ts
// frontend/src/api/sessions.ts
export const ACTION_LABELS: Record<string, string> = {
  create_session: '新建会话', switch_current: '切换当前图', ...  // 23 条手写
}
// frontend/src/lib/tools.ts
const UNDOABLE = new Set(['split_layers', 'promote_object_to_layer', ...])  // 11 条手写
```

后端 22 个 spec、前端 23 条标签 + 11 条 UNDOABLE，**三份手工维护**。新增工具必须记得改前端，否则标签显示为空字符串。缺 `/api/tools` 元数据端点是明确的架构缺口。

**3. 零可观测、零 Agent 级评测**

全仓 grep `langsmith|langfuse|opentelemetry|trace`：**零命中**（除 package-lock 里的 sourcemap 依赖）。日志只有 `logging.getLogger`。

规划质量没有在任何地方被度量。`app/eval/` 存在，但它评测的是**确定性图像处理工具**（指标：alpha_iou / mae / psnr / contain / size，对 expect 图做像素对比），**不是 Agent 的规划能力**。

对 `graph-canvas-ai` 而言这是好消息——这两点是参考项目最明显的空白，也正是你做出差异化的位置（见第六章扩展点）。

### P2 —— 工程完备度

**4. 无 CI**：没有 `.github/workflows`。测试依赖真实 Postgres 17 + Redis 7 + MinIO（`conftest` 直连），本地能跑但无人自动验证。

**5. 弱默认凭据散落**：`config.py` 里 `jwt_secret="dev-only-secret-please-change-in-production"`、`s3_access_key="retouch"/"retouch_dev"`，`docker-compose.yml` 里同样写死。**缺配置时的表现是「用了不安全的默认值」而不是「启动即报错」**——把「配置没传」伪装成「配置传了但不对」，排查时会往完全错误的方向走。`graph-canvas-ai` 别继承这个习惯。

**6. `lru_cache` 全局单例的测试污染**：`planner()`、`_graph()`、`redis_client()`、`get_image_provider()`、`get_settings()` 全用 `lru_cache`。conftest 靠手动 `cache_clear()` 逐个清理，脆。

**7. 前端组件偏大**：`CanvasStage.tsx` 1087 行、`LayerPanel.tsx` 673 行、`BatchPage.tsx` 435 行、`MarketingPage.tsx` 432 行。K 线所需的 canvas/transform/selection/selectionHistory 逻辑没有抽成 domain 层。

**8. 评测覆盖窄**：`dataset/` 只有 2 张源图 + 2 张 expect 图，`cases.json` 规模很小，算 demo 级别而非可用回归基线。

### P3 —— 小瑕疵

- README 说「21 种编辑工具」，实际注册表 22 个
- `promote_object_to_layer` 在前端 `ACTION_LABELS` 存在，但 agent_hidden 的 `HIDDEN_MASK` 命名与实际用途已经泛化（不止 mask）
- `sessions.load()` 注释写着「仅限后台任务」，但实际被 `tools/_record` 调用，边界靠自觉而非类型约束

---

## 六、对 `graph-canvas-ai` 的复用价值

### 能直接搬过去的（成本从低到高）

> 由于 `graph-canvas-ai` 目前是空仓，下面这些不是「迁移」而是**「照着实现」**——参考项目已经替你踩完了所有坑，你按它的结构写一遍即可，省掉全部试错成本。

| # | 模式 | 实现成本 | 收益 |
|---|---|---|---|
| 1 | **run id 作为 job id 去重** | 10 分钟 | 一行代码消灭重复执行问题 |
| 2 | **`agent_hidden` 隐藏内部 ID** | 1 小时 | 模型不再幻觉出 asset_id / session_id |
| 3 | **Pydantic Model → OpenAI function schema** | 2 小时 | 消灭手写 JSON Schema 的漂移 |
| 4 | **服务端计划校验（存在性/合法性/环检测/长度）** | 1 天 | 多步规划最缺的那张安全网 |
| 5 | **统一执行外壳集中状态流转 + 分级异常捕获** | 半天 | 新工具只需要写 handler |
| 6 | **revision 乐观锁让派生态失效** | 半天 | 选区/上下文/缓存一律适用 |
| 7 | **before/after 快照式 undo/redo** | 1 天 | 比维护逆操作稳健得多 |
| 8 | **mock provider 分层** | 半天 | 无 API Key 也能跑通全流程 |

### 别照抄的三处（参考项目的历史包袱）

| 别抄 | 原因 | 你应该怎么做 |
|---|---|---|
| 前端硬编码 `ACTION_LABELS` / `UNDOABLE` | 三份手工维护必然漂移 | 一开始就做 `/api/tools` 元数据端点，前端标签由注册表驱动 |
| `jwt_secret` / S3 弱口令默认值 | 缺配置时静默用不安全默认值 | 必填变量用 `${VAR:?提示}` fail-fast，或直接抛错 |
| 评测只覆盖像素工具 | 规划质量无人度量 | 直接做 `{指令 → 期望工具序列}` 的 Agent 评测集 |

### 简历高价值转化点（按「碾压 CRUD」程度排序）

1. **LLM 输出不可信 → 服务端结构性防御**：工具存在性、参数强校验、DAG 依赖校验、Kahn 环检测、步数上限。**这是任何 Agent 产品都必须回答的安全问题**，能讲清楚这个，面试官立刻知道你不是玩具级玩家。
2. **人机协作（HITL）闭环**：多步计划转 QUEUED → 计划卡片 → 确认/单步重试/取消后续 → 已排队任务级联取消。**这是企业级 Agent 的分水岭**。
3. **UI 与 Agent 共享一套工具契约**：一个 Pydantic 类同时派生模型签名、服务端校验、UI 参数表单，并显式隐藏内部 ID——「一处定义，三处消费」。
4. **ASQ + Redis Pub/Sub + SSE 的实时进度**：ARQ job id 幂等去重、15s 心跳、600s 主动断开重连、先订阅后快照避免竞态。
5. **声明式图层文档 + 快照式撤销**：工具只改 JSONB 文档，像素合成由渲染层完成；before/after memento 替代逆操作。
6. **乐观锁处理派生态**：revision 自增使旧选区/遮罩自动失效，尺寸不符显式判废而非静默拉伸。

### 差异化扩展点（做出来就能超过参考项目）

> 前 2 条恰好是你 README 里已经宣称、但参考项目给不了的能力；后 3 条补上参考项目最明显的空白。做完这 5 条，`graph-canvas-ai` 的技术叙事就在参考项目之上了。

1. **Agent 思维链（CoT）流式输出**：README 已宣称，参考项目完全没有。设计一条独立的 SSE 事件类型承载 planner 的中间输出，与 tool run 进度流并行推送。**这是最能体现「Agent 感」的一个功能，也是面试演示时最抓眼球的一帧。**
2. **真 LangGraph 状态机 + 反思循环**：参考项目只有 plan→verify 直线。做成带条件边的图：执行失败 → 错误回灌 → 重新规划，并把 `langgraph-checkpoint-postgres` 真正用起来做 checkpoint + 断点续跑。**这样 README 里「LangGraph 图结构状态机」这句话才站得住。**
3. **接 Langfuse / LangSmith 做全链路 trace**：给每次 `respond()` 打 trace，记录 planner prompt / tool_calls / 校验失败原因 / 每步耗时 token。**并且把「计划校验拒绝率」做成一个可观测指标**——这是衡量 Agent 稳定性的关键指标，多数人想不到。
4. **Agent 规划质量评测集**：仿 `app/eval/` 的样子做一份 `{用户指令 → 期望工具序列}` 的评测集，指标用 tool-F1 / 序列精确匹配 / 参数槽位准确率。**这是回答「你怎么证明 Agent 好用」的唯一硬答案。**
5. **CI + Prompt Regression**：给 `_SYSTEM` prompt 建版本快照，每次改动跑一遍 plan 评测集，做 prompt 变更的回归门禁。

---

## 七、跑起来参考项目看看（成本估算）

> 建议动手前先跑一遍，有了体感再照着写 `graph-canvas-ai`，比干读代码快得多。

| 步骤 | 耗时 | 风险 |
|---|---|---|
| `docker compose up -d`（PG/Redis/MinIO） | 3 min | **和 `graph-canvas-ai` 用同一套端口**，两个项目不能同时起；参考项目绑 0.0.0.0，你的新项目绑 127.0.0.1，先 down 掉再切 |
| `uv sync --all-extras` | 5–15 min | `--all-extras` 会拉 rembg + onnxruntime，体积大；只想跑通流程可只 `uv sync` + mock provider |
| `alembic upgrade head` | 10 s | 7 个迁移版本，无风险 |
| `uvicorn` + `arq worker` 双终端 | 10 s | 必须同时起，否则工具永远 QUEUED |
| 前端 `npm i && npm run dev` | 3 min | Vite 8 端口 7301 |
| **无 API Key 也能跑全流程** | — | `IMAGE_PROVIDER=mock`，但**对话 Agent 不可用**（`planner()` 强制要求 DASHSCOPE_API_KEY） |

**最小验证路径**：起中间件 → mock provider → 注册账号 → 上传一张图 → 进编辑器 → 手动点「去背景 / 拆层 / 调色」。这条链路不需要一分钱。要验证 Agent 对话，必须有百炼 Key（规划模型 `qwen-plus`）。

---

## 八、作为 `graph-canvas-ai` 参考项目的落地对照

> 背景修正：本项目是 `graph-canvas-ai`（图画智能体）的参考项目，不是与 `agentic` monorepo 的对照对象。
> `graph-canvas-ai` 当前状态：**0 个提交**，`backend/` 与 `frontend/` 为空目录，只有基建配置（Dockerfile / compose / .env.example / README）已就位。

### 8.1 README 宣称的能力，参考项目到底给不给得了

| graph-canvas-ai README 宣称 | 参考项目实现情况 | 能不能直接抄 |
|---|---|---|
| 「21+ 种图像原子操作」 | **22 个**，`tools/__init__.py` 全注册 | ✅ 完整可抄，README 反而少写了 1 个 |
| 「图层拆分」 | `edits/split.py` + `tools/layers.py`，主体/背景/文字三层 | ✅ 完整可抄 |
| 「文字层剥离重构」 | `20da5b2` 的 `set_layer_text` + `remove_text`（抠原字像素） | ✅ 完整可抄，这是最后一个代码提交，成熟度最高 |
| 「局部遮罩 Mask」 | `services/selections.py` + `edits/mask.py` + `segment.py`（SAM）+ `tools/region.py` | ✅ 完整可抄 |
| 「SSE 实时推送执行进度」 | `routers/events.py` + Redis Pub/Sub + ARQ | ✅ 完整可抄 |
| 「异步任务调度」 | `queue.py` / `worker.py` / `tasks/tools.py` | ✅ 完整可抄 |
| 「**LangGraph 图结构状态机**」 | ⚠️ **只有 plan→verify 线性两节点，无条件边、无循环、无 checkpointer** | ❌ 抄不到，要自己设计 |
| 「**Agent 思维链（CoT）流式反馈**」 | ⚠️ **完全没有**。SSE 只推 tool run 的 `progress/stage`，不推任何 LLM 思考过程 | ❌ 抄不到，要自己设计 |
| 「多步规划 Planning & Execution」 | `agent/plan.py` 校验 + `services/agent.py` 编排 | ✅ 可抄，但注意它没有反思/重规划 |

**结论：README 里最有野心的两条（状态机、思维链），恰恰是参考项目给不了的。** 剩下 7 条都有现成的成熟实现可以照搬。

这不是坏事——**这两条正好是你做出差异化的地方**。参考项目把「安全执行」做透了，但「可解释性」完全没做；你在它的骨架上补上思维链流式输出 + 真状态机（带反思循环），项目的技术叙事就比参考项目高一档。

### 8.2 建议的落地顺序（按参考项目的提交节奏反推）

对照第七章的 33 个提交，主干上真正立架构的只有 3 个（`9770db9` 异步基建 / `c200587` 工具注册表+Agent / `fe650d6` 多步计划校验）。建议按这个顺序推进：

| 阶段 | 目标 | 参考提交 | 产出 |
|---|---|---|---|
| 1 | 骨架 + 鉴权 + 素材存储 | #1–4 | 能注册登录、上传图片 |
| 2 | **Provider + ARQ + SSE** | #5 | 文生图跑通，进度实时可见 |
| 3 | **编辑会话 + LayerDocument** | #9 | 画布能显示、能切换当前图 |
| 4 | **工具注册表 + Agent 单步** | #10 | 一句话能调一个工具 |
| 5 | 确定性工具 + 撤销 | #11 | 裁剪/翻转/调色/去背 + 线性 undo |
| 6 | 选区 + 局部编辑 | #16 | SAM 点选、局部消除替换 |
| 7 | 拆层 | #17、#31 | 主体/背景/文字三层 |
| 8 | **多步计划校验 + 人机协作** | #19 | 这一步做完才有「Agent 产品」的样子 |
| 9 | 增强/营销/批量 | #15、#22、#23 | 功能补齐 |
| 10 | 评测 + 打磨 | #24–27 | eval 模块、交互细节 |

### 8.3 复用时的两个具体坑

**① 端口会撞。** 两个项目用同一套端口：7311(PG) / 7312(Redis) / 7313-7314(S3) / 7302(API)。参考项目 compose 里是 `"7311:5432"`（绑 0.0.0.0），你的新项目已改成 `127.0.0.1:7311`。**同时起两个项目必然冲突**——`docker compose down` 参考项目的中间件再起你的。

**② `.env.example` 的对象存储注释和实际配置不一致。**

```
.env.example:   # 对象存储（SeaweedFS，S3 兼容）
                # 容器内互访用 http://storage:8333
compose.yml:    image: pgsty/silo:latest   ← MinIO 分支，不是 SeaweedFS
                service 名是 minio，不是 storage
```

注释里的服务名 `storage:8333` 在 compose 中**根本不存在**。照注释写 `S3_ENDPOINT` 会连不上。实际应为 `http://minio:9000`（容器间）或 `http://127.0.0.1:7313`（宿主机）。这个注释是从 SeaweedFS 方案改到 silo 时的残留，建议顺手改掉。

顺带一提，你换 `pgsty/silo` + 绑 `127.0.0.1` 这两个决定都比参考项目更稳妥（参考项目用 `0.0.0.0` 且 MinIO 官方镜像已从 Docker Hub 下架），这部分做得对。

---

*报告完*
