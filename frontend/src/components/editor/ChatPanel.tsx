/**
 * 左侧对话面板 —— Agent 多步计划入口（M8）。
 *
 * 一句话 → /agent/plan → 计划卡片：
 *   >1 步停在 awaiting_confirm 等确认；确认后逐段执行，排队步（局部编辑、
 *   拆层）挂进度条，完成自动驱动下一步 —— 「去背景再换海边然后调亮」
 *   这类复合指令从此是一张卡片，而不是三轮各自为政的对话。
 *
 * 状态恢复：消息本身仍存组件状态（持久化是 M9.2 checkpointer 的事），
 * 但计划卡片以 agent_runs 表为真相源 —— 刷新后从 /agent/sessions/{id}/runs
 * 重建，执行到哪一步就显示到哪一步（DoD ④：刷新不白屏、不丢现场）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Input, Tag, Tooltip } from 'antd'
import { CheckOutlined, CloseOutlined, RedoOutlined, SendOutlined } from '@ant-design/icons'

import {
  cancelPlan,
  confirmPlan,
  continuePlan,
  createPlan,
  getAgentRun,
  listSessionRuns,
  retryPlan,
} from '@/api/agent'
import type { AgentRun, PlanStep } from '@/api/agent'
import { useRunStream } from '@/hooks/useRunStream'
import { useCotStream } from '@/hooks/useCotStream'
import CoTStream from '@/components/agent/CoTStream'
import TraceModal from '@/components/agent/TraceModal'
import { FileSearchOutlined } from '@ant-design/icons'

interface ChatMessage {
  role: 'user' | 'agent'
  text?: string
  runId?: string
}

const SUGGESTIONS = [
  '把图调亮一点',
  '拆成背景和主体，同时拆出文字',
  '把图变亮然后水平翻转',
  '消除选区里的物体',
]

export default function ChatPanel({
  sessionId,
  onChanged,
  onQueuedRun,
}: {
  sessionId: string
  /** 任何步骤落地后通知外层（画布文档变了） */
  onChanged?: () => void
  /** Agent 触发了排队型任务（局部编辑/拆层等）：外层凭 run_id 挂进度条 */
  onQueuedRun?: (runId: string, tool: string) => void
}) {
  const queryClient = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)

  // 恢复现场：这个会话的历史对话轮（计划卡片以 agent_runs 表为真相源）
  const history = useQuery({
    queryKey: ['agentRuns', sessionId],
    queryFn: () => listSessionRuns(sessionId),
    enabled: Boolean(sessionId),
  })

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages, history.data])

  useEffect(() => {
    const runs = history.data ?? []
    if (runs.length > 0 && messages.length === 0) {
      setMessages(
        runs.map((run) => ({
          role: 'agent' as const,
          runId: run.id,
          text: run.instruction ? undefined : undefined,
        })),
      )
    }
  }, [history.data, messages.length])

  const plan = useMutation({
    mutationFn: (instruction: string) => createPlan(sessionId, instruction),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ['agentRuns', sessionId] })
      setMessages((prev) => [...prev, { role: 'agent', runId: run.id }])
    },
    onError: (error) => {
      setMessages((prev) => [...prev, { role: 'agent', text: (error as Error).message }])
    },
  })

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || plan.isPending) return
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setInput('')
    plan.mutate(trimmed)
  }

  const busy = plan.isPending

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="text-faint px-1 text-xs leading-relaxed">
            用一句话描述要改什么；说了几件事我会拆成计划，确认后逐步执行。
            <div className="mt-3 flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((text) => (
                <button
                  key={text}
                  type="button"
                  onClick={() => send(text)}
                  className="border-line text-muted hover:border-brand hover:text-brand rounded-control border px-2 py-1 text-xs transition-colors"
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) =>
          message.role === 'user' ? (
            <div key={index} className="flex justify-end">
              <p className="bg-brand-soft text-ink rounded-control max-w-[85%] px-3 py-2 text-sm">
                {message.text}
              </p>
            </div>
          ) : message.runId ? (
            <PlanCard
              key={index}
              runId={message.runId}
              onQueuedRun={onQueuedRun}
              onChanged={onChanged}
            />
          ) : (
            <p key={index} className="text-danger text-xs">
              {message.text}
            </p>
          ),
        )}
      </div>

      <div className="border-line border-t p-3">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={() => send(input)}
            placeholder="描述要改的内容…"
            disabled={busy}
          />
          <Tooltip title={busy ? '正在规划' : '发送'}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={busy}
              disabled={input.trim().length === 0}
              onClick={() => send(input)}
            />
          </Tooltip>
        </div>
      </div>
    </div>
  )
}

