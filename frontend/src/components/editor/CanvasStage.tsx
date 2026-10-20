/**
 * Konva 画布。
 *
 * 这个组件做的唯一一件事：**按图层文档渲染**。它不做任何编辑操作，
 * 也不持有文档之外的状态 —— 文档是唯一真相源，画布只是它的一个投影。
 * 好处是「画布上显示的」和「工具实际改的」永远是一份东西。
 *
 * 缩放只有一个 scale：Stage 尺寸 = 画布尺寸 × scale，坐标仍是文档里的画布像素。
 * 这样以后加节点变换/选区时不用做「屏幕坐标 ⇄ 文档坐标」的第二套换算。
 *
 * M5 起这里把文档里此前**只读不画**的字段补上了：`adjustments`（调色）、
 * `crop`（裁剪）、`transform.flip_x/flip_y`（翻转）。工具能改但画布不渲染，
 * 等于功能做了一半 —— 用户只会认为那个工具坏了。
 *
 * M6 起增加选区交互：点选（每次点击 = 一个提示点）与笔刷（按住拖动涂抹）。
 *
 * M11 起画布内直接操作图层：
 *   - 点图层选中，四角/四边手柄缩放，顶部手柄旋转，按住拖动移动
 *   - **旋转绕图层中心**：节点的 x/y 记为几何中心、offset 记为半宽高。
 *     旧版直接给左上角加 rotation，图会绕左上角甩出画布 ——
 *     用户看到的就是「转一下整张图错乱了」。
 *   - 画布可视范围恒定：Stage 永远是 canvas.width × canvas.height，
 *     旋转/缩放超出画布的部分自然被裁掉，绝不反过来改画布尺寸。
 *   - 裁剪框在画布上拉，画布尺寸同样不变（裁的是图层，不是视口）。
 */

import { memo, useEffect, useMemo, useRef, useState } from "react";
import type Konva from "konva";
import type { MutableRefObject } from "react";
import {
  Circle,
  Group,
  Image as KonvaImage,
  Layer as KonvaLayer,
  Line,
  Rect,
  Stage,
  Text as KonvaText,
  Transformer,
} from "react-konva";

import type {
  Adjustments,
  LayerCanvas,
  LayerDocument,
  Layer as LayerModel,
} from "@/domain/layerDoc";
import type { SelectionMarker } from "@/api/sessions";
import { layerRect, layerSourceAssetId } from "@/domain/layerDoc";
import { adjustedSource } from "./adjustedSource";
import type { ImageMap } from "./useLoadedImages";

export type SelectionMode = "off" | "point" | "brush";

interface NormalizedPoint {
  x: number;
  y: number;
}

/** 画布内变换提交的补丁：全部是文档字段（左上角坐标、尺寸、角度）。 */
export interface TransformPatch {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  rotation?: number;
}

export interface CropBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 归一化到 (-180, 180]，避免转三圈后文档里出现 1080°。 */
function normalizeAngle(degrees: number): number {
  const wrapped = (((degrees + 180) % 360) + 360) % 360 - 180;
  return wrapped === -180 ? 180 : Math.round(wrapped * 10) / 10;
}

/**
 * 单个图层。
 *
 * 抽成组件而不是内联 map 出去：每个图层需要自己的 useMemo（按自己的
 * adjustments 缓存离屏 canvas），Hook 不能写在循环里。
 *
 * 几何一律用**中心锚点**：x/y 是中心，offset 是半宽高。
 * 这是「旋转不跑位」的唯一实现点 —— 详见文件头注释。
 */
