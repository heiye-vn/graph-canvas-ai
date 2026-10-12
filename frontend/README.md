# 前端（React 19 + Vite）

## 目录

```
src/
├── api/         REST 与 SSE 客户端；工具元数据统一从 /api/tools 拉取（M4）
├── domain/      ★ 画布领域层：layerDoc / transform / selection / history
│                  刻意先于组件编写——参考项目的 CanvasStage 长到 1087 行就是没抽这层
├── stores/      Zustand：canvasView / editorUi / agentRun / toasts
├── components/  canvas / agent / layers 三组
└── pages/       Landing / Create / Editor / Batch / Marketing
```

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

## 约定

- 业务接口走 `/api`，探针与 SSE 走根路径（`/ready`、`/events`），已在 `vite.config.ts` 配好代理。
- 工具标签与参数表单**全部由后端 `/api/tools` 下发**，前端不硬编码任何工具名清单。
