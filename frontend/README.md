# 前端（React 19 + Vite）

## 目录

```
src/
├── api/         REST 与 SSE 客户端；工具元数据统一从 /api/tools 拉取（M4）
├── domain/      ★ 画布领域层：layerDoc / transform / selection / history
│                  刻意先于组件编写——参考项目的 CanvasStage 长到 1087 行就是没抽这层
├── layouts/     WorkbenchLayout：左侧导航 + <Outlet />，全站外壳只有这一份
├── hooks/       useRunStream（SSE 流 → 组件状态）
├── lib/         brand / marketing（文案集中）/ antdTheme（组件库主题）
├── components/  通用件：BrandMark / PageHeader / AssetCard / RunProgress / ProtectedRoute
│                landing/：落地页专属组件（Hero / PromptComposer / Showcase / Steps / CTA）
├── stores/      Zustand：canvasView / editorUi / agentRun / toasts
└── pages/       Landing（公开）/ Assets / Create / Candidates / Editor
```

## 路由

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | LandingPage | **公开**落地页，不套 WorkbenchLayout，不要求登录 |
| `/login` | LoginPage | 支持 `state:{next,prompt}` 接力，登录后直达目标页 |
| `/create` | CreatePage | 创作起点：生成 + 上传 + 历史素材一屏 |
| `/candidates/:runId` | CandidatesPage | 候选图，**可刷新、可分享** |
| `/assets` | AssetsPage | 素材库（全量列表 + 删除） |
| `/editor` | EditorPage | M3 接入 Konva 画布 |

`/login` 之外的工作台页面全部包在 `ProtectedRoute` → `WorkbenchLayout` 两层布局路由里，
页面只写内容区。

> 落地页输入框支持把 prompt 一路带到创作页：
> 未登录时先跳 `/login` 并带上 `{next:'/create', prompt}`，登录成功后 LoginPage
> 再把 prompt 接力给 CreatePage。**别让用户在两个页面上重复输入同一句话。**
>
> 落地页的能力卡片带 `ready` 标记，未上线的能力会打「即将上线」——
> 落地页不该宣称还没做出来的功能。

> **候选页为什么必须独立成路由**：run id 在 URL 上才谈得上刷新恢复与分享。
> 内嵌方案里 run id 只活在内存，刷新一下这次生成的图就全丢了。
> 首屏数据来自 REST（`GET /runs/{id}` + `GET /runs/{id}/assets`），
> SSE **只负责还在跑的任务**的实时增量 —— 事件流从不做唯一数据源。

## 命令

```bash
npm install --ignore-scripts   # ⚠️ 见下方「安装踩坑」
npm run dev      # http://localhost:7301（已配代理到后端 7302）
npm run build    # 产物 dist/，由后端同源托管
npm run lint
```

### 安装踩坑（本机必读）

安装必须带 `--ignore-scripts`。原因：

esbuild 的 postinstall 会 `spawnSync node esbuild --version` 做二进制校验，在本机稳定报
`EBUSY`（Windows 文件锁），install 中断后 **optional 依赖 `@esbuild/win32-x64` /
`@rollup/rollup-win32-x64-msvc` 不会被安装**，于是构建时报
`MODULE_NOT_FOUND` 或 "The package @esbuild/win32-x64 could not be found"。

这两个原生包本来就是靠 optionalDependencies 提供的，postinstall 只是校验，跳过即可。
若已经装坏了，正确修法是 **整个 `node_modules` 删掉重装**，不要逐个 `--no-save` 补
（下次 `npm install` 会把它们当成多余包清掉）。

## UI 组件库：antd 6

控件一律走 **antd**（`antd@6` + `@ant-design/icons@6`，无需 React 19 兼容补丁）。
理由很实际：原生 `<select>` 的下拉面板是操作系统自绘的，和页面主题完全两个世界，
是界面显得「拼凑」的最大单一来源；手拼 SVG 图标也存在同样问题——线条粗细、
视觉重量凑不成一套。

三条硬规矩：

1. **主题只有一处真源**：`src/index.css` 的 Tailwind token 与 `src/lib/antdTheme.ts`
   的 antd token 必须一一对应。改动时两处同步，否则 antd 组件和手写部分一眼两套系统。
2. **主色只允许一个例外**。`colorPrimary` 的语义是「整页最该点的那一下」，
   页面上出现第二个主色层级就崩了。确需例外时（登录页深色提交按钮、
   落地页深色区块上的强调色 CTA）用**局部 `ConfigProvider` 只包住那一个按钮**，
   主题对象统一放在 `lib/antdTheme.ts` 里导出，不要在组件里现写十六进制。
3. **不再出现原生 form 控件**：`<select>` / `<input>` / `<textarea>` / `<button>` 一律换成
   antd 对应件。例外只有薛定谔式的场景性元素（纯装饰 SVG 示意图）。

> ⚠️ **antd 的 CSS-in-JS 是运行时注入的，加载顺序在 Vite 产出的样式表之后**，
> 同优先级下会盖掉 Tailwind 类。用 Tailwind 覆盖 antd 组件样式时必须加 `!` 后缀
> （v4 语法：`px-3!`，不是 v3 的 `!px-3`）。已知必须这么写的只有
> `WorkbenchLayout` 的退出按钮。

## 约定

- 业务接口走 `/api`，探针与 SSE 走根路径（`/ready`、`/events`），已在 `vite.config.ts` 配好代理。
- 工具标签与参数表单**全部由后端 `/api/tools` 下发**，前端不硬编码任何工具名清单。
- 素材卡统一用 `components/AssetCard` —— 创作页历史素材、素材库、候选页此前有三份
  figure 各自为政，改一次圆角必然漏两处。
- 构建产物按 `react` / `antd` / 业务代码分三块：antd 体积占了一半以上但几乎不变，
  单独成块可以让改一行业务逻辑不必让用户重新下载整个组件库。
