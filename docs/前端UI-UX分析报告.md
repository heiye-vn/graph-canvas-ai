# graph-canvas-ai 前端 UI/UX 分析报告

> 分析日期：2026-10-20 · 分析对象：`frontend/`（React 19 + antd 6 + Tailwind v4 + Konva）

---

## 一、总体评价

这是一套**工程素养明显高于平均水平**的前端：设计令牌化、领域逻辑下沉纯函数、注释密度极高且都在解释"为什么"。"诚实 UI"原则贯穿全库——能力不存在就不渲染按钮、失败不默默消失、token 缺失不做估算。主要短板在**移动端适配缺失、快捷键空头支票、字体栈两处不一致、以及若干死代码/色值游离**。

综合评分（主观）：功能设计 8.5 / 交互细节 9 / 视觉一致性 7.5 / 可访问性 6.5 / 可维护性 7.5。

---

## 二、信息架构与功能设计

### 2.1 路由与页面（`src/App.tsx`）

| 路径 | 页面 | 备注 |
|---|---|---|
| `/` | LandingPage | 公开落地页 |
| `/login` | LoginPage | 公开 |
| `/create` | CreatePage | 创作中心 |
| `/assets` | AssetsPage | 素材库 |
| `/candidates/:runId` | CandidatesPage | runId 在 URL，可刷新/分享 |
| `/editor` / `/editor/:sessionId` | EditorIndexPage / EditorPage | 会话列表 / 编辑器（懒加载） |
| `/editor/:sessionId/export` | ExportPage | 独立导出页（懒加载） |
| `/metrics` | MetricsPage | 懒加载（echarts ~400KB） |

设计上三个亮点：

1. **状态入 URL**：sessionId、runId 都进路径，页面可刷新、可分享、可回退——工具型产品的基本功，很多团队做不到。
2. **路由级代码分割**：Konva（gzip ~100KB）、echarts（~400KB）均按需加载，注释里写明了动机（"只有打开指标页的人需要付这份带宽"）。
3. **鉴权收敛**：`ProtectedRoute` 在 bootstrap 期间显示 Spin 而非闪烁放行；401 全局同步登出。

### 2.2 编辑器三栏外壳

```
顶栏 EditorToolbar（h-11）
┌────────────┬──────────────────────────┬────────────┐
│ 左 ChatPanel│ 中 CanvasStage + 胶卷条    │ 右 检查器    │
│ 304px 固定  │ flex-1，深色沉浸区         │ 304px 可收起 │
└────────────┴──────────────────────────┴────────────┘
```

- 左右栏各 304px 固定宽度（Tailwind v4 任意 spacing `w-76`），中栏 `min-w-0 flex-1`。
- 右栏可整体收起，收起后画布右缘留竖排文字把手（`writing-mode: vertical-rl`）——细节用心。
- 文件头注释写明四条原则：session id 在 URL、文档是唯一真相源、所有改动走工具入口、视图状态不进文档。**架构契约直接刻在组件头部**，是可维护性的关键实践。

---

## 三、视觉与样式体系

### 3.1 设计令牌（Tailwind v4 `@theme` + CSS 变量）

- 完整语义色板：`ink / muted / faint / line / paper / canvas / soft`，外加画布深色工作台三色 `stage #131417 / stage-card #1c1d22 / stage-border #282a30`。
- 圆角/阴影令牌化：`--radius-card/control/panel`、`--shadow-card/control/lift/stage`。
- 品牌色 `#2563eb`（蓝）统一贯穿 antd token、Transformer 手柄、激活态。

### 3.2 antd 主题（`src/lib/antdTheme.ts`）

- 微圆角体系（6/4/8）、控件高度 32/26/40、Slider 品牌蓝轨道、Button fontWeight 500。
- 另导出 `darkPrimaryTheme`（深主按钮）与 `accentTheme`（粉）两个局部主题。
- 中文 locale（zhCN）已配置。

### 3.3 主题策略：亮色工作台 + 局部深色沉浸区

**没有全局暗色模式**，而是刻意让画布中栏与胶卷条固定深色（图像编辑器的行业惯例，深色衬底让色彩判断更准），其余界面亮色。深色卡内文字用 Tailwind 任意选择器手动翻转。定位清晰，但意味着未来若要做全局暗色，深色区文字翻转逻辑会翻倍复杂。

### 3.4 字体 ⚠️ 存在不一致

三处定义、**两处不同步**：

