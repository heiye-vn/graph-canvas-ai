/**
 * 执行轨迹弹层（M9.3 DoD ①）：一次对话的全链路 span 时间轴。
 *
 * 每行 = 一个 span（规划/校验/每步工具/反思），右侧是耗时条 ——
 * 耗时条按全局最大耗时归一化，一眼看出时间花在哪个环节。
 */

import { useQuery } from '@tanstack/react-query'
import { Modal } from 'antd'

import { getTrace } from '@/api/agent'
import type { TraceSpan } from '@/api/agent'

const KIND_LABEL: Record<TraceSpan['kind'], string> = {
  planner: '规划',
  validate: '校验',
  tool: '工具',
  reflect: '反思',
  turn: '整轮',
}

const KIND_COLOR: Record<TraceSpan['kind'], string> = {
  planner: 'processing',
  validate: 'gold',
  tool: 'success',
  reflect: 'warning',
  turn: 'default',
}

export default function TraceModal({
  runId,
  open,
  onClose,
}: {
  runId: string
  open: boolean
  onClose: () => void
}) {
  const trace = useQuery({
    queryKey: ['trace', runId],
    queryFn: () => getTrace(runId),
    enabled: open,
  })

  const spans = trace.data ?? []
  const maxDuration = Math.max(1, ...spans.map((span) => span.duration_ms ?? 0))

  return (
    <Modal
      title="执行轨迹"
      open={open}
      onCancel={onClose}
      footer={null}
      width={560}
    >
      {trace.isLoading && <p className="text-faint text-xs">加载中…</p>}
      {!trace.isLoading && spans.length === 0 && (
        <p className="text-faint text-xs">这条对话还没有轨迹数据（可能是旧版本产生的）。</p>
      )}

      <div className="space-y-1.5">
        {spans.map((span) => (
          <div key={span.id} className="border-line rounded-control border px-2.5 py-1.5">
            <div className="flex items-center gap-1.5 text-xs">
              <span className={`ant-tag ant-tag-${KIND_COLOR[span.kind]} m-0`}>
                {KIND_LABEL[span.kind]}
              </span>
              <span className="min-w-0 flex-1 truncate">{span.name}</span>
              <span
                className={span.status === 'failed' ? 'text-danger' : 'text-success'}
                title={span.status}
              >
                {span.status === 'failed' ? '✕' : '✓'}
              </span>
            </div>

            <div className="mt-1 flex items-center gap-2">
              <div className="bg-soft h-1.5 min-w-0 flex-1 overflow-hidden rounded-full">
                <div
                  className={span.status === 'failed' ? 'bg-danger h-full' : 'bg-brand h-full'}
                  style={{ width: `${Math.round(((span.duration_ms ?? 0) / maxDuration) * 100)}%` }}
                />
              </div>
              <span className="text-faint w-14 text-right text-[10px] tabular-nums">
                {span.duration_ms != null ? `${span.duration_ms}ms` : '—'}
              </span>
            </div>

            <div className="text-faint mt-1 flex flex-wrap gap-x-3 text-[10px]">
              {span.model && <span>{span.model}</span>}
              {span.tokens_out != null && <span>out {span.tokens_out} tok</span>}
              {span.prompt_version && <span>{span.prompt_version}</span>}
              {span.detail?.error != null && (
                <span className="text-danger">{String(span.detail.error)}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
