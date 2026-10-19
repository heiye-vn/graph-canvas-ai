/**
 * 编辑记录 —— 紧凑历史撤销时间线（对齐参考图1标准）。
 *
 * 两端对齐排版，操作名居左，序号/状态居右。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Tooltip } from 'antd'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'

import { getHistory, redoStep, undoStep } from '@/api/history'
import type { SessionOut } from '@/api/sessions'

export default function HistoryPanel({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient()

  const history = useQuery({
    queryKey: ['history', sessionId],
    queryFn: () => getHistory(sessionId),
    retry: false,
  })

  function adopt(result: {
    session: SessionOut
    can_undo: boolean
    can_redo: boolean
    seq: number
  }) {
    queryClient.setQueryData(['session', sessionId], result.session)
    queryClient.setQueryData(['history', sessionId], (prev: unknown) => ({
      seq: result.seq,
      can_undo: result.can_undo,
      can_redo: result.can_redo,
      items: (prev as { items?: unknown[] } | undefined)?.items ?? [],
    }))
    void queryClient.invalidateQueries({ queryKey: ['history', sessionId] })
  }

  const undo = useMutation({
    mutationFn: () => undoStep(sessionId),
    onSuccess: adopt,
  })

  const redo = useMutation({
    mutationFn: () => redoStep(sessionId),
    onSuccess: adopt,
  })

  const state = history.data
  const items = state?.items ?? []

  return (
    <div className="select-none text-xs">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-slate-600 font-medium">编辑记录</span>
        <div className="flex items-center gap-1">
          <Tooltip title={state?.can_undo ? '撤销 (Ctrl+Z)' : '无撤销项'}>
            <Button
              size="small"
              type="text"
              icon={<UndoOutlined className="text-xs" />}
              disabled={!state?.can_undo}
              loading={undo.isPending}
              onClick={() => undo.mutate()}
              className="h-6! w-6! text-slate-500 hover:text-slate-800"
              aria-label="撤销"
            />
          </Tooltip>
          <Tooltip title={state?.can_redo ? '重做 (Ctrl+Y)' : '无重选项'}>
            <Button
              size="small"
              type="text"
              icon={<RedoOutlined className="text-xs" />}
              disabled={!state?.can_redo}
              loading={redo.isPending}
              onClick={() => redo.mutate()}
              className="h-6! w-6! text-slate-500 hover:text-slate-800"
              aria-label="重做"
            />
          </Tooltip>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="text-slate-400 m-0 py-1.5 text-[11px]">暂无操作记录</p>
      ) : (
        <div className="space-y-1 max-h-48 overflow-y-auto pr-0.5">
          {items.map((entry) => {
            const current = entry.seq === state?.seq
            const undone = entry.seq > (state?.seq ?? 0)

            return (
              <div
                key={entry.seq}
                className={`flex items-center justify-between py-1 px-1.5 rounded transition-colors ${
                  current
                    ? 'bg-blue-50/80 text-blue-900 font-medium'
                    : undone
                      ? 'text-slate-400 opacity-60'
                      : 'text-slate-600 hover:bg-slate-50'
                }`}
              >
                <span className={`truncate text-xs ${undone ? 'line-through' : ''}`}>
                  {entry.label}
                </span>
                <span className="font-mono text-[10px] text-slate-400 tabular-nums shrink-0 ml-2">
                  #{entry.seq}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

