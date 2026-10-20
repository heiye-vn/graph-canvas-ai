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
import { Alert, Button, Result, Spin } from 'antd'

import { getRun, listRunAssets } from '@/api/runs'
import type { RunOut } from '@/api/runs'
import AssetCard from '@/components/AssetCard'

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
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 m-0">生成结果候选</h1>
            <span className="rounded-full bg-blue-50 text-blue-600 px-2 py-0.5 text-xs font-semibold font-mono">
              {total} 张产出
            </span>
          </div>
          {prompt && (
            <p className="text-xs text-slate-500 m-0 mt-1 max-w-xl truncate">
              提示词：<span className="text-slate-800 font-medium">"{prompt}"</span>
            </p>
          )}
        </div>

        {isTerminalStatus(data.status) && (
          <div className="flex items-center gap-2">
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
              className="h-8! px-4! text-xs! font-semibold rounded-lg shadow-sm"
            >
              在画布中编辑
            </Button>
            <Link to="/create">
              <Button className="h-8! text-xs! rounded-lg">再生成一组</Button>
            </Link>
          </div>
        )}
      </div>

      {/* 实时生成进度卡片 */}
      {(!isTerminalStatus(data.status) || stream.status) && (
        <section className="mt-6 rounded-xl border border-blue-200 bg-blue-50/30 p-5 shadow-2xs">
          <RunProgress
            status={stream.status ?? data.status}
            progress={stream.status ? stream.progress : data.progress}
            stage={stream.stage ?? data.stage}
          />
        </section>
      )}

      {stream.error && (
        <Alert className="mt-4 rounded-lg" type="error" showIcon message={stream.error} closable />
      )}
      {data.error?.message && (
        <Alert className="mt-4 rounded-lg" type="error" showIcon message={data.error.message} />
      )}

      {/* 候选卡片网格 */}
      <section className="mt-8">
        {total === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-12 text-center text-xs text-slate-400">
            {isTerminalStatus(data.status) ? '本次任务未产出图像。' : '正在实时生成中，请稍候…'}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {finished.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                onEdit={() =>
                  openEditor.mutate({
                    asset_ids: [asset.id],
                    title: prompt ? `${prompt.slice(0, 20)}…` : undefined,
                  })
                }
              />
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