const LayerNode = memo(function LayerNode({
  layer,
  canvas,
  image,
  interactive,
  preview,
  onSelect,
  onCommit,
}: {
  layer: LayerModel;
  canvas: LayerCanvas;
  image: HTMLImageElement;
  interactive: boolean;
  preview?: Adjustments | null;
  onSelect?: (layerId: string) => void;
  onCommit?: (layerId: string, patch: TransformPatch) => void;
}) {
  const rect = layerRect(layer, canvas);

  // 依赖写具体的字段而不是整层的对象引用：文档每次保存都是新对象，
  // 用对象做依赖会让所有图层在任意一次改动后全部重算
  const adjustments = preview ?? layer.adjustments;
  const source = useMemo(
    () => adjustedSource(image, adjustments),
    [image, adjustments],
  );

  const crop = layer.crop;
  const halfWidth = rect.width / 2;
  const halfHeight = rect.height / 2;
  const baseScaleX = layer.transform.flip_x ? -1 : 1;
  const baseScaleY = layer.transform.flip_y ? -1 : 1;

  return (
    <KonvaImage
      id={`layer-${layer.id}`}
      image={source as Konva.ImageConfig["image"]}
      x={rect.x + halfWidth}
      y={rect.y + halfHeight}
      offsetX={halfWidth}
      offsetY={halfHeight}
      width={rect.width}
      height={rect.height}
      rotation={rect.rotation}
      scaleX={baseScaleX}
      scaleY={baseScaleY}
      opacity={layer.opacity}
      crop={
        crop
          ? { x: crop.x, y: crop.y, width: crop.width, height: crop.height }
          : undefined
      }
      listening={interactive}
      draggable={interactive}
      onMouseEnter={(event) => {
        // 悬停在图层上 → 抓手，暗示「可以拖着走」
        if (!interactive) return
        const container = event.target.getStage()?.container()
        if (container) container.style.cursor = "grab"
      }}
      onMouseLeave={(event) => {
        const container = event.target.getStage()?.container()
        if (container) container.style.cursor = "default"
      }}
      onDragStart={(event) => {
        const container = event.target.getStage()?.container()
        if (container) container.style.cursor = "grabbing"
        onSelect?.(layer.id)
      }}
      onMouseDown={() => onSelect?.(layer.id)}
      onTap={() => onSelect?.(layer.id)}
      onDragEnd={(event) => {
        const node = event.target as Konva.Image;
        const container = node.getStage()?.container();
        if (container) container.style.cursor = "grab";
        onCommit?.(layer.id, {
          x: Math.round(node.x() - halfWidth),
          y: Math.round(node.y() - halfHeight),
        });
      }}
      onTransformEnd={(event) => {
        const node = event.target as Konva.Image;
        // Transformer 只改 scale，不改 width；把 scale 折算回文档尺寸，
        // 然后本地立刻复位 —— 否则下一帧会「旧尺寸 × 新倍率」二次放大
        const nextWidth = Math.max(
          16,
          Math.round(rect.width * Math.abs(node.scaleX())),
        );
        const nextHeight = Math.max(
          16,
          Math.round(rect.height * Math.abs(node.scaleY())),
        );

        node.width(nextWidth);
        node.height(nextHeight);
        node.offsetX(nextWidth / 2);
        node.offsetY(nextHeight / 2);
        node.scaleX(baseScaleX);
        node.scaleY(baseScaleY);

        onCommit?.(layer.id, {
          x: Math.round(node.x() - nextWidth / 2),
          y: Math.round(node.y() - nextHeight / 2),
          width: nextWidth,
          height: nextHeight,
          rotation: normalizeAngle(node.rotation()),
        });
      }}
    />
  );
});

/**
 * 素材图没加载出来时的占位。
 *
 * 拆层后的「主体」是一张独立素材，它加载失败时整层会**凭空消失** ——
 * 用户只会看到背景，进而怀疑拆层把物体弄丢了。这里画一块明确的告示，
 * 把「图没下载下来」和「拆层丢了东西」区分开。
 */
const MissingLayer = memo(function MissingLayer({
  layer,
  canvas,
}: {
  layer: LayerModel;
  canvas: LayerCanvas;
}) {
  const rect = layerRect(layer, canvas);
  const edge = Math.min(canvas.width, canvas.height);
  return (
    <Group listening={false}>
      <Rect
        x={rect.x}
        y={rect.y}
        width={rect.width}
        height={rect.height}
        fill="rgba(245, 158, 11, 0.10)"
        stroke="#f59e0b"
        strokeWidth={Math.max(2, edge * 0.003)}
        dash={[edge * 0.02, edge * 0.014]}
      />
      <KonvaText
        x={rect.x + rect.width * 0.035}
        y={rect.y + rect.height * 0.035}
        text={`「${layer.name}」的图片没加载出来`}
        fontSize={Math.max(20, edge * 0.028)}
        fill="#f59e0b"
      />
    </Group>
  );
});

