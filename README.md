# GraphCanvasAgent (图画智能体) - 自然语言驱动的多模态图像编辑工作台

GraphCanvasAgent 是一个基于 **React 19 + FastAPI + LangChain/LangGraph + Konva** 构建的全栈 AI 图像编辑智能体系统。

不同于传统的单步生图工具，本项目利用 **LangGraph 状态机** 与 **大模型多步规划能力**，允许用户通过自然语言完成复杂的复合修图任务；前端依托 **Konva 渲染引擎** 实现了可交互的高性能画布，支持图层精准解耦、文本重绘与实时流式状态反馈。

### 核心特性

- 🤖 **Agent 智能调度与多步规划**：基于 LangGraph 构建图结构状态机，将复杂修图意图拆解为多步执行计划（Planning & Execution）。
- 🎨 **高性能交互画布**：基于 Konva 打造，支持图层拆分、文字层剥离重构、局部遮罩（Mask）与多图元混合排版。
- 🛠 **全链路多模态工具箱**：内置 21+ 种图像原子操作，涵盖 文生图、局部重绘（Inpainting）、语义抠图（Matting）、分辨率超分等。
- ⚡ **生产级异步工程架构**：
  - 后端基于 FastAPI 构建高性能异步接口。
  - 采用 SSE (Server-Sent Events) 协议实时向前端推送 Agent 思维链（CoT）与执行进度。
  - 内置异步任务调度机制，保障耗时生图/推理任务的非阻塞运行。

---

## 快速开始

```bash
# 1) 中间件：Postgres 17 / Redis 7 / 对象存储
docker compose up -d

# 2) 后端（依赖可选；CV 体积大，M6 才需要）
cd backend
uv sync --extra dev                     # 或再加 --extra agent / --extra cv
uv run uvicorn app.main:app --port 7302 --reload

# 3) 异步任务 worker（M2 起**必须与 API 同时跑**，再开一个终端）
uv run arq app.worker.WorkerSettings

# 4) 前端
cd frontend
npm install --ignore-scripts             # 本机必须带该参数，见 frontend/README.md
npm run dev                              # http://localhost:7301
```

打开 <http://localhost:7301>，落地页会实时显示后端 `/ready` 的三项依赖状态（Postgres / Redis / 对象存储）。

> ⚠️ **worker 必须挂着**：容器只负责 Postgres / Redis / 对象存储，任务执行在 worker 进程里。
> 少跑它的表现是生成任务永远停在「排队中」——不是接口坏了。

> ⚠️ 本机 `localhost` 会解析到 IPv6 `::1`，而 compose 端口只绑 `127.0.0.1`。
> 环境变量里一律写 `127.0.0.1`，否则 Redis 会连接超时。

## 工程结构

```
backend/    FastAPI：config（必填 fail-fast）/ db / routers / services / tools / agent / providers / eval
frontend/   React 19：api / domain（画布领域层）/ layouts / hooks / components / pages
docs/       开发计划与参考项目分析报告（阶段性文档，开发完成后从仓库移除）
```

## 已具备的形态

`/` 公开落地页 → `/login`（可携带 prompt 接力）→ `/create` 创作（生成 + 上传 + 素材一屏）
→ `/candidates/{runId}` 候选图（可刷新可分享）→ `/assets` 素材库。工作台统一套左侧导航。

## 开发进度

施工图见 [`docs/开发计划.md`](docs/开发计划.md)。

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 基建：Docker / compose / 对象存储选型 | ✅ |
| M1 | 骨架 + 鉴权（bcrypt + JWT）+ 素材上传（可切换直传模式） | ✅ |
| M2 | Provider 抽象 + ARQ 任务队列 + SSE 事件流（协议定死，含 CoT 预留） | ✅ |
| M3–M8 | 画布、工具注册表、选区局部编辑、多步计划 | ⬜ |
| M9 | 差异化：CoT 流式 / 状态机反思 / 可观测 | ⬜ |
| M10–M11 | 评测 CI、功能补齐 | ⬜ |

## 文档

- [`docs/开发计划.md`](docs/开发计划.md) —— M0–M11 施工图，含每阶段的验收标准与「别照抄参考项目」清单
- [`docs/ai-picture-editor-项目分析报告.md`](docs/ai-picture-editor-项目分析报告.md) —— 参考项目的能力与缺口审计
- [`backend/README.md`](backend/README.md) / [`frontend/README.md`](frontend/README.md) —— 各自的分层与命令