| 位置 | 字体栈 |
|---|---|
| `antdTheme.ts` token.fontFamily | Plus Jakarta Sans → 系统 → Segoe UI → PingFang SC → Hiragino Sans GB → **Microsoft YaHei UI** → Microsoft YaHei |
| `index.css` body | Plus Jakarta Sans → 系统 → PingFang SC → **HarmonyOS Sans SC** → Microsoft YaHei → Segoe UI（顺序不同！） |
| `CanvasStage.tsx` 画布文字层 | `"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC"` —— 刻意与服务端 Pillow 的 msyh.ttc 对齐，保证"所见即拍平所得" ✅ |

问题：antd 组件与普通文本在 Windows/macOS 上可能落到**不同的中文字体**（YaHei UI vs YaHei，或是否经过 HarmonyOS），同页出现细微字形差异。建议两处逐字对齐。

值得称道：等宽数字 `font-mono tabular-nums` 大量使用（分辨率、缩放%、不透明度、历史序号），数字不跳动，专业感强。

---

## 四、交互设计细节（亮点密集区）

### 4.1 顶栏工具条：能力驱动渲染

`EditorToolbar.tsx` 固定 9 个动作平铺（裁剪/翻转×2/去背景/换背景/扩图/超分/调色/拆层），溢出时横向滚动而非折叠。核心设计：

> `visible = PRIMARY_ACTIONS.filter(item => available.has(item.tool))` —— 后端 `/api/tools` 没有的工具**连按钮都不渲染**。注释原话："摆一个点下去只会弹错的假按钮，比少一个按钮恶劣得多。"

`needsLayer` 项无图像层时 disabled；裁剪模式顶栏整体切换为比例胶囊组（自由/1:1/4:5/9:16/16:9）+确定/取消——**模式化 UI 而非弹窗**，符合编辑器心智。

### 4.2 画布交互（CanvasStage.tsx，855 行，全库交互密度最高）

- **单 scale 坐标系**：坐标始终是文档像素，不做屏幕坐标换算——从根上消除一类换算 bug。
- **fit 算法**：双向取 min 且 `Math.min(..., 1)`（小图不放糊），留 32px 余量防亚像素滚动条（注释记录了 871.23 的坑）。
- **中心锚点几何**：图层 x/y 记几何中心、offset 记半宽高——旋转绕中心不甩出画布（血泪教训沉淀）。
- **缩放补偿手柄**：裁剪框 `anchorSize = 10 / scale`、虚线 `dash = [7/scale, 5/scale]`，缩到 30% 手柄依然点得到。
- **以中心缩放的 boundBoxFunc**：把新框平移到与旧框同心。
- **手势 = 意图采集**：拖动/变换全部在 `onDragEnd/onTransformEnd` 松手后统一走 `transform_layer` 写文档，一次手势一条撤销记录。
- 加载失败图层画橙色虚线占位 `MissingLayer`，把"图没下载下来"与"拆层丢了东西"区分开，另有预签名过期自动重拉一次的自愈逻辑。

### 4.3 调色面板：性能分级 + 预览/落库分离

- 11 参数（基础 8 + 细节 3），拖动只改本地 `previewAdjustments` 预览，"应用"才走 `adjust_color` 落撤销栈。
- **性能分级**：锐化/清晰度是 unsharp 邻域运算，标记 `live: false` 松手才预览；其余 9 项拖动即预览。
- 切图层用 `key={selectedLayer.id}` 强制重置防串态。

### 4.4 变换面板

本地 state + 松手提交（注释解释了为什么不能直接绑文档值：拖动中受控值会把 thumb 按回去）；缩放基准是画布宽度防基准漂移；独创 `NumberField` 可点开手输（Enter/Esc/夹取）；未选图层显示虚线空态而非隐藏面板。

### 4.5 CoT 流式与对话

- 分块规则是纯函数（`domain/cot.ts` + 单测）：thought 增量原地拼接不插空格，其余 kind 独立成块，首帧 seq 做 React key。
- 四类增量四种颜色（思考 muted / 调用 brand / 观察 ink / 反思 danger）；planning 默认展开，流收束自动折叠成摘要行，**用户手动展开后不再抢控制权**（`touched` 标记）——尊重用户的细节。
- 一轮对话 = 一条 AgentRun，含状态 Tag、结构化步骤列表、动作栏、审计 TraceModal。

### 4.6 其他