/** 遮罩 overlay 图：后端下发的半透明 PNG，随选区生成/失效整体出现或消失。 */
function MaskOverlay({ url }: { url: string }) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!url) {
      setImage(null);
      return;
    }
    const img = new window.Image();
    img.onload = () => setImage(img);
    img.src = url;
    return () => {
      img.onload = null;
    };
  }, [url]);

  if (!image) return null;
  return <KonvaImage image={image} opacity={0.45} listening={false} />;
}

/**
 * 文字层渲染（M7）。
 *
 * 对齐规则与服务端 edits/render.py 的 _composite_text 一致：
 * 文字在图层框（transform.x/y/width/height）内水平垂直居中。
 * 字体栈把 Windows 的微软雅黑放最前 —— 服务端 Pillow 在本机命中的
 * 就是 msyh.ttc，两边同字体才能保证「所见即拍平所得」。
 */
const CANVAS_FONT_STACK =
  '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif';

function TextNode({
  layer,
  canvas,
}: {
  layer: LayerModel;
  canvas: LayerCanvas;
}) {
  const rect = layerRect(layer, canvas);
  const text = layer.text;
  if (!text) return null;
  return (
    <KonvaText
      x={rect.x}
      y={rect.y}
      width={Math.max(8, rect.width)}
      height={Math.max(12, rect.height)}
      text={text.text}
      fontSize={Math.max(8, text.font_size)}
      fill={text.fill}
      align="center"
      verticalAlign="middle"
      fontFamily={CANVAS_FONT_STACK}
      opacity={layer.opacity}
      rotation={rect.rotation}
      listening={false}
    />
  );
}

/**
 * 画布内裁剪框。
 *
 * 用 Konva Transformer 做手柄：四角 + 四边中点共 8 个，比例选择决定 keepRatio。
 * 手柄尺寸按 Stage 倍率反向补偿 —— 画布缩到 30% 时手柄若还是 10px 本地值，
 * 屏幕上只有 3px，根本点不到。
 *
 * 只做几何：框外压暗、框体可拖。裁完怎么写文档是调用方的事
 * （归一化后走 crop_canvas，画布变小、图层只平移）。
 */
function clampCropBox(box: CropBox, canvas: LayerCanvas): CropBox {
  const width = Math.min(box.width, canvas.width);
  const height = Math.min(box.height, canvas.height);
  return {
    width,
    height,
    x: Math.min(Math.max(0, box.x), canvas.width - width),
    y: Math.min(Math.max(0, box.y), canvas.height - height),
  };
}

