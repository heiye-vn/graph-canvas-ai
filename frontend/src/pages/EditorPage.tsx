/**
 * 编辑工作台（M5.5 起为三栏外壳，M11 起工具条按能力驱动渲染）。
 *
 *   顶栏：标题 / 主工具条 / 撤销重做 / 对比 / 缩放 / 导出 / 图层
 *   左：对话面板        中：画布 + 候选图条        右：图层 / 变换 / 工具 / 属性 / 编辑记录
 *
 * 五条原则在这里落地：
 *   1. **session id 在 URL 上** —— 刷新重建、分享直达都靠它
 *   2. **文档是唯一真相源** —— 画布和所有面板都只是它的投影
 *   3. **所有改动都走工具入口** —— 直接改文档的那条路径不写历史，
 *      用户会发现「有些操作退不回去」
 *   4. **改动一律用服务端返回的 session 覆盖缓存** —— 新图层 id、服务端补的
 *      默认值都在那份响应里，本地推导迟早漏点什么
 *   5. **视图状态（缩放 / 选中 / 裁剪框 / 调色预览）不进文档** ——
 *      它们不该产生撤销记录
 *
 * 画布上的手势（拖动 / 缩放 / 旋转 / 裁剪框）只是**采集意图**：
 * 松手后统一走 `transform_layer` / `crop_layer` 写文档，一次手势一条历史。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Popover,
  Result,
  Skeleton,
  Slider,
  message,
} from "antd";
import { ClearOutlined } from "@ant-design/icons";
import type Konva from "konva";

import {
  clearSelection,
  createSelection,
  getSession,
  getSelection,
} from "@/api/sessions";
import type { SessionOut } from "@/api/sessions";
import { invokeTool, listTools } from "@/api/tools";
import { getHistory, redoStep, undoStep } from "@/api/history";
import AdjustPanel from "@/components/editor/AdjustPanel";
import CandidateStrip from "@/components/editor/CandidateStrip";
import CanvasStage from "@/components/editor/CanvasStage";
import type {
  CropBox,
  SelectionMode,
  TransformPatch,
} from "@/components/editor/CanvasStage";
import ChatPanel from "@/components/editor/ChatPanel";
import EditorToolbar from "@/components/editor/EditorToolbar";
import type { CropRatio, ToolbarAction } from "@/components/editor/EditorToolbar";
import HistoryPanel from "@/components/editor/HistoryPanel";
import LayerPanel from "@/components/editor/LayerPanel";
import ToolPanel from "@/components/editor/ToolPanel";
import TransformPanel from "@/components/editor/TransformPanel";
import { RunProgress } from "@/components/RunProgress";
import { useLoadedImages } from "@/components/editor/useLoadedImages";
import { usePanelWidth } from "@/hooks/usePanelWidth";
import { useRunStream } from "@/hooks/useRunStream";
import type { Adjustments, Layer } from "@/domain/layerDoc";
import {
  referencedAssetIds,
  topmostVisibleImageLayer,
} from "@/domain/layerDoc";

const ZOOM_STEP = 0.1;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;

/** 比例 → 宽高比。null = 自由。 */
const CROP_RATIOS: Record<CropRatio, number | null> = {
  free: null,
  "1:1": 1,
  "4:5": 4 / 5,
  "9:16": 9 / 16,
  "16:9": 16 / 9,
};

/** 排队型（重像素）工具 → 采用后的图层名。 */
const QUEUED_TOOL_LABEL: Record<string, string> = {
  erase_region: "局部消除结果",
  replace_region: "局部替换结果",
};

/**
 * 这些排队工具在 worker 里**自己改文档**并落撤销栈
 * （拆层、去背景、换背景、扩图、超分），完成后前端只需重新拉会话 ——
 * 再走 add_image_layer 会把结果又叠一层。
 */
