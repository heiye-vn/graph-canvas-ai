# 前端（React 19 + Vite）

## 目录

```
src/
├── api/         REST 与 SSE 客户端；工具元数据统一从 /api/tools 拉取（M4）
├── domain/      ★ 画布领域层：layerDoc（M3 已落地）/ events / upload
│                  刻意先于组件编写——组件只消费规则，不在自己身上定义规则
├── layouts/     WorkbenchLayout：左侧导航 + <Outlet />，全站外壳只有这一份
├── hooks/       useRunStream（SSE 流 → 组件状态）/ useCreateSession（开会话的统一入口）
├── lib/         brand / marketing（文案集中）/ antdTheme（组件库主题）
├── components/  通用件：BrandMark / PageHeader / AssetCard / RunProgress / ProtectedRoute
│                editor/：编辑器专属件，三栏外壳各归其位 ——
│                         ChatPanel（左：对话）/ QuickToolbar（顶：快捷工具）/
│                         CanvasStage + CandidateStrip（中：画布 + 候选图条）/
│                         LayerPanel + TransformPanel + ToolPanel + HistoryPanel（右）/
│                         adjustedSource（离屏调色）
│                landing/：落地页专属组件（Hero / PromptComposer / Showcase / Steps / CTA）
├── stores/      Zustand：canvasView / editorUi / agentRun / toasts
└── pages/       Landing（公开）/ Assets / Create / Candidates / Editor（索引 + 详情）
```

> ⚠️ **图层文档必须前后端一致**：`domain/layerDoc.ts` 与后端
> `app/schemas/layer_doc.py` 是同一份契约的两端。两边漂移的结果不是报错，
> 而是「画布上显示的不是工具实际改的东西」。改一边必须看另一边。