function CropOverlay({
  canvas,
  box,
  ratio,
  scale,
  onChange,
}: {
  canvas: LayerCanvas;
  box: CropBox;
  /** null = 自由比例 */
  ratio: number | null;
  /** Stage 当前倍率：手柄与虚线要反向补偿 */
  scale: number;
  onChange: (box: CropBox) => void;
}) {
  const rectRef = useRef<Konva.Rect>(null);
  const transformerRef = useRef<Konva.Transformer>(null);

  useEffect(() => {
    const transformer = transformerRef.current;
    const node = rectRef.current;
    if (!transformer || !node) return;
    transformer.nodes([node]);
    transformer.getLayer()?.batchDraw();
  }, [box]);

  const commit = (next: CropBox) => {
    const clamped = clampCropBox(next, canvas);
    onChange(clamped);
    return clamped;
  };

  const invert = 1 / (scale || 1);

  return (
    <KonvaLayer>
      {/* 框外压暗：四块矩形拼出「挖洞」效果，比整层滤镜可靠 */}
      <Rect
        x={0}
        y={0}
        width={canvas.width}
        height={box.y}
        fill="rgba(9, 12, 20, 0.55)"
        listening={false}
      />
      <Rect
        x={0}
        y={box.y + box.height}
        width={canvas.width}
        height={Math.max(0, canvas.height - box.y - box.height)}
        fill="rgba(9, 12, 20, 0.55)"
        listening={false}
      />
      <Rect
        x={0}
        y={box.y}
        width={box.x}
        height={box.height}
        fill="rgba(9, 12, 20, 0.55)"
        listening={false}
      />
      <Rect
        x={box.x + box.width}
        y={box.y}
        width={Math.max(0, canvas.width - box.x - box.width)}
        height={box.height}
        fill="rgba(9, 12, 20, 0.55)"
        listening={false}
      />

      <Rect
        ref={rectRef}
        x={box.x}
        y={box.y}
        width={box.width}
        height={box.height}
        stroke="#5f98ad"
        strokeWidth={2}
        strokeScaleEnabled={false}
        dash={[7 * invert, 5 * invert]}
        fill="rgba(255,255,255,0.02)"
        draggable
        onDragMove={(event) => {
          const next = commit({
            ...box,
            x: event.target.x(),
            y: event.target.y(),
          });
          event.target.position({ x: next.x, y: next.y });
        }}
        onTransform={() => {
          const node = rectRef.current;
          if (!node) return;
          // Transformer 改的是 scale：折算回宽高后立刻复位，
          // 否则下一帧会「旧尺寸 × 新倍率」越拖越大
          const next = commit({
            x: node.x(),
            y: node.y(),
            width: Math.max(32, node.width() * Math.abs(node.scaleX())),
            height: Math.max(32, node.height() * Math.abs(node.scaleY())),
          });
          node.setAttrs({
            x: next.x,
            y: next.y,
            width: next.width,
            height: next.height,
            scaleX: 1,
            scaleY: 1,
          });
        }}
      />

      <Transformer
        ref={transformerRef}
        rotateEnabled={false}
        flipEnabled={false}
        keepRatio={ratio !== null}
        ignoreStroke
        enabledAnchors={[
          "top-left",
          "top-center",
          "top-right",
          "middle-left",
          "middle-right",
          "bottom-left",
          "bottom-center",
          "bottom-right",
        ]}
        anchorSize={10 * invert}
        anchorCornerRadius={3 * invert}
        anchorStrokeWidth={1.5 * invert}
        borderStrokeWidth={invert}
        anchorStroke="#427f95"
        anchorFill="#ffffff"
        borderStroke="#5f98ad"
        boundBoxFunc={(oldBox, nextBox) =>
          nextBox.width < 32 || nextBox.height < 32 ? oldBox : nextBox
        }
      />
    </KonvaLayer>
  );
}

