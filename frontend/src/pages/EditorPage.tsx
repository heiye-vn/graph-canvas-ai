/**
 * 编辑工作台（M5.5 起为三栏外壳）。
 *
 *   顶栏：标题 / 快捷工具条 / 缩放 / 导出
 *   左：对话面板        中：画布 + 候选图条        右：图层 / 变换 / 工具 / 属性 / 编辑记录
 *
 * 五条原则在这里落地：
 *   1. **session id 在 URL 上** —— 刷新重建、分享直达都靠它
 *   2. **文档是唯一真相源** —— 画布和所有面板都只是它的投影
 *   3. **所有改动都走工具入口** —— 直接改文档的那条路径不写历史，
 *      用户会发现「有些操作退不回去」
 *   4. **改动一律用服务端返回的 session 覆盖缓存** —— 新图层 id、服务端补的
 *      默认值都在那份响应里，本地推导迟早漏点什么
 *   5. **视图状态（缩放 / 选中图层）不进文档** —— 放大镜和选中框不该产生撤销记录
 *
 * M6 加入选区：模式（点选/笔刷）、笔刷半径、当前 run 都是**视图状态**，
 * 与缩放同级 —— 选区 overlay 不进文档，改图后随 revision 自动失效。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Popover,
  Result,
  Segmented,
  Skeleton,
  Slider,
  Tooltip,
} from "antd";
import {
  ClearOutlined,
  ColumnWidthOutlined,
  ExportOutlined,
  MinusOutlined,
  PlusOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { message } from "antd";
import type Konva from "konva";

import {
  clearSelection,
  createSelection,
  getSession,
  getSelection,
} from "@/api/sessions";
import type { SessionOut } from "@/api/sessions";
import { invokeTool, listTools } from "@/api/tools";
import CandidateStrip from "@/components/editor/CandidateStrip";
import CanvasStage from "@/components/editor/CanvasStage";
import type { SelectionMode } from "@/components/editor/CanvasStage";
import ChatPanel from "@/components/editor/ChatPanel";
import HistoryPanel from "@/components/editor/HistoryPanel";
import LayerPanel from "@/components/editor/LayerPanel";
import QuickToolbar from "@/components/editor/QuickToolbar";
import ToolPanel from "@/components/editor/ToolPanel";
import TransformPanel from "@/components/editor/TransformPanel";
import { RunProgress } from "@/components/RunProgress";
import { useLoadedImages } from "@/components/editor/useLoadedImages";
import { useRunStream } from "@/hooks/useRunStream";
import type { Layer } from "@/domain/layerDoc";
import {
  referencedAssetIds,
  topmostVisibleImageLayer,
} from "@/domain/layerDoc";

const ZOOM_STEP = 0.1;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;

/** 排队型（重像素）工具 → 采用后的图层名。 */
const QUEUED_TOOL_LABEL: Record<string, string> = {
  erase_region: "局部消除结果",
  replace_region: "局部替换结果",
};