const DOCUMENT_QUEUED_TOOLS = new Set([
  "split_layers",
  "remove_background",
  "replace_background",
  "expand_canvas",
  "upscale_image",
  "edit_image",
]);

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export default function EditorPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  });
  const tools = useQuery({ queryKey: ["tools"], queryFn: listTools });
  const history = useQuery({
    queryKey: ["history", sessionId],
    queryFn: () => getHistory(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  });

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
  const [panel, setPanel] = useState<"adjust" | "tool" | null>(null);
  const [layersOpen, setLayersOpen] = useState(true);
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
  // 裁剪模式：画布上拉框，确定后才写文档
  const [cropping, setCropping] = useState(false);
  const [cropBox, setCropBox] = useState<CropBox | null>(null);
  const [cropRatio, setCropRatio] = useState<CropRatio>("free");
  // 调色预览：只改画布渲染，应用才落文档
  const [adjustPreview, setAdjustPreview] = useState<Adjustments | null>(null);
  // 拆层选项：勾上后顶栏那一下会带上 include_text
  const [splitIncludeText, setSplitIncludeText] = useState(false);
  // 排队任务浮层：默认展开，可收成一个小胶囊（不挡画面）
  const [runCardOpen, setRunCardOpen] = useState(true);
  // 窄屏兜底：左 304 + 右 304 + 导航 56，窗口再窄画布就被挤没了
  const [narrowScreen, setNarrowScreen] = useState(
    () => typeof window !== "undefined" && window.innerWidth < 1152,
  );
  const [narrowDismissed, setNarrowDismissed] = useState(false);
  useEffect(() => {
    const onResize = () => setNarrowScreen(window.innerWidth < 1152);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // 左右栏拖拽调宽（松手才写 localStorage）
  const { width: leftPanelWidth, onHandlePointerDown: onLeftPanelDrag } =
    usePanelWidth("editor:leftPanelWidth", "left");
  const { width: rightPanelWidth, onHandlePointerDown: onRightPanelDrag } =
    usePanelWidth("editor:rightPanelWidth", "right");
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

  // ---- 撤销 / 重做（顶栏与编辑记录面板共用同一份缓存） ----
  function adoptHistory(result: {
    session: SessionOut;
    can_undo: boolean;
    can_redo: boolean;
    seq: number;
  }) {
    queryClient.setQueryData(["session", sessionId], result.session);
    void queryClient.invalidateQueries({ queryKey: ["history", sessionId] });
    void queryClient.invalidateQueries({ queryKey: ["selection", sessionId] });
  }

  const undo = useMutation({ mutationFn: () => undoStep(sessionId), onSuccess: adoptHistory });
  const redo = useMutation({ mutationFn: () => redoStep(sessionId), onSuccess: adoptHistory });

  /**
   * 撤销/重做快捷键：Ctrl/Cmd+Z、Ctrl/Cmd+Shift+Z、Ctrl+Y ——
   * 顶栏 Tooltip 已经把它们标出去了，这里把承诺兑现。
   *
   * 输入框/文本域/contentEditable 聚焦时豁免：别把用户正在打的字撤了。
   * 裁剪/选区模式下同样生效（它们只动预览框，文档没动，可安全撤销）。
   */
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        if (!history.data?.can_undo || undo.isPending) return;
        event.preventDefault();
        undo.mutate();
      } else if (key === "y" || (key === "z" && event.shiftKey)) {
        if (!history.data?.can_redo || redo.isPending) return;
        event.preventDefault();
        redo.mutate();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data, undo.isPending, redo.isPending]);

  // ---- 排队任务的进度流与自动采用 ----
  const runStream = useRunStream(activeRun?.id ?? null);
  const adoptingRef = useRef(false);

  useEffect(() => {
    if (!activeRun || !runStream.closed || runStream.status !== "succeeded")
      return;

    // worker 已改文档的排队工具：重新拉会话/历史即可，绝不 add_image_layer
    if (DOCUMENT_QUEUED_TOOLS.has(activeRun.tool)) {
      void queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["history", sessionId] });
      void queryClient.invalidateQueries({
        queryKey: ["selection", sessionId],
      });
      message.success(
        activeRun.tool === "split_layers"
          ? "拆层完成，画布已重建为 背景/主体/文字 三层"
          : "处理完成，画布已更新（可撤销）",
      );
      setActiveRun(null);
      return;
    }

    const asset = runStream.candidates[0];
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

  /** 排队任务失败时别让卡片「默默消失」—— 用户会以为图已经改好了。 */
  useEffect(() => {
    if (!activeRun || !runStream.closed) return;
    if (runStream.status === "failed" || runStream.status === "cancelled") {
      message.error(
        runStream.error
          ? `处理失败：${runStream.error}`
          : "处理失败或已取消，画布没有改动",
      );
      setActiveRun(null);
    }
  }, [activeRun, runStream]);

  const queueRun = (runId: string, tool: string) => {
    setActiveRun({ id: runId, tool });
    setRunCardOpen(true);
  };

  /** 进度卡标题：用工具的中文名，别只显示一个百分比 */
  const activeToolLabel = useMemo(
    () =>
      tools.data?.items.find((item) => item.name === activeRun?.tool)?.label ??
      null,
    [tools.data, activeRun?.tool],
  );

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

  const { images, pending, failed } = useLoadedImages(urlMap);

  /**
   * 画布上「有图层但没有像素」的素材集合。
   *
   * 两种都要算：加载失败的，以及**文档引用了、服务端却没下发 URL 的**
   * （数据不一致时 `failed` 是空数组，光看它会让这层继续静默消失）。
   */
  const failedAssetIds = useMemo(() => {
    const ids = new Set(failed);
    if (data) {
      for (const assetId of referencedAssetIds(data.doc)) {
        if (!urlMap[assetId]) ids.add(assetId);
      }
    }
    return [...ids];
  }, [data, failed, urlMap]);

  /**
   * 素材图加载失败时自动换一批预签名重拉一次。
   *
   * 常见触发：会话闲置超过签名有效期、或对象存储瞬时 5xx。旧行为是失败即丢弃，
   * 画布上那层直接消失（拆层后「主体」不见就是这个表现）。以失败集合为 key，
   * 同一批失败只自愈一次，避免「失败 → invalidate → 还是失败」的死循环。
   */
  const healedFailures = useRef<string | null>(null);
  useEffect(() => {
    if (failed.length === 0) return;
    const key = [...failed].sort().join(",");
    if (healedFailures.current === key) return;
    healedFailures.current = key;
    void queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
  }, [failed, queryClient, sessionId]);


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

  /** 画布上的变换框只认「真的点过」的图层，不回落到当前图。 */
  const transformLayerId = useMemo(() => {
    if (!data || !selectedLayerId) return null;
    return data.doc.layers.some((layer) => layer.id === selectedLayerId)
      ? selectedLayerId
      : null;
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
  // 对比的前提是「藏起最上层还能看到别的东西」：可见图像层 < 2 时无从比起
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

  /**
   * 裁剪模式的键盘：Esc 取消、Enter 确定。
   *
   * 依赖里带上 cropBox / data：effect 闭包捕获的是本次渲染的 confirmCrop，
   * 不重建就会拿旧框去裁。
   */
  useEffect(() => {
    if (!cropping) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCropping(false);
        setCropBox(null);
      } else if (event.key === "Enter" && cropBox) {
        event.preventDefault();
        confirmCrop();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cropping, cropBox, data]);

  const availableTools = useMemo(
    () => new Set((tools.data?.items ?? []).map((item) => item.name)),
    [tools.data],
  );

  function invoke(name: string, params: Record<string, unknown>) {
    runTool.mutate({ name, params });
  }

  /** 画布导出：Konva Stage 直接出 PNG（严格按画布设定分辨率 1:1 输出）。 */
  function exportPng() {
    const stage = stageRef.current;
    if (!stage || !data) return;
    // 抵消 Stage 当前为了适应屏幕或用户缩放产生的 scale
    const currentStageScale = stage.scaleX() || 1;
    const pixelRatio = 1 / currentStageScale;

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

  // ---------------------------------------------------------------- 画布手势

  /** 拖动/缩放/旋转松手：一次手势 = 一条历史。 */
  function handleTransform(layerId: string, patch: TransformPatch) {
    invoke("transform_layer", { layer: layerId, ...patch });
  }

  /**
   * 进入裁剪：裁的是**画布**，不是某个图层。
   *
   * 初始框内缩 8%：贴着边缘起框的话，四个手柄里有两个在画布外，
   * 用户第一步就得先猜「能往里拖」。
   */
  function startCrop() {
    if (!data) return;
    const { width: W, height: H } = data.doc.canvas;
    const inset = Math.round(Math.min(W, H) * 0.08);
    setCropBox({
      x: inset,
      y: inset,
      width: Math.max(16, W - inset * 2),
      height: Math.max(16, H - inset * 2),
    });
    setCropRatio("free");
    setCropping(true);
    setSelectionMode("off");
    setPanel(null);
  }

  /** 切比例：以画布中心生成最大的内接矩形（比「保留当前框」更可预期）。 */
  function changeCropRatio(ratio: CropRatio) {
    setCropRatio(ratio);
    if (!data) return;
    const r = CROP_RATIOS[ratio];
    const { width: W, height: H } = data.doc.canvas;
    if (!r) {
      const inset = Math.round(Math.min(W, H) * 0.08);
      setCropBox({
        x: inset,
        y: inset,
        width: Math.max(16, W - inset * 2),
        height: Math.max(16, H - inset * 2),
      });
      return;
    }
    let width = W;
    let height = width / r;
    if (height > H) {
      height = H;
      width = height * r;
    }
    setCropBox({
      x: Math.round((W - width) / 2),
      y: Math.round((H - height) / 2),
      width: Math.round(width),
      height: Math.round(height),
    });
  }

  /**
   * 确定裁剪：画布坐标 → 归一化，交给 crop_canvas。
   *
   * 归一化的原因：后端只关心「裁掉哪一块比例」，它自己乘画布尺寸。
   * 传像素的话，前端 Stage 的缩放、图层是否超出画布都会让这个数失去基准。
   */
  function confirmCrop() {
    if (!data || !cropBox) return;
    const { width: W, height: H } = data.doc.canvas;
    invoke("crop_canvas", {
      x: clamp(cropBox.x / W, 0, 1),
      y: clamp(cropBox.y / H, 0, 1),
      width: clamp(cropBox.width / W, 0.001, 1),
      height: clamp(cropBox.height / H, 0.001, 1),
    });
    setCropping(false);
    setCropBox(null);
  }

  function cancelCrop() {
    setCropping(false);
    setCropBox(null);
  }

  function handleToolbarAction(action: ToolbarAction) {
    const layerId = selectedLayer?.type === "image" ? selectedLayer.id : undefined;
    switch (action) {
      case "crop":
        startCrop();
        break;
      case "flip_h":
        invoke("flip_layer", { layer: layerId, direction: "horizontal" });
        break;
      case "flip_v":
        invoke("flip_layer", { layer: layerId, direction: "vertical" });
        break;
      case "remove_background":
        if (layerId) invoke("remove_background", { layer: layerId });
        break;
      case "replace_background":
        setToolName("replace_background");
        setPanel("tool");
        setLayersOpen(true);
        break;
      case "expand_canvas":
        setToolName("expand_canvas");
        setPanel("tool");
        setLayersOpen(true);
        break;
      case "upscale_image":
        invoke("upscale_image", { scale: 2 });
        break;
      case "adjust_color":
        setAdjustPreview(null);
        setPanel(panel === "adjust" ? null : "adjust");
        setLayersOpen(true);
        setToolName(null);
        break;
      case "split_layers":
        invoke("split_layers", { include_text: splitIncludeText });
        break;
      default:
        break;
    }
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
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-100 text-slate-900">
      <EditorToolbar
        title={data.title || "图像编辑会话"}
        width={doc.canvas.width}
        height={doc.canvas.height}
        available={availableTools}
        busy={runTool.isPending}
        hasLayer={selectedLayer?.type === "image"}
        selectionMode={selectionMode}
        onSelectionMode={(mode) => {
          setSelectionMode(mode);
          if (mode !== "off") {
            setCropping(false);
            setCropBox(null);
          }
        }}
        compare={compare}
        canCompare={canCompare}
        onToggleCompare={() => setCompare((prev) => !prev)}
        zoom={zoom}
        currentScale={currentScale}
        onZoomStep={stepZoom}
        onFit={() => setZoom(null)}
        onExport={exportPng}
        onExportMaterials={() => navigate(`/editor/${sessionId}/export`)}
        onAction={handleToolbarAction}
        canUndo={Boolean(history.data?.can_undo)}
        canRedo={Boolean(history.data?.can_redo)}
        undoBusy={undo.isPending}
        redoBusy={redo.isPending}
        onUndo={() => undo.mutate()}
        onRedo={() => redo.mutate()}
        layersOpen={layersOpen}
        onToggleLayers={() => {
          // 「图层」按钮的语义是「回到图层面板」：面板收着就打开并退出工具面板，
          // 已经停在工具/调色面板上就退回图层，只有本来就停在图层时才收起。
          if (!layersOpen) {
            setLayersOpen(true);
            setPanel(null);
          } else if (panel !== null) {
            setPanel(null);
          } else {
            setLayersOpen(false);
          }
        }}
        cropping={cropping}
        cropRatio={cropRatio}
        onCropRatio={changeCropRatio}
        onConfirmCrop={confirmCrop}
        onCancelCrop={cancelCrop}
      />

      {failedAssetIds.length > 0 && (
        <Alert
          className="m-2 mb-0"
          type="warning"
          showIcon
          message={`有 ${failedAssetIds.length} 张图层图片没取到，画布上显示为橙色占位。这通常是一次请求失败，不是图层丢了。`}
          action={
            <button
              type="button"
              onClick={() => {
                healedFailures.current = null;
                void queryClient.invalidateQueries({
                  queryKey: ["session", sessionId],
                });
              }}
              className="cursor-pointer rounded border border-amber-400 px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50"
            >
              重新加载
            </button>
          }
        />
      )}
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
      {narrowScreen && !narrowDismissed && (
        <Alert
          className="m-2 mb-0"
          type="info"
          showIcon
          closable
          onClose={() => setNarrowDismissed(true)}
          message="当前窗口较窄，画布会被左右面板挤压。建议加宽窗口，或点顶栏「图层」收起右侧面板腾空间。"
        />
      )}

      {/* ---- 三栏核心工作台 ---- */}
      <div className="flex min-h-0 flex-1">
        {/* 左栏：对话与 Agent 计划（可拖右缘分隔条调宽） */}
        <section
          className="relative shrink-0 border-r border-slate-200 bg-white flex flex-col"
          style={{ width: leftPanelWidth }}
        >
          <ChatPanel
            sessionId={sessionId}
            onQueuedRun={queueRun}
            onChanged={onPlanChanged}
          />
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="调整对话面板宽度"
            onPointerDown={onLeftPanelDrag}
            className="absolute inset-y-0 -right-[3px] z-20 w-1.5 cursor-col-resize rounded transition-colors hover:bg-blue-400/50"
          />
        </section>

        {/* 中栏：沉浸式深色画布舞台 + 底部版本胶卷条。
            overflow-hidden 是最后一道闸：任何子元素意外溢出都到此为止，
            绝不让横向滚动条冒到窗口底部。 */}
        <section className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-stage">
          {(selectionMode !== "off" || cropping || selectionData) && (
            <div className="mx-4 mt-2 flex shrink-0 items-center justify-between gap-3 rounded-md border border-blue-500/20 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-300 backdrop-blur-sm">
              <span>
                {cropping
                  ? "✦ 裁剪模式：拖动框或四角调整范围，顶栏「确定」写入文档（画布尺寸不变）。"
                  : selectionMode === "point"
                    ? "✦ 点选模式：在画面上点击选中物体，然后执行消除或替换。"
                    : selectionMode === "brush"
                      ? "✦ 笔刷模式：在画面上涂抹选中区域，然后执行消除或替换。"
                      : "✦ 已有选区：可执行消除或替换。"}
              </span>
              <div className="flex shrink-0 items-center gap-1.5">
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
                            open: false,
                            formatter: (value) =>
                              `${Math.round((value ?? 0) * 1000)}‰`,
                          }}
                        />
                      </div>
                    }
                    trigger="click"
                  >
                    <button
                      type="button"
                      className="cursor-pointer rounded border border-blue-400/40 px-2 py-0.5 text-[11px] text-blue-200 hover:bg-blue-500/20"
                    >
                      粗细
                    </button>
                  </Popover>
                )}
                {selectionData && (
                  <>
                    <button
                      type="button"
                      disabled={runTool.isPending}
                      onClick={() => invoke("erase_region", {})}
                      className="cursor-pointer rounded border border-blue-400/40 px-2 py-0.5 text-[11px] text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
                    >
                      消除
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setToolName("replace_region");
                        setPanel("tool");
                        setLayersOpen(true);
                      }}
                      className="cursor-pointer rounded border border-blue-400/40 px-2 py-0.5 text-[11px] text-blue-200 hover:bg-blue-500/20"
                    >
                      替换
                    </button>
                    <button
                      type="button"
                      disabled={removeSelection.isPending}
                      onClick={() => removeSelection.mutate()}
                      className="flex cursor-pointer items-center gap-1 rounded border border-blue-400/40 px-2 py-0.5 text-[11px] text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
                    >
                      <ClearOutlined className="text-[10px]" />
                      清除选区
                    </button>
                  </>
                )}
              </div>
            </div>
          )}

          {/* 画布中央区域：CanvasStage 自己吃满宽高做 fit（宽高都要算） */}
          <div className="relative min-h-0 flex-1 overflow-hidden p-3">
            {cropping && (
              <div className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2 whitespace-nowrap rounded-md bg-zinc-900/85 px-3 py-1 text-[11px] text-zinc-100 shadow-lg backdrop-blur-sm">
                拖动裁剪框，点「确定」应用 · Esc 取消
              </div>
            )}
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
                failedAssetIds={failedAssetIds}
                selectedLayerId={transformLayerId}
                previewAdjustments={
                  panel === "adjust" && selectedLayer && adjustPreview
                    ? { layerId: selectedLayer.id, adjustments: adjustPreview }
                    : null
                }
                onSelectLayer={(layerId) => setSelectedLayerId(layerId)}
                onTransform={handleTransform}
                cropMode={cropping}
                cropBox={cropBox}
                cropRatio={CROP_RATIOS[cropRatio]}
                onCropBoxChange={setCropBox}
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

            {/* 排队任务进度卡：右下角、可收成胶囊。
                深色卡片里 RunProgress 的浅色文字类要一起翻过来，否则「准备中」几乎看不见。 */}
            {activeRun && !runStream.closed && (
              <div className="absolute bottom-4 right-4 z-30">
                {runCardOpen ? (
                  <div
                    role="status"
                    aria-live="polite"
                    className="w-64 rounded-lg border border-zinc-700/80 bg-zinc-900/95 p-3 shadow-2xl backdrop-blur-md [&_.text-faint]:text-zinc-500 [&_.text-ink]:text-zinc-200 [&_.text-muted]:text-zinc-400"
                  >
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className="text-[11px] font-medium text-zinc-300">
                        {activeToolLabel ? `${activeToolLabel}处理中` : "AI 处理中"}
                      </span>
                      <button
                        type="button"
                        onClick={() => setRunCardOpen(false)}
                        className="cursor-pointer text-[11px] text-zinc-500 transition-colors hover:text-zinc-300"
                      >
                        收起
                      </button>
                    </div>
                    <RunProgress
                      status={runStream.status}
                      progress={runStream.progress}
                      stage={runStream.stage}
                    />
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setRunCardOpen(true)}
                    className="flex cursor-pointer items-center gap-2 rounded-full border border-zinc-700/80 bg-zinc-900/95 px-3 py-1.5 text-[11px] text-zinc-300 shadow-lg backdrop-blur-md transition-colors hover:text-white"
                  >
                    <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
                    {activeToolLabel ?? "AI 处理中"} ·{" "}
                    {Math.round(runStream.progress)}%
                  </button>
                )}
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

          {/* 右栏收起后，画布右缘留一个竖向把手 —— 比顶栏那颗「图层」按钮好找 */}
          {!layersOpen && (
            <button
              type="button"
              onClick={() => setLayersOpen(true)}
              title="展开图层面板"
              className="absolute right-0 top-1/2 z-30 -translate-y-1/2 cursor-pointer rounded-l-md border border-r-0 border-slate-200 bg-white py-3 pl-1.5 pr-1 text-[11px] text-slate-500 shadow-md transition-colors hover:text-slate-900 [writing-mode:vertical-rl]"
            >
              图层
            </button>
          )}
        </section>

        {/* 右栏：检查器面板（图层 / 变换 / 工具 / 属性 / 编辑记录，可拖左缘分隔条调宽） */}
        {layersOpen && (
          <aside
            className="relative shrink-0 border-l border-slate-200 bg-white space-y-4 overflow-y-auto p-3.5"
            style={{ width: rightPanelWidth }}
          >
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="调整检查器面板宽度"
              onPointerDown={onRightPanelDrag}
              className="absolute inset-y-0 -left-[3px] z-20 w-1.5 cursor-col-resize rounded transition-colors hover:bg-blue-400/50"
            />
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold tracking-wide text-slate-400">
                检查器
              </span>
              <button
                type="button"
                onClick={() => setLayersOpen(false)}
                title="收起面板（右侧留出画布空间）"
                aria-label="收起面板"
                className="h-6 w-6 cursor-pointer rounded text-sm leading-none text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                »
              </button>
            </div>
            {panel === "adjust" && selectedLayer && selectedLayer.type === "image" ? (
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="m-0 text-xs font-semibold text-slate-800">
                    调色 · {selectedLayer.name}
                  </h2>
                  <button
                    type="button"
                    onClick={() => {
                      setPanel(null);
                      setAdjustPreview(null);
                    }}
                    className="cursor-pointer text-[11px] text-slate-400 hover:text-slate-700"
                  >
                    收起
                  </button>
                </div>
                <AdjustPanel
                  key={selectedLayer.id}
                  layer={selectedLayer}
                  onPreview={setAdjustPreview}
                  applying={runTool.isPending}
                  onApply={(adjustments) => {
                    invoke("adjust_color", {
                      layer: selectedLayer.id,
                      ...adjustments,
                    });
                    setAdjustPreview(null);
                  }}
                />
              </section>
            ) : (
              <>
                <section>
                  <h2 className="mb-2 text-[11px] font-semibold tracking-wider text-slate-400">
                    图层
                  </h2>
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
                      setPanel("tool");
                    }}
                    splitIncludeText={splitIncludeText}
                    onSplitIncludeTextChange={setSplitIncludeText}
                  />
                </section>

                <section>
                  <h2 className="mb-2 text-[11px] font-semibold tracking-wider text-slate-400">
                    变换
                  </h2>
                  <TransformPanel doc={doc} layer={selectedLayer} onInvoke={invoke} />
                </section>

                <section>
                  <h2 className="mb-2 text-[11px] font-semibold tracking-wider text-slate-400">
                    工具
                  </h2>
                  <ToolPanel
                    sessionId={sessionId}
                    selected={panel === "tool" ? toolName : null}
                    onSelect={(name) => {
                      setToolName(name || null);
                      setPanel(name ? "tool" : null);
                    }}
                    onQueuedRun={queueRun}
                  />
                </section>
              </>
            )}

            <section className="pt-1 border-t border-slate-100">
              <h2 className="mb-2 text-[11px] font-semibold tracking-wider text-slate-400">
                属性
              </h2>
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
        )}
      </div>
    </div>
  );
}
