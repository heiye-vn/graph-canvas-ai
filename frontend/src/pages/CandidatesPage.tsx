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

import { getRun, listRunAssets } from '@/api/runs'
import type { RunOut } from '@/api/runs'
import { RunProgress } from '@/components/RunProgress'
import { useAuthStore } from '@/stores/authStore'
import { useRunStream } from '@/hooks/useRunStream'
import { isTerminalStatus } from '@/domain/events'
import type { RunStatus } from '@/domain/events'

export default function CandidatesPage() {
  const { runId = '' } = useParams()
  const queryClient = useQueryClient()
  const { user } = useAuthStore()

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
    return <p className="text-muted px-8 py-10 text-sm">加载中…</p>
  }

  if (run.isError) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-16 text-center">
        <p className="text-ink text-sm">这个任务不存在，或者它不属于当前账号。</p>
        <Link to="/create" className="text-brand hover:text-brand-strong mt-3 inline-block text-xs">
          回到创作页
        </Link>
      </div>
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
      <header className="mb-6">
        <p className="text-faint text-xs">{user?.email}</p>
        <h1 className="text-ink mt-1 text-2xl font-medium tracking-tight">候选图</h1>
        {prompt && <p className="text-muted mt-2 text-sm">{prompt}</p>}
      </header>

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
        <p className="bg-danger/10 text-danger mt-4 rounded-control px-4 py-3 text-sm">
          {stream.error}
        </p>
      )}
      {data.error?.message && (
        <p className="bg-danger/10 text-danger mt-4 rounded-control px-4 py-3 text-sm">
          {data.error.message}
        </p>
      )}

      <section className="mt-8">
        {total === 0 ? (
          <p className="text-muted text-sm">
            {isTerminalStatus(data.status) ? '这次没有产出可用的图。' : '正在生成，稍等片刻…'}
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {finished.map((asset) => (
              <figure
                key={asset.id}
                className="border-line bg-paper shadow-card overflow-hidden rounded-card border"
              >
                <img src={asset.url} alt="" className="h-44 w-full object-cover" loading="lazy" />
                <figcaption className="text-muted flex items-center justify-between px-3 py-2 text-xs">
                  <span className="font-mono">
                    {asset.width}×{asset.height}
                  </span>
                  <a
                    href={asset.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-brand hover:text-brand-strong transition"
                  >
                    查看原图
                  </a>
                </figcaption>
              </figure>
            ))}

            {live.map((candidate) => (
              <figure
                key={candidate.assetId}
                className="border-line bg-paper shadow-card overflow-hidden rounded-card border"
              >
                <img
                  src={candidate.url}
                  alt=""
                  className="h-44 w-full object-cover"
                  loading="lazy"
                />
                <figcaption className="text-faint px-3 py-2 text-xs">刚刚生成</figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>

      <footer className="mt-10 flex items-center gap-4">
        <Link
          to="/create"
          className="border-line bg-paper hover:border-brand rounded-control border px-3 py-1.5 text-xs text-ink shadow-control transition"
        >
          再生成一组
        </Link>
        <Link to="/" className="text-muted hover:text-ink text-xs transition">
          去素材库
        </Link>
      </footer>
    </div>
  )
}