export default function EditorPage() {
  const { sessionId = "" } = useParams();
  const queryClient = useQueryClient();

  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  });
  const tools = useQuery({ queryKey: ["tools"], queryFn: listTools });

  /**
   * 面板上任何改动都从这里走。
   *
   * 成功后用服务端返回的 session 覆盖缓存（而不是本地算一份）：
   * 图层的新 id、服务端补的默认值都在那份响应里，本地推导迟早漏点什么。
   */
  const runTool = useMutation({
    mutationFn: ({
      name,
      params,
    }: {
      name: string;
      params: Record<string, unknown>;
    }) => invokeTool(name, sessionId, params),
    onSuccess: (result) => {
      queryClient.setQueryData(["session", sessionId], result.session);
      void queryClient.invalidateQueries({ queryKey: ["history", sessionId] });
      // 排队型工具：立即切到进度流，生成完自动采用
      if (result.run_id) setActiveRun({ id: result.run_id, tool: result.tool });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    },
  });

  // ---- 视图状态（刻意不进文档：它们不产生撤销记录） ----
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null);
  const [toolName, setToolName] = useState<string | null>(null);
  const [zoom, setZoom] = useState<number | null>(null); // null = 适应容器
  const [currentScale, setCurrentScale] = useState(0);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("off");
  const [brushRadius, setBrushRadius] = useState(0.03);
  const [activeRun, setActiveRun] = useState<{
    id: string;
    tool: string;
  } | null>(null);
  // 对比模式：临时隐藏最上层的图像层，看编辑前的样子（视图状态，不进文档）
  const [compare, setCompare] = useState(false);
  const stageRef = useRef<Konva.Stage | null>(null);

  const data = session.data as SessionOut | undefined;
  const revision = data?.revision ?? null;

  /**
   * 当前选区。queryKey 带 revision：文档一变（工具/撤销/重做）整个查询
   * 自动失效重取，过期选区后端返回 null，overlay 无感消失 ——
   * 「改图后旧选区自动失效」（DoD ③）在前端的表现就是这个键。
   */
  const selection = useQuery({
    queryKey: ["selection", sessionId, revision],
    queryFn: () => getSelection(sessionId),
    enabled: Boolean(sessionId) && revision !== null,
  });

  const updateSelection = useMutation({
    mutationFn: (payload: Parameters<typeof createSelection>[1]) =>
      createSelection(sessionId, payload),
    onSuccess: (result) => {
      queryClient.setQueryData(["selection", sessionId, revision], result);
    },
    onError: () => {
      // 409 = 画布已变：丢本地状态，让用户重新选
      void queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      void queryClient.invalidateQueries({
        queryKey: ["selection", sessionId],
      });
    },
  });

  const removeSelection = useMutation({
    mutationFn: () => clearSelection(sessionId),
    onSuccess: () => {
      queryClient.setQueryData(["selection", sessionId, revision], null);
    },
  });

  // ---- 排队任务的进度流与自动采用 ----
  const runStream = useRunStream(activeRun?.id ?? null);
  const adoptingRef = useRef(false);

  useEffect(() => {
    if (!activeRun || !runStream.closed || runStream.status !== "succeeded")
      return;
    const asset = runStream.candidates[0];

    // 拆层：worker 已整份替换文档并落撤销栈 —— 前端只需重新拉会话，
    // 绝不能走 add_image_layer（会把主体再叠一层出来）
    if (activeRun.tool === "split_layers") {
      void queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["history", sessionId] });
      void queryClient.invalidateQueries({
        queryKey: ["selection", sessionId],
      });
      message.success("拆层完成，画布已重建为 背景/主体/文字 三层");
      setActiveRun(null);
      return;
    }

    if (!asset) {
      setActiveRun(null);
      return;
    }
    // 结果只上墙 → 自动采用为新图层（与候选页同一入口 add_image_layer）
    if (!adoptingRef.current) {
      adoptingRef.current = true;
      runTool.mutate(
        {
          name: "add_image_layer",
          params: {
            asset_id: asset.assetId,
            name: QUEUED_TOOL_LABEL[activeRun.tool] ?? "编辑结果",
          },
        },
        {
          onSuccess: () =>
            message.success(
              "局部编辑完成，已加入画布。顶栏「对比」可查看编辑前的样子",
            ),
          onSettled: () => {
            adoptingRef.current = false;
            setActiveRun(null);
          },
        },
      );
    }
  }, [activeRun, runStream, runTool, queryClient, sessionId]);

  const queueRun = (runId: string, tool: string) =>
    setActiveRun({ id: runId, tool });

  /** 计划卡片里任何步骤落地后：文档/历史/选区都可能变了 */
  const onPlanChanged = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    void queryClient.invalidateQueries({ queryKey: ["history", sessionId] });
    void queryClient.invalidateQueries({ queryKey: ["selection", sessionId] });
  }, [queryClient, sessionId]);

  // asset_id -> 预签名地址。必须 useMemo：useLoadedImages 靠引用变化去重
  const urlMap = useMemo(() => {
    if (!data) return {};
    const wanted = referencedAssetIds(data.doc);
    const map: Record<string, string> = {};
    for (const asset of data.assets) {
      if (wanted.includes(asset.id)) map[asset.id] = asset.url;
    }
    return map;
  }, [data]);

  const { images, pending } = useLoadedImages(urlMap);

  /**
   * 变换面板的作用对象。
   *
   * 用户没点过图层时默认跟「当前图」走（与工具的默认目标一致）；
   * 选中的图层被删掉后回落到当前图 —— 选中一个不存在的图层只会让面板全部失灵。
   */
  const selectedLayer: Layer | null = useMemo(() => {
    if (!data) return null;
    if (selectedLayerId) {
      const found = data.doc.layers.find(
        (layer) => layer.id === selectedLayerId,
      );
      if (found) return found;
    }
    return topmostVisibleImageLayer(data.doc) ?? null;
  }, [data, selectedLayerId]);

  /**
   * 对比模式的作用对象：最上层的可见图像层（通常是最近一次编辑的结果）。
   * ⚠️ 必须留在早退 return 之前的 hooks 区 —— hook 顺序在两次渲染之间
   * 不允许变化（React 会直接抛 Fatal Error）。
   */
  const topImageLayerId = useMemo(() => {
    const layers = data?.doc.layers;
    if (!layers) return null;
    for (let i = layers.length - 1; i >= 0; i--) {
      const layer = layers[i];
      if (layer.visible && layer.type === "image") return layer.id;
    }
    return null;
  }, [data]);
  // 对比的前提是「藏起最上层还能看到别的东西」：可见图像层 < 2 时无从比起，
  // 硬按只会把画布掏成白底（文字层目前不上画布，M7 重构后另说）
  const visibleImageLayerCount = useMemo(
    () =>
      (data?.doc.layers ?? []).filter((l) => l.visible && l.type === "image")
        .length,
    [data],
  );
  const canCompare = visibleImageLayerCount >= 2;
  useEffect(() => {
    if (compare && !canCompare) setCompare(false);
  }, [compare, canCompare]);
  const hiddenLayerIds = compare && topImageLayerId ? [topImageLayerId] : null;

  function invoke(name: string, params: Record<string, unknown>) {
    runTool.mutate({ name, params });
  }

  /** 画布导出：Konva Stage 直接出 PNG（严格按画布设定分辨率 1:1 输出）。 */
  function exportPng() {
    const stage = stageRef.current;
    if (!stage || !data) return;
    // 抵消 Stage 当前为了适应屏幕或用户缩放产生的 scale，确保导出尺寸精确等于画布基准尺寸（如 1024x1024）
    const currentScale = stage.scaleX() || 1;
    const pixelRatio = 1 / currentScale;

    const link = document.createElement("a");
    link.href = stage.toDataURL({ pixelRatio, mimeType: "image/png" });
    link.download = `${data.title || "画布"}.png`;
    link.click();
  }

  function stepZoom(direction: 1 | -1) {
    const base = zoom ?? currentScale;
    if (!base) return;
    setZoom(
      Math.min(
        ZOOM_MAX,
        Math.max(
          ZOOM_MIN,
          Math.round((base + direction * ZOOM_STEP) * 100) / 100,
        ),
      ),
    );
  }

  if (session.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-8 py-10">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }

  if (session.isError || !data) {
    return (
      <Result
        status="404"
        title="找不到这个编辑会话"
        subTitle="它可能已被删除，或者不属于当前账号。"
        extra={
          <Link to="/assets">
            <Button type="primary">去素材库</Button>
          </Link>
        }
      />
    );
  }

  const doc = data.doc;
  const selectionData = selection.data ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-100 text-slate-900 select-none">
      {/* ---- 顶栏（对齐参考图1：精巧紧凑，信息主次分明） ---- */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-3.5 z-20">
        {/* 左侧：任务标题 + 分辨率徽标 */}
        <div className="flex items-center gap-2 min-w-0 max-w-65 shrink-0">
          <span
            className="truncate text-xs font-semibold text-slate-800"
            title={data.title}
          >
            {data.title || "图像编辑会话"}
          </span>
          <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
            {doc.canvas.width}×{doc.canvas.height}
          </span>
        </div>

        {/* 中间：高频快捷工具条 */}
        <div className="min-w-0 flex-1 px-3">
          <QuickToolbar
            tools={tools.data?.items ?? []}
            selected={toolName}
            onSelect={setToolName}
          />
        </div>

        {/* 右侧：操控组件群（选区模式、对比、缩放、导出） */}
        <div className="flex shrink-0 items-center gap-1.5">
          {/* 选区模式微调 */}
          <Segmented
            size="small"
            value={selectionMode}
            onChange={(value) => setSelectionMode(value as SelectionMode)}
            options={[
              { label: "选区·关", value: "off" },
              { label: "点选", value: "point" },
              { label: "笔刷", value: "brush" },
            ]}
            className="text-xs"
          />

          {selectionMode === "brush" && (
            <Popover
              placement="bottomRight"
              content={
                <div className="w-44 px-1 pt-1">
                  <p className="m-0 mb-2 text-xs text-slate-500">笔刷粗细</p>
                  <Slider
                    min={0.005}
                    max={0.12}
                    step={0.005}
                    value={brushRadius}
                    onChange={setBrushRadius}
                    tooltip={{
                      formatter: (v) => `${Math.round((v ?? 0) * 1000)}‰`,
                    }}
                  />
                </div>
              }
              trigger="click"
            >
              <button
                type="button"
                className="px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 rounded border border-slate-200 cursor-pointer"
              >
                粗细
              </button>
            </Popover>
          )}

          {selectionData && (
            <Tooltip title="清除当前选区">
              <Button
                size="small"
                type="text"
                icon={<ClearOutlined className="text-xs" />}
                loading={removeSelection.isPending}
                onClick={() => removeSelection.mutate()}
                className="h-7! w-7!"
                aria-label="清除选区"
              />
            </Tooltip>
          )}

          <div className="h-4 w-px bg-slate-200 mx-0.5" />

          {/* 对比按钮 */}
          <Tooltip
            title={
              canCompare
                ? "对比编辑前后效果（长按或点击）"
                : "需两层以上可见图像才能对比"
            }
          >
            <button
              type="button"
              disabled={!canCompare}
              onClick={() => setCompare((prev) => !prev)}
              className={`flex h-7 items-center gap-1.5 px-2.5 text-xs font-medium rounded-md transition-all cursor-pointer ${
                compare
                  ? "bg-blue-600 text-white shadow-2xs"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-40"
              }`}
            >
              <SwapOutlined className="text-[11px]" />
              <span>对比</span>
            </button>
          </Tooltip>

          {/* 缩放控制器群（一体化高质感控件，统一定高 h-7 像素级对齐） */}
          <div className="flex h-7 items-center rounded-md border border-slate-200 bg-slate-50/80 px-1 shadow-2xs">
            <Tooltip title="缩小 (10%)">
              <button
                type="button"
                onClick={() => stepZoom(-1)}
                className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-white hover:text-slate-800 transition-colors cursor-pointer"
                aria-label="缩小"
              >
                <MinusOutlined className="text-[10px]" />
              </button>
            </Tooltip>
            <span className="w-11 text-center font-mono text-[11px] font-medium tabular-nums text-slate-600 select-none">
              {zoom === null ? "适应" : `${Math.round(zoom * 100)}%`}
            </span>
            <Tooltip title="放大 (10%)">
              <button
                type="button"
                onClick={() => stepZoom(1)}
                className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-white hover:text-slate-800 transition-colors cursor-pointer"
                aria-label="放大"
              >
                <PlusOutlined className="text-[10px]" />
              </button>
            </Tooltip>
            <div className="h-3 w-px bg-slate-200 mx-0.5" />
            <Tooltip title="适应窗口">
              <button
                type="button"
                disabled={zoom === null}
                onClick={() => setZoom(null)}
                className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-white hover:text-slate-800 disabled:opacity-30 disabled:hover:bg-transparent transition-colors cursor-pointer"
                aria-label="适应窗口"
              >
                <ColumnWidthOutlined className="text-[11px]" />
              </button>
            </Tooltip>
          </div>

          {/* 导出按钮 */}
          <Button
            size="small"
            type="primary"
            icon={<ExportOutlined className="text-xs" />}
            onClick={exportPng}
            className="h-7! px-3! text-xs! font-medium rounded-md shadow-2xs"
          >
            导出
          </Button>
        </div>
      </header>

      {runTool.isError && (
        <Alert
          className="m-2 mb-0"
          type="error"
          showIcon
          closable
          message="这次改动没能保存到服务端，画布已回滚到上一次成功的状态。"
        />
      )}
      {updateSelection.isError && (
        <Alert
          className="m-2 mb-0"
          type="warning"
          showIcon
          closable
          message="选区没能保存（画布可能刚变过），请重新点选或涂抹。"
        />
      )}

      {/* ---- 三栏核心工作台 ---- */}
      <div className="flex min-h-0 flex-1">
        {/* 左栏：对话与 Agent 计划 */}
        <section className="w-76 shrink-0 border-r border-slate-200 bg-white flex flex-col">
          <ChatPanel
            sessionId={sessionId}
            onQueuedRun={queueRun}
            onChanged={onPlanChanged}
          />
        </section>

        {/* 中栏：沉浸式深色画布舞台 + 底部版本胶卷条 */}
        <section className="flex min-w-0 flex-1 flex-col bg-stage">
          {selectionMode !== "off" && (
            <div className="mx-4 mt-2 shrink-0 rounded-md bg-blue-500/10 border border-blue-500/20 px-3 py-1.5 text-xs text-blue-300 backdrop-blur-sm">
              {selectionMode === "point"
                ? "✦ 点选模式：在画面上点击选中物体，然后到右侧执行消除或替换。"
                : "✦ 笔刷模式：在画面上涂抹选中区域，然后到右侧执行局部编辑。"}
            </div>
          )}

          {/* 画布中央区域（暗色底板 + 立体阴影装裱） */}
          <div className="relative min-h-0 flex-1 overflow-auto p-6 flex items-center justify-center">
            <div className="w-full flex items-center justify-center">
              <CanvasStage
                doc={doc}
                images={images}
                loading={pending}
                zoom={zoom}
                stageRef={stageRef}
                onScaleChange={setCurrentScale}
                selectionMode={selectionMode}
                brushRadius={brushRadius}
                maskUrl={selectionData?.mask.url ?? null}
                markers={selectionData?.markers ?? []}
                selectionBusy={updateSelection.isPending}
                hiddenLayerIds={hiddenLayerIds}
                onPointClick={(point) =>
                  updateSelection.mutate({
                    revision: data.revision,
                    points: [point],
                    append: true,
                  })
                }
                onStrokeEnd={(points) =>
                  updateSelection.mutate({
                    revision: data.revision,
                    strokes: [points],
                    radius: brushRadius,
                    append: true,
                  })
                }
              />
            </div>

            {/* 排队任务悬浮卡片 */}
            {activeRun && !runStream.closed && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-30">
                <div className="rounded-lg bg-zinc-900/90 border border-zinc-700/80 p-3.5 shadow-2xl backdrop-blur-md min-w-70">
                  <RunProgress
                    status={runStream.status}
                    progress={runStream.progress}
                    stage={runStream.stage}
                  />
                </div>
              </div>
            )}
          </div>

          {/* 底部历史/候选图胶卷条（常驻锚点） */}
          <CandidateStrip
            doc={doc}
            urls={urlMap}
            busy={runTool.isPending}
            onSwitch={(layerId) =>
              invoke("switch_current_image", { layer: layerId })
            }
          />
        </section>

        {/* 右栏：检查器面板（图层 / 变换 / 工具 / 属性 / 编辑记录） */}
        <aside className="w-76 shrink-0 border-l border-slate-200 bg-white space-y-4 overflow-y-auto p-3.5">
          <section>
            <h2 className="mb-2 text-xs font-semibold text-slate-800">图层</h2>
            <LayerPanel
              doc={doc}
              selectedId={selectedLayer?.id ?? null}
              onSelect={setSelectedLayerId}
              busy={runTool.isPending}
              onToggleVisible={(layerId, visible) =>
                invoke("set_layer_visible", { layer: layerId, visible })
              }
              onSwitchCurrent={(layerId) =>
                invoke("switch_current_image", { layer: layerId })
              }
              onEditText={(layerId) => {
                setSelectedLayerId(layerId);
                setToolName("set_layer_text");
              }}
            />
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold text-slate-800">变换</h2>
            <TransformPanel doc={doc} layer={selectedLayer} onInvoke={invoke} />
          </section>

          <section>
            <ToolPanel
              sessionId={sessionId}
              selected={toolName}
              onSelect={setToolName}
              onQueuedRun={queueRun}
            />
          </section>

          <section className="pt-1 border-t border-slate-100">
            <h2 className="mb-2 text-xs font-semibold text-slate-800">属性</h2>
            <dl className="m-0 space-y-1 text-xs">
              {[
                ["画布尺寸", `${doc.canvas.width} × ${doc.canvas.height}`],
                ["修订号", String(data.revision ?? 1)],
                ["导出格式", "PNG (1:1 原画)"],
                ["图层总数", `${doc.layers.length} 层`],
                ["选区状态", selectionData ? "已激活" : "无"],
              ].map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-center justify-between py-0.5"
                >
                  <dt className="text-slate-400 text-[11px]">{key}</dt>
                  <dd className="m-0 font-mono text-[11px] text-slate-700 tabular-nums font-medium">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="pt-1 border-t border-slate-100">
            <HistoryPanel sessionId={sessionId} />
          </section>
        </aside>
      </div>
    </div>
  );
}
