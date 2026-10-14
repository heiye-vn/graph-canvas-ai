/**
 * 编辑工作台。
 *
 * 四条原则在这里落地：
 *   1. **session id 在 URL 上** —— 刷新重建、分享直达都靠它
 *   2. **文档是唯一真相源** —— 画布和图层面板都只是它的投影，没有一个
 *      「真正被编辑的东西」藏在 store 里；刷新后从 REST 拿回来的就是下一次渲染的全部输入
 *   3. **所有改动都走工具入口** —— M5 起这条不能破：面板上的「显示/隐藏」「设为当前图」
 *      以前是直接改文档，那样它们不会进撤销栈，用户会发现「有些操作退不回去」
 *   4. **失败回滚** —— 请求失败必须能回到服务端真实状态，否则用户看到的是幻觉
 */

import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Result, Skeleton } from 'antd'
import { Button } from 'antd'

import { getSession } from '@/api/sessions'
import type { SessionOut } from '@/api/sessions'
import { invokeTool } from '@/api/tools'
import AgentBar from '@/components/editor/AgentBar'
import CanvasStage from '@/components/editor/CanvasStage'
import HistoryBar from '@/components/editor/HistoryBar'
import LayerPanel from '@/components/editor/LayerPanel'
import ToolPanel from '@/components/editor/ToolPanel'
import { useLoadedImages } from '@/components/editor/useLoadedImages'
import PageHeader from '@/components/PageHeader'
import { referencedAssetIds } from '@/domain/layerDoc'

export default function EditorPage() {
  const { sessionId = '' } = useParams()
  const queryClient = useQueryClient()

  const session = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  })

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

  if (session.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-8 py-10">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    )
  }

  if (session.isError) {
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

  if (!data) return null
  const doc = data.doc

  return (
    <div className="mx-auto w-full max-w-6xl px-8 py-8">
      <PageHeader
        title={data.title}
        description={`${doc.canvas.width}×${doc.canvas.height} · ${doc.layers.length} 个图层`}
      />

      {runTool.isError && (
        <Alert
          className="mb-4"
          type="error"
          showIcon
          message="这次改动没能保存到服务端，画布已回滚到上一次成功的状态。"
        />
      )}

      <div className="border-line bg-paper shadow-card rounded-card mb-6 border p-4">
        <h2 className="text-muted mb-2 text-sm font-medium">一句话改图</h2>
        <AgentBar sessionId={sessionId} />
      </div>

      <HistoryBar sessionId={sessionId} />

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section className="border-line bg-paper shadow-card flex min-h-[26rem] items-start justify-center rounded-card border p-4">
          <CanvasStage doc={doc} images={images} loading={pending} />
        </section>

        <aside className="border-line bg-paper shadow-card rounded-card border p-4">
          <h2 className="text-muted mb-2 text-sm font-medium">图层</h2>
          <LayerPanel
            doc={doc}
            busy={runTool.isPending}
            onToggleVisible={(layerId, visible) =>
              runTool.mutate({
                name: 'set_layer_visible',
                params: { layer: layerId, visible },
              })
            }
            onSwitchCurrent={(layerId) =>
              runTool.mutate({ name: 'switch_current_image', params: { layer: layerId } })
            }
          />

          <h2 className="text-muted mt-6 mb-2 text-sm font-medium">工具</h2>
          <ToolPanel sessionId={sessionId} />
        </aside>
      </div>
    </div>
  )
}
