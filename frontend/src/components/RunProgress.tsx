/**
 * 任务进度展示。创作页与候选页共用一份，避免「两处的进度条长得不一样」。
 *
 * 两个不变量：
 *   1. 宽度一律 clamp 到 0~100 —— 后端保证不了，但进度条溢出容器很难看
 *   2. 状态未知时显示「准备中」而不是空白 —— 空白会让用户以为卡死了
 */

import { STATUS_LABEL } from '@/domain/events'
import type { RunStatus } from '@/domain/events'

export function RunProgress({
  status,
  progress,
  stage,
}: {
  status: RunStatus | null
  progress: number
  stage?: string | null
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <StatusBadge status={status} />
        <span className="text-faint font-mono text-xs">{Math.round(progress)}%</span>
      </div>
      <div className="bg-soft mt-3 h-1.5 w-full overflow-hidden rounded-full">
        <div
          className="bg-brand h-full rounded-full transition-[width] duration-300"
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        />
      </div>
      {stage && <p className="text-muted mt-2 text-xs">{stage}</p>}
    </div>
  )
}

export function StatusBadge({ status }: { status: RunStatus | null }) {
  const failed = status === 'failed'
  return (
    <span
      className={`text-sm ${failed ? 'text-danger' : status === 'cancelled' ? 'text-muted' : 'text-ink'}`}
    >
      {status ? STATUS_LABEL[status] : '准备中'}
    </span>
  )
}