## 路由

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | LandingPage | **公开**落地页，不套 WorkbenchLayout，不要求登录 |
| `/login` | LoginPage | 支持 `state:{next,prompt}` 接力，登录后直达目标页 |
| `/create` | CreatePage | 创作起点：生成 + 上传 + 历史素材一屏 |
| `/candidates/:runId` | CandidatesPage | 候选图，**可刷新、可分享** |
| `/assets` | AssetsPage | 素材库（全量列表 + 删除 + 编辑入口） |
| `/editor` | EditorIndexPage | 会话入口列表 |
| `/editor/:sessionId` | EditorPage | **三栏编辑器外壳**（M5.5）：左对话 / 中画布+候选图条 / 右面板（**按需加载**：konva 约 100KB gzip） |

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
npm run dev      # http://127.0.0.1:7401（已配代理到后端 7402）
npm run build    # 产物 dist/，由后端同源托管
npm run lint
npm run test     # vitest：只跑 src/**/*.test.ts（领域层纯函数）
```

> **为什么只给领域层写测试**：UI 组件的断言价值低且脆，
> 而 `domain/layerDoc.ts` 里那三条约定（数组顺序、默认图层、切换当前图）
> 一旦漂了，表现是「画布显示的不是被改的那个图层」，要很久才能定位到这里。
> `domain/pixels.ts` 同属这一类 —— 但它被单拎出来测试的理由更硬：
> **DoD ③「透明通道的图调色不发黑」**，坏掉之后的表现在 UI 上只是「图糊了」，
> 谁也不会想到是 alpha 通道的事。

### 调色为什么不走 Konva filters

`domain/pixels.ts` 只写 RGB、**从不写第 4 个字节**，透明区域因此永远透明。
等价的做法是用 Konva 自定义 filter，但那条路有两个问题：

1. Konva 的 filter 靠 `this` 绑定读节点属性，属于内部机制，版本一换可能静默失效，
   而失效的表现是「调色突然没效果了」，很难往 filter 上想；
2. 自定义 filter 必须配合 `node.cache()`，cache 时机与图像加载时机一错开就是空白。

离屏 canvas 的路径没这两个问题，而且像素运算本身能在 vitest 里一行断言钉住。
代价是每次参数变化要拷一张 bitmap —— 所以 `adjustedSource()`
在参数全中性时直接返回原图，不做无谓拷贝。

### 安装踩坑（本机必读）

安装必须带 `--ignore-scripts`。原因：

esbuild 的 postinstall 会 `spawnSync node esbuild --version` 做二进制校验，在本机稳定报
`EBUSY`（Windows 文件锁），install 中断后 **optional 依赖 `@esbuild/win32-x64` /
`@rollup/rollup-win32-x64-msvc` 不会被安装**，于是构建时报
`MODULE_NOT_FOUND` 或 "The package @esbuild/win32-x64 could not be found"。

这两个原生包本来就是靠 optionalDependencies 提供的，postinstall 只是校验，跳过即可。
若已经装坏了，正确修法是 **整个 `node_modules` 删掉重装**，不要逐个 `--no-save` 补
（下次 `npm install` 会把它们当成多余包清掉）。

## 编辑器外壳（M5.5）

画布类产品的通行形态：**对话即工作区**。布局是「左对话 / 中画布 / 右面板」，
但有一条自己的分工原则 —— **入口可以多，表单只有一份**：

- 顶栏快捷工具条只做**入口**（按 `/api/tools` 的 group 分组平铺），
  点击后右侧 ToolPanel 显示该工具的参数表单。每个按钮各弹一个表单的话，
  两份表单迟早对不上。
- 变换面板的滑杆**直接绑具体工具名**（`set_opacity` / `rotate_layer` / `reorder_layer`），
  这是「表单不硬编码」规矩的**刻意例外**：用户拖的是「透明度」这个概念，
  不是「某个名字的工具」。概念到工具的映射集中在 TransformPanel 一处。
- 滑杆拖动过程**不发请求**，松手（`onChangeComplete`）才提交 ——
  拖一次 0→100 会触发几十个中间值，每次都落一条历史等于把撤销栈灌满废水。
- **视图状态（缩放 / 选中图层 / 对话内容）不进文档**：放大镜和选中框不该产生
  撤销记录；选中图层被删后回落到「当前图」，否则面板整体失灵。
- 对话记录只存组件状态：Agent 执行记录的持久化是 M8 的事，现在落库只会存出
  一堆没有上下文的单轮记录。画布状态本身是持久的，损失的只是聊天记录。
- 导出 = Konva `stage.toDataURL()`，所见即所得（含调色/裁剪/翻转后的效果）。

## UI 组件库：antd 6

控件一律走 **antd**（`antd@6` + `@ant-design/icons@6`，无需 React 19 兼容补丁）。
理由很实际：原生 `<select>` 的下拉面板是操作系统自绘的，和页面主题完全两个世界，
是界面显得「拼凑」的最大单一来源；手拼 SVG 图标也存在同样问题——线条粗细、
视觉重量凑不成一套。

三条硬规矩：

1. **主题只有一处真源**：`src/index.css` 的 Tailwind token 与 `src/lib/antdTheme.ts`
   的 antd token 必须一一对应。改动时两处同步，否则 antd 组件和手写部分一眼两套系统。
   **字体栈也在这个约束里**：`--font-sans` 与 antd `token.fontFamily` 必须逐字一致，
   且 CJK 字体要显式列出 —— Windows 上 `system-ui` 对中文的回退不可控，
   会落到衬线渲染路径，这是「字体看着很丑」的常见根因。
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
  `ToolPanel` 里没有一个 `if (name === 'xxx')` 分支 —— 参数模型决定了渲染成输入框、
  数字框、下拉还是开关。**新增工具时前端一行都不用改**，这是 M4 的验收项之一。
  `agent_hidden` 的参数在表单上带 🔒 标记：它由界面选择或服务端回填，不是给人填的。
- 素材卡统一用 `components/AssetCard` —— 创作页历史素材、素材库、候选页此前有三份
  figure 各自为政，改一次圆角必然漏两处。
- **「编辑会话的状态只有一个真相源」这一条延伸成了两条硬规矩**：
  - 画布与图层面板都只是投影，不在 store 里再藏一份「真正被编辑的东西」；
  - **任何改动都用服务端返回的 session 覆盖缓存**，不在本地推导下一份文档 ——
    新图层的 id、服务端补的默认值都在那份响应里，本地推导迟早漏点什么。
- **改动一律走工具入口，绝不直接 PUT 文档**：图层面板的「显示/隐藏」「设为当前图」
  也调 `set_layer_visible` / `switch_current_image`。直接改文档的那条路径不写历史，
  用户会发现「有些操作退不回去」。
- 「用素材开会话」统一走 `hooks/useCreateSession.ts`：候选页和素材库各写一遍的结果是
  跳转目标与失败处理各不一样。
- 构建产物按 `react` / `antd` / 业务代码分三块：antd 体积占了一半以上但几乎不变，
  单独成块可以让改一行业务逻辑不必让用户重新下载整个组件库。