/** 单条计划卡片：状态、步骤、按钮、排队步的自动推进都在这里。 */
function PlanCard({
  runId,
  onQueuedRun,
  onChanged,
}: {
  runId: string
  onQueuedRun?: (runId: string, tool: string) => void
  onChanged?: () => void
}) {
  // run 是本地真相源的缓存；每次 API 响应整体覆盖
  const [run, setRun] = useState<AgentRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)
  const reportedRef = useRef<string | null>(null)
  // 每次行动（确认/重试/继续）后重开 CoT 流：执行期的 observation 也在同一条通道
  const [cotEpoch, setCotEpoch] = useState(0)
  const cot = useCotStream(runId, true, cotEpoch)

  const load = useCallback(async () => {
    try {
      setRun(await getAgentRun(runId))
    } catch (err) {
      setError((err as Error).message)
    }
  }, [runId])

  useEffect(() => {
    void load()
  }, [load])

  // CoT 流收束 = 规划/推进到了终态（或断线）—— 拉一次最新现场
  const refreshOnClose = useRef(false)
  useEffect(() => {
    if (cot.closed && !refreshOnClose.current) {
      refreshOnClose.current = true
      void load()
    }
    if (!cot.closed) refreshOnClose.current = false
  }, [cot.closed, load])

  // 恢复现场后计划若停在 awaiting_confirm / failed，卡片直接可交互；
  // 执行中的排队步 → 订阅它的进度流
  const watching = run?.plan.find(
    (step) => step.status === 'queued' && step.run_id && step.tool !== 'text_to_image',
  )
  const stream = useRunStream(watching?.run_id ?? null)

  // 排队步交给外层挂进度条（去重，防 effect 重跑造成重复上报）
  useEffect(() => {
    if (watching?.run_id && reportedRef.current !== watching.run_id) {
      reportedRef.current = watching.run_id
      onQueuedRun?.(watching.run_id, watching.tool)
    }
  }, [watching, onQueuedRun])

  // 排队步结束 → 驱动计划继续推进
  useEffect(() => {
    if (!watching?.run_id || !stream.closed || busy) return
    if (stream.status === null) return
    setBusy(true)
    continuePlan(runId, watching.run_id)
      .then((next) => {
        setRun(next)
        onChanged?.()
        setCotEpoch((prev) => prev + 1) // 重开 CoT 流收执行期的观察
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setBusy(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.closed, watching?.run_id])

  if (error && !run) {
    return <p className="text-danger text-xs">{error}</p>
  }
  if (!run) {
    return <p className="text-faint text-xs">计划加载中…</p>
  }

  const act = async (action: () => Promise<AgentRun>) => {
    setBusy(true)
    setError(null)
    try {
      const next = await action()
      setRun(next)
      onChanged?.()
      setCotEpoch((prev) => prev + 1) // 重开 CoT 流，收执行期的观察
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const hasFailed = run.plan.some((step) => step.status === 'failed')

  return (
    <div className="border-line rounded-control border px-2.5 py-2 text-xs">
      <div className="mb-1.5 flex items-center gap-1.5">
        <StatusTag status={run.status} />
        {run.error && <span className="text-danger">{run.error}</span>}
      </div>

      <CoTStream
        items={cot.items}
        closed={cot.closed}
        defaultOpen={run.status === 'planning'}
      />

      {run.reply && <p className="text-muted mt-1.5 mb-1.5">{run.reply}</p>}

      {run.plan.length > 0 && (
        <ol className="m-0 list-none space-y-1 p-0">
          {run.plan.map((step) => (
            <StepRow key={step.id} step={step} />
          ))}
        </ol>
      )}

      <div className="mt-2 flex gap-1.5">
        {run.status === 'awaiting_confirm' && (
          <>
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              loading={busy}
              onClick={() => act(() => confirmPlan(run.id))}
            >
              确认执行
            </Button>
            <Button
              size="small"
              icon={<CloseOutlined />}
              disabled={busy}
              onClick={() => act(() => cancelPlan(run.id))}
            >
              取消
            </Button>
          </>
        )}
        {run.status === 'failed' && hasFailed && (
          <Button
            size="small"
            icon={<RedoOutlined />}
            loading={busy}
            onClick={() => act(() => retryPlan(run.id))}
          >
            重试失败步骤
          </Button>
        )}
        {(run.status === 'running' || run.status === 'awaiting_confirm') && (
          <Button size="small" type="text" disabled={busy} onClick={() => act(() => cancelPlan(run.id))}>
            取消后续
          </Button>
        )}
        <Button
          size="small"
          type="text"
          icon={<FileSearchOutlined />}
          onClick={() => setTraceOpen(true)}
        >
          轨迹
        </Button>
      </div>

      {error && <p className="text-danger mt-1.5 mb-0">{error}</p>}

      <TraceModal runId={run.id} open={traceOpen} onClose={() => setTraceOpen(false)} />
    </div>
  )
}

function StepRow({ step }: { step: PlanStep }) {
  return (
    <li className="flex items-start gap-1.5">
      <StepDot status={step.status} />
      <div className="min-w-0 flex-1">
        <span className={step.status === 'canceled' ? 'text-faint' : ''}>{step.tool}</span>
        {step.message && (
          <p className="text-muted m-0 text-[11px] leading-snug">{step.message}</p>
        )}
      </div>
    </li>
  )
}

function StepDot({ status }: { status: PlanStep['status'] }) {
  const color =
    status === 'succeeded'
      ? 'bg-success'
      : status === 'failed'
        ? 'bg-danger'
        : status === 'canceled'
          ? 'bg-line'
          : 'bg-brand animate-pulse'
  return <span className={`mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full ${color}`} />
}

function StatusTag({ status }: { status: AgentRun['status'] }) {
  const label: Record<AgentRun['status'], string> = {
    planning: '规划中',
    awaiting_confirm: '待确认',
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  const color: Record<AgentRun['status'], string> = {
    planning: 'processing',
    awaiting_confirm: 'gold',
    running: 'processing',
    succeeded: 'success',
    failed: 'error',
    cancelled: 'default',
  }
  return (
    <Tag bordered={false} color={color[status]} className="m-0">
      {label[status]}
    </Tag>
  )
}
