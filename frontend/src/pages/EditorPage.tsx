/**
 * 编辑工作台。
 *
 * 三条原则在这里落地：
 *   1. **session id 在 URL 上** —— 刷新重建、分享直达都靠它
 *   2. **文档是唯一真相源** —— 画布和图层面板都只是它的投影，没有一个
 *      「真正被编辑的东西」藏在 store 里；刷新后从 REST 拿回来的就是下一次渲染的全部输入
 *   3. **改动先乐观更新、失败回滚** —— 切个图层还要等一轮 HTTP 太钝，
 *      但请求失败必须能回到服务端真实状态，否则用户看到的是幻觉
 */

import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Result, Skeleton, Spin } from 'antd'
import { SaveOutlined } from '@ant-design/icons'

import { getSession, replaceSessionDoc } from '@/api/sessions'
import type { SessionOut } from '@/api/sessions'
import CanvasStage from '@/components/editor/CanvasStage'
import LayerPanel from '@/components/editor/LayerPanel'
import { useLoadedImages } from '@/components/editor/useLoadedImages'
import PageHeader from '@/components/PageHeader'
import type { LayerDocument } from '@/domain/layerDoc'
import { referencedAssetIds, setLayerVisible, switchCurrentImage } from '@/domain/layerDoc'

export default function EditorPage() {
  const { sessionId = '' } = useParams()
  const queryClient = useQueryClient()

  const session = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  })

  const save = useMutation({
    mutationFn: (doc: LayerDocument) => replaceSessionDoc(sessionId, doc),
    onError: () => {
      // 服务端没接受这次改动，重新拉一次回到真实状态
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

  function commit(next: LayerDocument) {
    if (!data) return
    queryClient.setQueryData(['session', sessionId], { ...data, doc: next })
    save.mutate(next)
  }

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
        extra={
          <span className="text-faint inline-flex items-center gap-2 text-xs">
            {save.isPending ? (
              <>
                <Spin size="small" /> 保存中
              </>
            ) : (
              <>
                <SaveOutlined /> 已同步到服务端
              </>
            )}
          </span>
        }
      />

      {save.isError && (
        <Alert
          className="mb-4"
          type="error"
          showIcon
          message="这次改动没能保存到服务端，画布已回滚到上一次成功的状态。"
        />
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section className="border-line bg-paper shadow-card flex min-h-[26rem] items-start justify-center rounded-card border p-4">
          <CanvasStage doc={doc} images={images} loading={pending} />
        </section>

        <aside className="border-line bg-paper shadow-card rounded-card border p-4">
          <h2 className="text-muted mb-2 text-sm font-medium">图层</h2>
          <LayerPanel
            doc={doc}
            onToggleVisible={(layerId, visible) => commit(setLayerVisible(doc, layerId, visible))}
            onSwitchCurrent={(layerId) => commit(switchCurrentImage(doc, layerId))}
          />
        </aside>
      </div>
    </div>
  )
}
