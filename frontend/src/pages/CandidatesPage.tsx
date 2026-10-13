/**
 * 候选图页 —— 独立路由 `/candidates/:runId`。
 *
 * 为什么必须独立成一页而不是内嵌在创作页里：
 *   run id 在 URL 上 = 可刷新、可分享、可后退。内嵌方案里 run id 只活在内存，
 *   刷新一下这次生成的图就找不回来了。
 *
 * 首屏的状态来自 REST（`GET /runs/{id}` + `GET /runs/{id}/assets`），
 * SSE 只负责**还在跑的任务**的实时增量 —— 现场恢复一律走 REST，
 * 事件流从来不作为唯一数据源。
 */

import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Empty, Result, Space, Spin } from 'antd'

import { getRun, listRunAssets } from '@/api/runs'
import type { RunOut } from '@/api/runs'
import AssetCard from '@/components/AssetCard'
import PageHeader from '@/components/PageHeader'
import { RunProgress } from '@/components/RunProgress'
import { useCreateSessionAndEdit } from '@/hooks/useCreateSession'
import { useRunStream } from '@/hooks/useRunStream'
import { isTerminalStatus } from '@/domain/events'
import type { RunStatus } from '@/domain/events'

export default function CandidatesPage() {
  const { runId = '' } = useParams()
  const queryClient = useQueryClient()
  const openEditor = useCreateSessionAndEdit()

  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId),
    enabled: Boolean(runId),
    retry: false,
  })

  const assets = useQuery({
    queryKey: ['run-assets', runId],
    queryFn: () => listRunAssets(runId),
    enabled: Boolean(runId),
    retry: false,
  })

  const status: RunStatus | null = run.data?.status ?? null
  const stillRunning = status !== null && !isTerminalStatus(status)

  // 只有还在跑的任务才订阅；已结束的任务开 SSE 会白等一整个心跳周期
  const stream = useRunStream(stillRunning ? runId : null)

  useEffect(() => {
    if (!stream.closed) return
    queryClient.invalidateQueries({ queryKey: ['run', runId] })
    queryClient.invalidateQueries({ queryKey: ['run-assets', runId] })
    queryClient.invalidateQueries({ queryKey: ['assets'] })
  }, [stream.closed, queryClient, runId])

  if (run.isLoading) {
    return (
      <div className="flex justify-center py-28">
        <Spin size="large" />
      </div>
    )
  }

  if (run.isError) {
    return (
      <Result
        status="404"
        title="找不到这个任务"
        subTitle="它可能已被清理，或者不属于当前账号。"
        extra={
          <Link to="/create">
            <Button type="primary">回到创作页</Button>
          </Link>
        }
      />
    )
  }

  const data = run.data as RunOut
  const prompt = String(data.params?.prompt ?? '')
  const finished = assets.data ?? []
  const live = stream.candidates.filter(
    (candidate) => !finished.some((item) => item.id === candidate.assetId),
  )
  const total = finished.length + live.length

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <PageHeader
        title="候选图"
        description={prompt || undefined}
        extra={
          isTerminalStatus(data.status) ? (
            <Space>
              <Button
                type="primary"
                loading={openEditor.isPending}
                disabled={total === 0}
                onClick={() =>
                  openEditor.mutate({
                    asset_ids: [
                      ...finished.map((asset) => asset.id),
                      ...live.map((candidate) => candidate.assetId),
                    ],
                    title: prompt ? `${prompt.slice(0, 20)}…` : undefined,
                  })
                }
              >
                在画布中编辑
              </Button>
              <Link to="/create">
                <Button>再生成一组</Button>
              </Link>
              <Link to="/assets">
                <Button type="link">去素材库</Button>
              </Link>
            </Space>
          ) : null
        }
      />

      {(!isTerminalStatus(data.status) || stream.status) && (
        <section className="border-line bg-paper shadow-card rounded-card border p-5">
          <RunProgress
            status={stream.status ?? data.status}
            progress={stream.status ? stream.progress : data.progress}
            stage={stream.stage ?? data.stage}
          />
        </section>
      )}

      {stream.error && (
        <Alert className="mt-4" type="error" showIcon message={stream.error} closable />
      )}
      {data.error?.message && (
        <Alert className="mt-4" type="error" showIcon message={data.error.message} />
      )}

      <section className="mt-8">
        {total === 0 ? (
          <Empty
            description={
              isTerminalStatus(data.status) ? '这次没有产出可用的图。' : '正在生成，稍等片刻…'
            }
          />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {finished.map((asset) => (
              <AssetCard key={asset.id} asset={asset} />
            ))}

            {live.map((candidate) => (
              <AssetCard
                key={candidate.assetId}
                pending
                asset={{
                  id: candidate.assetId,
                  url: candidate.url,
                  width: null,
                  height: null,
                }}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
