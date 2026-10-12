/**
 * 生图工作台（M2 端到端闭环）。
 *
 * 交互顺序刻意固定为「先拿 run id → 再订阅 → 最后才渲染进度」：
 * 反过来的话，任务可能在订阅建立前就结束，前端永远等不到任何事件。
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'

import { SIZE_PRESETS, cancelRun, createTextToImage } from '@/api/runs'
import type { RunOut } from '@/api/runs'
import { useRunStream } from '@/hooks/useRunStream'
import { STATUS_LABEL } from '@/domain/events'
import type { RunStatus } from '@/domain/events'
import { APP_BADGE, APP_NAME } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'

export default function CreatePage() {
  const { user, signOut } = useAuthStore()
  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState<string>(SIZE_PRESETS[0].value)
  const [count, setCount] = useState(1)
  const [runId, setRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const stream = useRunStream(runId)

  const submit = useMutation({
    mutationFn: () => createTextToImage({ prompt, size, n: count }),
    onSuccess: (run: RunOut) => {
      setError(null)
      setRunId(run.id) // 先落 run id，hook 随即建立 SSE 订阅
    },
    onError: (err: Error) => setError(err.message),
  })

  const cancel = useMutation({
    mutationFn: () => cancelRun(runId as string),
    onError: (err: Error) => setError(err.message),
  })

  const busy =
    submit.isPending ||
    (stream.status !== null && stream.status !== 'succeeded' && !stream.closed) ||
    (stream.status === null && runId !== null && !stream.closed)

  const shownStatus: RunStatus | null = stream.status
  const canSubmit = prompt.trim().length > 0 && !busy

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-medium text-ink">
            生成图片
            <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold tracking-wide text-dark">
              {APP_BADGE}
            </span>
          </h1>
          <p className="mt-1 text-xs text-faint">
            {APP_NAME} · {user?.email}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/"
            className="rounded-control border border-line bg-paper px-3 py-1.5 text-xs text-ink shadow-control transition hover:border-brand"
          >
            素材库
          </Link>
          <button
            type="button"
            onClick={signOut}
            className="rounded-control px-3 py-1.5 text-xs text-muted transition hover:text-ink"
          >
            退出
          </button>
        </div>
      </header>

      <section className="rounded-card border border-line bg-paper p-5 shadow-card">
        <label htmlFor="prompt" className="block text-xs text-muted">
          描述你想要的画面
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="例如：白色背景上的透明玻璃精华瓶，柔和顶光，电商主图质感"
          className="mt-2 w-full resize-none rounded-control border border-line bg-soft px-3 py-2 text-sm text-ink outline-none transition focus:border-brand"
        />

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <span className="block text-xs text-muted">尺寸</span>
            <select
              value={size}
              onChange={(e) => setSize(e.target.value)}
              className="mt-1 rounded-control border border-line bg-soft px-3 py-2 text-sm text-ink outline-none transition focus:border-brand"
            >
              {SIZE_PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <span className="block text-xs text-muted">张数</span>
            <select
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="mt-1 rounded-control border border-line bg-soft px-3 py-2 text-sm text-ink outline-none transition focus:border-brand"
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n} 张
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => submit.mutate()}
            className="rounded-control bg-brand px-5 py-2 text-sm font-medium text-white shadow-control transition hover:bg-brand-strong disabled:opacity-50"
          >
            {submit.isPending ? '提交中…' : '生成'}
          </button>

          {runId && !stream.closed && (
            <button
              type="button"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
              className="rounded-control border border-line px-3 py-2 text-xs text-muted transition hover:border-danger hover:text-danger disabled:opacity-50"
            >
              取消
            </button>
          )}
        </div>

        <p className="mt-3 text-xs text-faint">
          当前接入本地占位模型，出图会带 MOCK 标记 —— 用于验证链路，不是真实模型效果。
        </p>
      </section>

      {error && (
        <p className="mt-4 rounded-control bg-danger/10 px-4 py-3 text-sm text-danger">{error}</p>
      )}
      {stream.error && !error && (
        <p className="mt-4 rounded-control bg-danger/10 px-4 py-3 text-sm text-danger">
          {stream.error}
        </p>
      )}

      {runId && <ProgressPanel status={shownStatus} progress={stream.progress} stage={stream.stage} />}

      {stream.candidates.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-medium text-ink">候选图</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {stream.candidates.map((candidate) => (
              <figure
                key={candidate.assetId}
                className="overflow-hidden rounded-card border border-line bg-paper shadow-card"
              >
                <img
                  src={candidate.url}
                  alt=""
                  className="h-40 w-full object-cover"
                  loading="lazy"
                />
                <figcaption className="px-3 py-2">
                  <a
                    href={candidate.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-brand transition hover:text-brand-strong"
                  >
                    查看原图
                  </a>
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function ProgressPanel({
  status,
  progress,
  stage,
}: {
  status: RunStatus | null
  progress: number
  stage: string | null
}) {
  return (
    <section className="mt-6 rounded-card border border-line bg-paper p-5 shadow-card">
      <div className="flex items-center justify-between text-sm">
        <span className="text-ink">{status ? STATUS_LABEL[status] : '已提交'}</span>
        <span className="font-mono text-xs text-faint">{progress}%</span>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-soft">
        <div
          className="h-full rounded-full bg-brand transition-[width] duration-300"
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        />
      </div>
      {stage && <p className="mt-2 text-xs text-muted">{stage}</p>}
    </section>
  )
}
