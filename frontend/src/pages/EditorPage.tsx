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
 */

import { useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Result, Skeleton, Tooltip } from 'antd'
import {
  ColumnWidthOutlined,
  ExportOutlined,
  MinusOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import type Konva from 'konva'

import { getSession } from '@/api/sessions'
import type { SessionOut } from '@/api/sessions'
import { invokeTool, listTools } from '@/api/tools'
import CandidateStrip from '@/components/editor/CandidateStrip'
import CanvasStage from '@/components/editor/CanvasStage'
import ChatPanel from '@/components/editor/ChatPanel'
import HistoryPanel from '@/components/editor/HistoryPanel'
import LayerPanel from '@/components/editor/LayerPanel'
import QuickToolbar from '@/components/editor/QuickToolbar'
import ToolPanel from '@/components/editor/ToolPanel'
import TransformPanel from '@/components/editor/TransformPanel'
import { useLoadedImages } from '@/components/editor/useLoadedImages'
import type { Layer } from '@/domain/layerDoc'
import { referencedAssetIds, topmostVisibleImageLayer } from '@/domain/layerDoc'

const ZOOM_STEP = 0.1
const ZOOM_MIN = 0.1
const ZOOM_MAX = 4

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
  const stageRef = useRef<Konva.Stage | null>(null)

  const data = session.data as SessionOut | undefined

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

      {/* ---- 三栏 ---- */}
      <div className="flex min-h-0 flex-1">
        {/* 左：对话 */}
        <section className="border-line bg-paper w-72 shrink-0 border-r">
          <ChatPanel sessionId={sessionId} />
        </section>

        {/* 中：画布 + 候选图条 */}
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="bg-soft min-h-0 flex-1 overflow-auto p-4">
            <div className="flex min-h-full items-start justify-center">
              <CanvasStage
                doc={doc}
                images={images}
                loading={pending}
                zoom={zoom}
                stageRef={stageRef}
                onScaleChange={setCurrentScale}
              />
            </div>
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
            <ToolPanel sessionId={sessionId} selected={toolName} onSelect={setToolName} />
          </section>

          <section>
            <h2 className="text-muted mb-2 text-xs font-medium">属性</h2>
            <dl className="m-0 text-xs">
              {[
                ['画布', `${doc.canvas.width} × ${doc.canvas.height}`],
                ['导出格式', 'PNG'],
                ['图层数', String(doc.layers.length)],
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
