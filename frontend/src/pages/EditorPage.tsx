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

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Popover, Result, Segmented, Skeleton, Slider, Tooltip } from 'antd'
import {
  ClearOutlined,
  ColumnWidthOutlined,
  ExportOutlined,
  MinusOutlined,
  PlusOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { message } from 'antd'
import type Konva from 'konva'

import {
  clearSelection,
  createSelection,
  getSession,
  getSelection,
} from '@/api/sessions'
import type { SessionOut } from '@/api/sessions'
import { invokeTool, listTools } from '@/api/tools'
import CandidateStrip from '@/components/editor/CandidateStrip'
import CanvasStage from '@/components/editor/CanvasStage'
import type { SelectionMode } from '@/components/editor/CanvasStage'
import ChatPanel from '@/components/editor/ChatPanel'
import HistoryPanel from '@/components/editor/HistoryPanel'
import LayerPanel from '@/components/editor/LayerPanel'
import QuickToolbar from '@/components/editor/QuickToolbar'
import ToolPanel from '@/components/editor/ToolPanel'
import TransformPanel from '@/components/editor/TransformPanel'
import { RunProgress } from '@/components/RunProgress'
import { useLoadedImages } from '@/components/editor/useLoadedImages'
import { useRunStream } from '@/hooks/useRunStream'
import type { Layer } from '@/domain/layerDoc'
import { referencedAssetIds, topmostVisibleImageLayer } from '@/domain/layerDoc'

const ZOOM_STEP = 0.1
const ZOOM_MIN = 0.1
const ZOOM_MAX = 4

/** 排队型（重像素）工具 → 采用后的图层名。 */
const QUEUED_TOOL_LABEL: Record<string, string> = {
  erase_region: '局部消除结果',
  replace_region: '局部替换结果',
}

export default function EditorPage() {
  const { sessionId = '' } = useParams()
  const queryClient = useQueryClient()

  const session = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  })
  const tools = useQuery({ queryKey: ['tools'], queryFn: listTools })

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
      name: string
      params: Record<string, unknown>
    }) => invokeTool(name, sessionId, params),
    onSuccess: (result) => {
      queryClient.setQueryData(['session', sessionId], result.session)
      void queryClient.invalidateQueries({ queryKey: ['history', sessionId] })
      // 排队型工具：立即切到进度流，生成完自动采用
      if (result.run_id) setActiveRun({ id: result.run_id, tool: result.tool })
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
  })

  // ---- 视图状态（刻意不进文档：它们不产生撤销记录） ----
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null)
  const [toolName, setToolName] = useState<string | null>(null)
  const [zoom, setZoom] = useState<number | null>(null) // null = 适应容器
  const [currentScale, setCurrentScale] = useState(0)
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('off')
  const [brushRadius, setBrushRadius] = useState(0.03)
  const [activeRun, setActiveRun] = useState<{ id: string; tool: string } | null>(null)
  // 对比模式：临时隐藏最上层的图像层，看编辑前的样子（视图状态，不进文档）
  const [compare, setCompare] = useState(false)
  const stageRef = useRef<Konva.Stage | null>(null)

  const data = session.data as SessionOut | undefined
  const revision = data?.revision ?? null

  /**
   * 当前选区。queryKey 带 revision：文档一变（工具/撤销/重做）整个查询
   * 自动失效重取，过期选区后端返回 null，overlay 无感消失 ——
   * 「改图后旧选区自动失效」（DoD ③）在前端的表现就是这个键。
   */
  const selection = useQuery({
    queryKey: ['selection', sessionId, revision],
    queryFn: () => getSelection(sessionId),
    enabled: Boolean(sessionId) && revision !== null,
  })

  const updateSelection = useMutation({
    mutationFn: (payload: Parameters<typeof createSelection>[1]) =>
      createSelection(sessionId, payload),
    onSuccess: (result) => {
      queryClient.setQueryData(['selection', sessionId, revision], result)
    },
    onError: () => {
      // 409 = 画布已变：丢本地状态，让用户重新选
      void queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['selection', sessionId] })
    },
  })

  const removeSelection = useMutation({
    mutationFn: () => clearSelection(sessionId),
    onSuccess: () => {
      queryClient.setQueryData(['selection', sessionId, revision], null)
    },
  })

  // ---- 排队任务的进度流与自动采用 ----
  const runStream = useRunStream(activeRun?.id ?? null)
  const adoptingRef = useRef(false)

  useEffect(() => {
    if (!activeRun || !runStream.closed || runStream.status !== 'succeeded') return
    const asset = runStream.candidates[0]
    if (!asset) {
      setActiveRun(null)
      return
    }
    // 结果只上墙 → 自动采用为新图层（与候选页同一入口 add_image_layer）
    if (!adoptingRef.current) {
      adoptingRef.current = true
      runTool.mutate(
        {
          name: 'add_image_layer',
          params: {
            asset_id: asset.assetId,
            name: QUEUED_TOOL_LABEL[activeRun.tool] ?? '编辑结果',
          },
        },
        {
          onSuccess: () =>
            message.success('局部编辑完成，已加入画布。顶栏「对比」可查看编辑前的样子'),
          onSettled: () => {
            adoptingRef.current = false
            setActiveRun(null)
          },
        },
      )
    }
  }, [activeRun, runStream, runTool])

  const queueRun = (runId: string, tool: string) => setActiveRun({ id: runId, tool })

  // asset_id -> 预签名地址。必须 useMemo：useLoadedImages 靠引用变化去重
  const urlMap = useMemo(() => {
    if (!data) return {}
    const wanted = referencedAssetIds(data.doc)
    const map: Record<string, string> = {}
    for (const asset of data.assets) {
      if (wanted.includes(asset.id)) map[asset.id] = asset.url
    }
    return map
  }, [data])

  const { images, pending } = useLoadedImages(urlMap)

  /**
   * 变换面板的作用对象。
   *
   * 用户没点过图层时默认跟「当前图」走（与工具的默认目标一致）；
   * 选中的图层被删掉后回落到当前图 —— 选中一个不存在的图层只会让面板全部失灵。
   */
  const selectedLayer: Layer | null = useMemo(() => {
    if (!data) return null
    if (selectedLayerId) {
      const found = data.doc.layers.find((layer) => layer.id === selectedLayerId)
      if (found) return found
    }
    return topmostVisibleImageLayer(data.doc) ?? null
  }, [data, selectedLayerId])

  /**
   * 对比模式的作用对象：最上层的可见图像层（通常是最近一次编辑的结果）。
   * ⚠️ 必须留在早退 return 之前的 hooks 区 —— hook 顺序在两次渲染之间
   * 不允许变化（React 会直接抛 Fatal Error）。
   */
  const topImageLayerId = useMemo(() => {
    const layers = data?.doc.layers
    if (!layers) return null
    for (let i = layers.length - 1; i >= 0; i--) {
      const layer = layers[i]
      if (layer.visible && layer.type === 'image') return layer.id
    }
    return null
  }, [data])
  // 对比的前提是「藏起最上层还能看到别的东西」：可见图像层 < 2 时无从比起，
  // 硬按只会把画布掏成白底（文字层目前不上画布，M7 重构后另说）
  const visibleImageLayerCount = useMemo(
    () => (data?.doc.layers ?? []).filter((l) => l.visible && l.type === 'image').length,
    [data],
  )
  const canCompare = visibleImageLayerCount >= 2
  useEffect(() => {
    if (compare && !canCompare) setCompare(false)
  }, [compare, canCompare])
  const hiddenLayerIds = compare && topImageLayerId ? [topImageLayerId] : null

  function invoke(name: string, params: Record<string, unknown>) {
    runTool.mutate({ name, params })
  }

  /** 画布导出：Konva Stage 直接出 PNG（严格按画布设定分辨率 1:1 输出）。 */
  function exportPng() {
    const stage = stageRef.current
    if (!stage || !data) return
    // 抵消 Stage 当前为了适应屏幕或用户缩放产生的 scale，确保导出尺寸精确等于画布基准尺寸（如 1024x1024）
    const currentScale = stage.scaleX() || 1
    const pixelRatio = 1 / currentScale

    const link = document.createElement('a')
    link.href = stage.toDataURL({ pixelRatio, mimeType: 'image/png' })
    link.download = `${data.title || '画布'}.png`
    link.click()
  }

  function stepZoom(direction: 1 | -1) {
    const base = zoom ?? currentScale
    if (!base) return
    setZoom(
      Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round((base + direction * ZOOM_STEP) * 100) / 100)),
    )
  }

  if (session.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-8 py-10">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    )
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
    )
  }

  const doc = data.doc
  const selectionData = selection.data ?? null

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* ---- 顶栏 ---- */}
      <header className="border-line flex shrink-0 items-center gap-3 border-b px-4 py-2">
        <div className="min-w-0 shrink-0">
          <h1 className="m-0 truncate text-sm font-medium">{data.title}</h1>
          <p className="text-faint m-0 text-[11px]">
            {doc.canvas.width}×{doc.canvas.height} · {doc.layers.length} 个图层
          </p>
        </div>

        <div className="min-w-0 flex-1 overflow-x-auto">
          <QuickToolbar
            tools={tools.data?.items ?? []}
            selected={toolName}
            onSelect={setToolName}
          />
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {/* 选区三件套：模式切换 / 笔刷半径 / 清除。视图状态，不进文档 */}
          <Segmented
            size="small"
            value={selectionMode}
            onChange={(value) => setSelectionMode(value as SelectionMode)}
            options={[
              { label: '选区·关', value: 'off' },
              { label: '点选', value: 'point' },
              { label: '笔刷', value: 'brush' },
            ]}
          />
          {selectionMode === 'brush' && (
            <Popover
              placement="bottomRight"
              content={
                <div className="w-44 px-1 pt-1">
                  <p className="text-muted m-0 mb-2 text-xs">笔刷粗细</p>
                  <Slider
                    min={0.005}
                    max={0.12}
                    step={0.005}
                    value={brushRadius}
                    onChange={setBrushRadius}
                    tooltip={{ formatter: (v) => `${Math.round((v ?? 0) * 1000)}‰` }}
                  />
                </div>
              }
              trigger="click"
            >
              <Button size="small" type="text">
                粗细
              </Button>
            </Popover>
          )}
          {selectionData && (
            <Tooltip title="清除当前选区">
              <Button
                size="small"
                type="text"
                icon={<ClearOutlined />}
                loading={removeSelection.isPending}
                onClick={() => removeSelection.mutate()}
                aria-label="清除选区"
              />
            </Tooltip>
          )}
          <Tooltip title={canCompare ? '隐藏最上层图像，对比编辑前后效果' : '至少需要两层可见图像（例如一次局部编辑的结果叠在原图上）才能对比'}>
            <Button
              size="small"
              type={compare ? 'primary' : 'text'}
              icon={<SwapOutlined />}
              disabled={!canCompare}
              onClick={() => setCompare((prev) => !prev)}
              aria-label="对比编辑前后"
            >
              对比
            </Button>
          </Tooltip>

          <Tooltip title="缩小">
            <Button
              size="small"
              type="text"
              icon={<MinusOutlined />}
              onClick={() => stepZoom(-1)}
              aria-label="缩小"
            />
          </Tooltip>
          <span className="text-faint w-12 text-center text-xs tabular-nums">
            {zoom === null ? '适应' : `${Math.round(zoom * 100)}%`}
          </span>
          <Tooltip title="放大">
            <Button
              size="small"
              type="text"
              icon={<PlusOutlined />}
              onClick={() => stepZoom(1)}
              aria-label="放大"
            />
          </Tooltip>
          <Tooltip title="贴齐容器宽度">
            <Button
              size="small"
              type="text"
              icon={<ColumnWidthOutlined />}
              disabled={zoom === null}
              onClick={() => setZoom(null)}
              aria-label="适应容器"
            />
          </Tooltip>
          <Button size="small" icon={<ExportOutlined />} onClick={exportPng}>
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

      {/* ---- 三栏 ---- */}
      <div className="flex min-h-0 flex-1">
        {/* 左：对话 */}
        <section className="border-line bg-paper w-72 shrink-0 border-r">
          <ChatPanel sessionId={sessionId} onQueuedRun={queueRun} />
        </section>

        {/* 中：画布 + 候选图条 */}
        <section className="flex min-w-0 flex-1 flex-col">
          {selectionMode !== 'off' && (
            <div className="bg-brand-soft text-ink mx-3 mt-2 shrink-0 rounded-card px-3 py-1.5 text-xs">
              {selectionMode === 'point'
                ? '点选模式：在画面上单击要编辑的物体（可多点几次），然后到右侧选「局部消除 / 局部替换」执行'
                : '笔刷模式：按住鼠标在画面上涂抹要编辑的区域，然后到右侧选「局部消除 / 局部替换」执行'}
            </div>
          )}
          <div className="bg-soft relative min-h-0 flex-1 overflow-auto p-4">
            <div className="flex min-h-full items-start justify-center">
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

            {/* 排队任务进度：浮在画布上方，完成后自动采用并消失 */}
            {activeRun && !runStream.closed && (
              <div className="absolute bottom-4 left-1/2 w-72 -translate-x-1/2">
                <div className="bg-paper border-line rounded-card border p-3 shadow-md">
                  <RunProgress
                    status={runStream.status}
                    progress={runStream.progress}
                    stage={runStream.stage}
                  />
                </div>
              </div>
            )}
          </div>
          <CandidateStrip
            doc={doc}
            urls={urlMap}
            busy={runTool.isPending}
            onSwitch={(layerId) => invoke('switch_current_image', { layer: layerId })}
          />
        </section>

        {/* 右：图层 / 变换 / 工具 / 属性 / 编辑记录 */}
        <aside className="border-line bg-paper w-72 shrink-0 space-y-5 overflow-y-auto border-l p-3">
          <section>
            <h2 className="text-muted mb-2 text-xs font-medium">图层</h2>
            <LayerPanel
              doc={doc}
              selectedId={selectedLayer?.id ?? null}
              onSelect={setSelectedLayerId}
              busy={runTool.isPending}
              onToggleVisible={(layerId, visible) =>
                invoke('set_layer_visible', { layer: layerId, visible })
              }
              onSwitchCurrent={(layerId) => invoke('switch_current_image', { layer: layerId })}
            />
          </section>

          <section>
            <h2 className="text-muted mb-2 text-xs font-medium">变换</h2>
            <TransformPanel doc={doc} layer={selectedLayer} onInvoke={invoke} />
          </section>

          <section>
            <h2 className="text-muted mb-2 text-xs font-medium">工具参数</h2>
            <ToolPanel
              sessionId={sessionId}
              selected={toolName}
              onSelect={setToolName}
              onQueuedRun={queueRun}
            />
          </section>

          <section>
            <h2 className="text-muted mb-2 text-xs font-medium">属性</h2>
            <dl className="m-0 text-xs">
              {[
                ['画布', `${doc.canvas.width} × ${doc.canvas.height}`],
                ['导出格式', 'PNG'],
                ['图层数', String(doc.layers.length)],
                ['选区', selectionData ? '已有（工具将作用于选区内）' : '无'],
              ].map(([key, value]) => (
                <div key={key} className="flex items-center justify-between py-0.5">
                  <dt className="text-faint">{key}</dt>
                  <dd className="m-0 tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section>
            <HistoryPanel sessionId={sessionId} />
          </section>
        </aside>
      </div>
    </div>
  )
}