export default function CanvasStage({
  doc,
  images,
  loading = false,
  zoom = null,
  stageRef,
  onScaleChange,
  selectionMode = "off",
  brushRadius = 0.03,
  maskUrl = null,
  markers = [],
  selectionBusy = false,
  hiddenLayerIds = null,
  failedAssetIds = null,
  selectedLayerId = null,
  previewAdjustments = null,
  onSelectLayer,
  onTransform,
  cropMode = false,
  cropBox = null,
  cropRatio = null,
  onCropBoxChange,
  onPointClick,
  onStrokeEnd,
}: {
  doc: LayerDocument;
  images: ImageMap;
  loading?: boolean;
  /** null = 贴齐容器宽；数字 = 固定倍率（1 = 100%） */
  zoom?: number | null;
  /** 导出要用 Stage 本体；由父级持有（视图状态不进文档） */
  stageRef?: MutableRefObject<Konva.Stage | null>;
  /** 实际生效的倍率回传给顶栏显示（fit 时的倍率只有这里算得出来） */
  onScaleChange?: (scale: number) => void;
  selectionMode?: SelectionMode;
  /** 笔刷半径，相对画布短边的比例 */
  brushRadius?: number;
  maskUrl?: string | null;
  markers?: SelectionMarker[];
  selectionBusy?: boolean;
  /** 对比模式：临时隐藏这些图层（视图状态，不进文档、不影响导出以外的一切） */
  hiddenLayerIds?: string[] | null;
  /** 素材图加载失败的 asset_id：这些层画占位告示，而不是静默消失 */
  failedAssetIds?: string[] | null;
  /** 当前选中的图层：显示变换框（视图状态，不进文档） */
  selectedLayerId?: string | null;
  /** 调色面板的实时预览：只影响这一层的渲染，不进文档 */
  previewAdjustments?: { layerId: string; adjustments: Adjustments } | null;
  onSelectLayer?: (layerId: string | null) => void;
  /** 画布内拖动/缩放/旋转松手后提交（由父级走工具写文档） */
  onTransform?: (layerId: string, patch: TransformPatch) => void;
  /** 裁剪模式：框外压暗、出现裁剪框；此时禁用图层选中与选区手势 */
  cropMode?: boolean;
  cropBox?: CropBox | null;
  /** null = 自由比例 */
  cropRatio?: number | null;
  onCropBoxChange?: (box: CropBox) => void;
  /** 点选模式下的单击回调（归一化坐标） */
  onPointClick?: (point: NormalizedPoint) => void;
  /** 笔刷模式下一笔结束的回调（归一化坐标序列） */
  onStrokeEnd?: (points: NormalizedPoint[]) => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const innerStageRef = useRef<Konva.Stage | null>(null);
  const stage = stageRef ?? innerStageRef;
  const transformerRef = useRef<Konva.Transformer | null>(null);
  // 可用区域是**宽 + 高**：只按宽度算会让 1:1 的画布在矮窗口里上下被裁
  const [boxSize, setBoxSize] = useState({ width: 0, height: 0 });
  // 正在画的笔迹（文档像素坐标），mouseup 时归一化交出去
  const [stroke, setStroke] = useState<NormalizedPoint[] | null>(null);
  const drawingRef = useRef(false);

  // 容器尺寸是唯一外部约束：编辑区旁边还有面板，写死宽度必然会溢出
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      setBoxSize({ width: rect?.width ?? 0, height: rect?.height ?? 0 });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { width: canvasWidth, height: canvasHeight } = doc.canvas;
  const fitScale = useMemo(() => {
    if (!boxSize.width || !boxSize.height || !canvasWidth || !canvasHeight) {
      return 0;
    }
    // 留 32px：内层 p-2 吃掉 16px，剩下 16px 给阴影、变换手柄和亚像素取整。
    // 贴到 0 余量时 canvas 宽度会算出 871.23 这种小数，浏览器一取整就出滚动条。
    const usableWidth = Math.max(0, boxSize.width - 32);
    const usableHeight = Math.max(0, boxSize.height - 32);
    return Math.min(usableWidth / canvasWidth, usableHeight / canvasHeight, 1); // 小图不放大到糊
  }, [boxSize, canvasWidth, canvasHeight]);
  const scale = zoom ?? fitScale;

  useEffect(() => {
    if (scale > 0) onScaleChange?.(scale);
  }, [scale, onScaleChange]);

  // 光标基线：图层 hover 会临时改成 grab / grabbing，离开后回到这里。
  // 刻意不写在 Stage 的 style 里 —— React 每次重渲染都会把它重置成 default，
  // 而 Konva 的 mouseenter 改的是容器 DOM 的 cursor，两边会互相打架。
  useEffect(() => {
    const container = stage.current?.container();
    if (!container) return;
    container.style.cursor =
      selectionMode === "off" && !cropMode ? "default" : "crosshair";
  }, [selectionMode, cropMode, stage]);

  // 选区模式切换时丢弃没画完的笔迹，避免上一次模式的残影
  useEffect(() => {
    if (selectionMode !== "brush") setStroke(null);
  }, [selectionMode]);

  // layers 数组从下到上，直接顺序渲染即可（不需要翻转 —— 翻转是为了给面板看）
  const hidden = useMemo(() => new Set(hiddenLayerIds ?? []), [hiddenLayerIds]);
  const drawable = doc.layers.filter(
    (layer) => layer.visible && !hidden.has(layer.id),
  );
  const failedAssets = useMemo(
    () => new Set(failedAssetIds ?? []),
    [failedAssetIds],
  );

  /**
   * 变换框跟着选中层走。
   *
   * 依赖里带 doc.layers / scale：图层重建（新文档）与缩放切换后，
   * Konva 节点是新实例，必须重新 attach，否则框会挂在已销毁的节点上。
   * 只给图像层装框：文字层的位置来自 OCR，拖动它会「改一次就再也对不上原文」。
   */
  useEffect(() => {
    const tr = transformerRef.current;
    const current = stage.current;
    if (!tr || !current) return;
    const layer = selectedLayerId
      ? doc.layers.find((item) => item.id === selectedLayerId)
      : null;
    const node =
      layer && layer.type === "image" && layer.visible && !cropMode
        ? current.findOne(
            (candidate: Konva.Node) => candidate.id() === `layer-${layer.id}`,
          )
        : null;
    tr.nodes(node ? [node] : []);
    tr.getLayer()?.batchDraw();
  }, [selectedLayerId, doc.layers, scale, stage, cropMode]);

  function pointerNormalized(): NormalizedPoint | null {
    const pos = stage.current?.getPointerPosition();
    if (!pos || scale === 0) return null;
    return { x: pos.x / scale / canvasWidth, y: pos.y / scale / canvasHeight };
  }

  function handleClick(event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (cropMode) return;
    if (selectionMode === "point") {
      if (selectionBusy || !onPointClick) return;
      const point = pointerNormalized();
      if (point) onPointClick(point);
      return;
    }
    // 点空白处取消选中：target 是 Stage 自己说明没点到任何图层
    if (event.target === event.target.getStage()) onSelectLayer?.(null);
  }

  function handleMouseDown() {
    if (cropMode || selectionMode !== "brush" || selectionBusy || !onStrokeEnd)
      return;
    drawingRef.current = true;
    const point = pointerNormalized();
    if (point) setStroke([point]);
  }

  function handleMouseMove() {
    if (!drawingRef.current) return;
    const point = pointerNormalized();
    if (point) setStroke((prev) => (prev ? [...prev, point] : [point]));
  }

  function handleMouseUp() {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    if (stroke && stroke.length > 0 && onStrokeEnd) {
      onStrokeEnd(stroke);
    }
    setStroke(null);
  }

  const brushWidthPx = Math.max(
    2,
    Math.min(canvasWidth, canvasHeight) * brushRadius,
  );
  const markerRadius = Math.max(4, Math.min(canvasWidth, canvasHeight) * 0.008);
  // 裁剪/选区模式下手柄让位：此时鼠标属于工具，不属于图层
  const directManipulation = selectionMode === "off" && !cropMode;

  return (
    // 根节点吃满可用区域：fit 的倍率就是按这个盒子的宽高算的。
    // 适应模式 overflow-hidden（尺寸已算到装得下）；手动放大后允许滚动看细节，
    // 但滚动条 UI 一律隐藏（scrollbar-none）—— 那条 bar 的出现条件
    // （纵向滚动条挤压宽度 → 横向也冒出来）对用户来说就是「莫名多了条滚动条」。
    <div
      ref={boxRef}
      className={`relative h-full w-full scrollbar-none ${
        zoom === null ? "overflow-hidden" : "overflow-auto"
      }`}
    >
      <div className="flex h-max min-h-full w-max min-w-full items-center justify-center p-2">
      {scale === 0 ? (
        <div className="bg-soft rounded-card h-64 w-64 animate-pulse" />
      ) : (
        <div className="rounded-md shadow-2xl ring-1 ring-white/10 overflow-hidden shrink-0">
          <Stage
            ref={stage}
            width={canvasWidth * scale}
            height={canvasHeight * scale}
            scaleX={scale}
            scaleY={scale}
            onClick={handleClick}
            onTap={handleClick}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onTouchMove={handleMouseMove}
            onTouchEnd={handleMouseUp}
          >
            <KonvaLayer listening={directManipulation}>
              {doc.canvas.background && (
                <Rect
                  x={0}
                  y={0}
                  width={canvasWidth}
                  height={canvasHeight}
                  fill={doc.canvas.background}
                  listening={false}
                />
              )}

              {drawable.map((layer) => {
                // M7 起文字层直接上画布（此前只在面板展示）——拆层产出的
                // 文字层必须看得到，「文案可改且位置不变」才有验证对象
                if (layer.type === "text") {
                  return (
                    <TextNode
                      key={layer.id}
                      layer={layer}
                      canvas={doc.canvas}
                    />
                  );
                }
                const assetId = layerSourceAssetId(layer);
                const image = assetId ? images[assetId] : undefined;
                if (!image) {
                  // 加载失败的素材给一块告示：静默 return null 等于「这一层凭空消失」
                  return assetId && failedAssets.has(assetId) ? (
                    <MissingLayer
                      key={layer.id}
                      layer={layer}
                      canvas={doc.canvas}
                    />
                  ) : null;
                }
                return (
                  <LayerNode
                    key={layer.id}
                    layer={layer}
                    canvas={doc.canvas}
                    image={image}
                    interactive={directManipulation}
                    preview={
                      previewAdjustments?.layerId === layer.id
                        ? previewAdjustments.adjustments
                        : null
                    }
                    onSelect={onSelectLayer}
                    onCommit={onTransform}
                  />
                );
              })}

              {/* 选区 overlay 与提示点：渲染属于画布，状态不属于文档 */}
              <MaskOverlay url={maskUrl ?? ""} />
              {markers.map((marker) => (
                <Group key={marker.index} listening={false}>
                  <Circle
                    x={marker.x * canvasWidth}
                    y={marker.y * canvasHeight}
                    radius={markerRadius}
                    fill="#ffffff"
                    stroke={SELECTION_COLOR}
                    strokeWidth={2}
                  />
                  <Circle
                    x={marker.x * canvasWidth}
                    y={marker.y * canvasHeight}
                    radius={markerRadius * 0.4}
                    fill={SELECTION_COLOR}
                  />
                </Group>
              ))}

              {/* 变换框：只有选中图像层且不在裁剪/选区模式时出现 */}
              <Transformer
                ref={transformerRef}
                rotateEnabled={directManipulation}
                flipEnabled={false}
                keepRatio={false}
                enabledAnchors={[
                  "top-left",
                  "top-center",
                  "top-right",
                  "middle-left",
                  "middle-right",
                  "bottom-left",
                  "bottom-center",
                  "bottom-right",
                ]}
                anchorSize={8}
                anchorCornerRadius={2}
                anchorStroke="#2563eb"
                anchorFill="#ffffff"
                borderStroke="#2563eb"
                borderStrokeWidth={1.5}
                rotateAnchorOffset={26}
                rotateAnchorCursor="grab"
                boundBoxFunc={(oldBox, nextBox) => {
                  if (nextBox.width < 16 || nextBox.height < 16) return oldBox
                  // 以中心缩放：Transformer 默认把对角锚点钉死（拖右下角时左上角不动），
                  // 这里把新框平移到与旧框同心 —— 拖任何一个角，图都围绕自身中心缩。
                  const centerX = oldBox.x + oldBox.width / 2
                  const centerY = oldBox.y + oldBox.height / 2
                  return {
                    ...nextBox,
                    x: centerX - nextBox.width / 2,
                    y: centerY - nextBox.height / 2,
                  }
                }}
              />
            </KonvaLayer>

            {/* 裁剪框独立一层：拖动它不该牵动别的图层 */}
            {cropMode && cropBox && onCropBoxChange && (
              <CropOverlay
                canvas={doc.canvas}
                box={cropBox}
                ratio={cropRatio}
                scale={scale}
                onChange={onCropBoxChange}
              />
            )}

            {/* 正在画的笔迹预览：纯视觉反馈，松手才交给服务端 */}
            {stroke && stroke.length > 0 && (
              <KonvaLayer listening={false}>
                <Line
                  points={stroke.flatMap((p) => [
                    p.x * canvasWidth,
                    p.y * canvasHeight,
                  ])}
                  stroke="rgba(95, 152, 173, 0.55)"
                  strokeWidth={brushWidthPx}
                  lineCap="round"
                  lineJoin="round"
                />
              </KonvaLayer>
            )}
          </Stage>
        </div>
      )}
      </div>

      {loading && (
        <span className="text-faint absolute top-3 left-3 text-xs">
          素材加载中…
        </span>
      )}
      {selectionBusy && (
        <span className="border-line bg-paper text-muted absolute top-3 right-3 rounded-card border px-2 py-1 text-xs shadow-sm">
          选区计算中…
        </span>
      )}
    </div>
  );
}

const SELECTION_COLOR = "#5f98ad";