- **胶卷条**：64×64 缩略图、激活 ring、隐藏层压暗、空态也占位。
- **图层列表**：自定义行盒模型（antd List 在窄栏会把内容挤到逐字换行——注释记录了教训），选中/当前图两档蓝色态，`role="button" tabIndex aria-pressed` + Enter/Space 键盘支持；刻意不放"成层"按钮（后端没此工具）。
- **导出页**：顶栏 PNG（Konva 直出零等待）与导出页 ZIP（服务端拍平三档投放位）分工写进文件头。
- **指标页**：echarts 按需注册（不进整包 1MB）、ResizeObserver 自适应、明确提示"未返回用量的不做估算"；研发指标（拒绝率/prompt 版本）刻意不对用户展示。

---

## 五、加载态 / 空态 / 错误态

覆盖分层次，相当完善：

| 场景 | 实现 |
|---|---|
| 路由懒加载/鉴权 | Spin 居中 |
| 页面数据 | Skeleton（编辑器/导出/指标）、Spin（素材/候选） |
| 会话不存在 | 统一 `Result status="404"` + 返回按钮（三处一致） |
| 画布素材失败 | 加载角标 + MissingLayer 占位 + Alert 带重载 + 自愈重拉 |
| 操作失败 | Alert 区分类型（保存回滚 / 选区 409）；排队任务失败 message.error 不默默消失 |
| 空态 | Empty / 虚线框 / 差异化指引文案（素材库按 Tab 给 CTA） |

全库 12 处 message 无 notification，反馈克制统一。

---

## 六、问题清单（按优先级）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 1 | **快捷键空头支票**：撤销/重做 Tooltip 标注 Ctrl+Z / Ctrl+Y，但全项目无对应 keydown 监听 | EditorToolbar | 补全局监听（注意输入框聚焦时豁免），或先删 Tooltip 里的快捷键提示 |
| 2 | **字体栈两处不一致**：antdTheme 有 Hiragino/YaHei UI，index.css 有 HarmonyOS 且 Segoe UI 顺序不同 | antdTheme.ts vs index.css | 逐字对齐为一份 |
| 3 | **死代码**：`QuickToolbar.tsx`（旧顶栏方案）无任何引用 | components/editor/ | 删除 |
| 4 | **深色色值游离**：CandidateStrip 硬编码 `bg-[#121316] border-[#23252a]`，与 @theme 的 stage 三色肉眼几乎相同但不同步 | CandidateStrip.tsx | 收敛到 stage 令牌 |
| 5 | **移动端未适配**：编辑器三栏定宽 304+304，导航依赖 hover 展开，窄屏直接挤死画布 | EditorPage / WorkbenchLayout | 至少加窄屏提示；中期考虑右栏抽屉化 |
| 6 | **`select-none` 滥用**：根容器整片禁选，用户无法复制 CoT 内容、错误信息、会话标题 | WorkbenchLayout / EditorPage 等 | 收窄到按钮/把手等操作区 |
| 7 | **可访问性缺口**：CoT 流式区与进度卡无 `aria-live`；画布位图无替代文本 | CoTStream / RunProgress | 加 `aria-live="polite"` |
| 8 | **侧栏不可调宽**：左右栏写死 304px | EditorPage | 低优先级，可加拖拽分栏 |
| 9 | **EditorPage.tsx 1045 行、state 20+**：裁剪/选区/对比/调色/排队全挤一个组件 | EditorPage.tsx | 按模式抽 hook（useCropMode / useSelectionMode 等） |
| 10 | **antd 内联样式优先级战争**：大量 `h-7!` `text-xs!` 后缀覆盖 | 多处 | 关注 antd 6 后续版本兼容性 |

---

## 七、值得作为团队范式的实践

1. **诚实 UI**：能力不存在不渲染、失败不静默、数据不估算。
2. **注释解释"为什么"**：871.23 亚像素坑、光标双写冲突、滑杆不能绑文档值……每个坑都留在了代码里。
3. **领域逻辑下沉**：`domain/` 纯函数（cot/layerDoc/pixels）带 vitest 单测，UI 组件保持薄。
4. **一次手势一条历史**：意图采集与文档写入分离，撤销栈干净。
5. **前后端运算顺序契约**：调色 11 参数前端 pixels.ts 与服务端 render.py 严格同序——跨端一致性的正确做法。

---

*关键文件索引见各节内引用，均位于 `D:\ZSP\Study\Ai Agent\graph-canvas-ai\frontend\src\` 下。*
