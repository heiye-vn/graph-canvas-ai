/**
 * 编辑记录（M5 撤销栈的 UI）。
 *
 * 两个开关的可用性来自**服务端指针**而不是本地有没有改动：刷新之后能不能撤，
 * 得问服务端。所以 can_undo / can_redo 必须跟着每次 undo/redo 的响应一起回来 ——
 * 前端如果为了显示按钮状态再发一次 GET，在快速连点时会出现
 * 「按钮可点但请求 409」的窗口。
 *
 * 历史列表刻意只显示标签与位置 —— 快照是服务端的东西，
 * 前端要还原某一步就退到那一步，不必自己拼文档。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, List, Tag, Tooltip } from 'antd'
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
    // 服务端返回的文档就是新的真相源，顺带把指针状态也一起吸收
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
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-muted m-0 text-xs font-medium">编辑记录</h3>
        <div className="flex gap-1">
          <Tooltip title={state?.can_undo ? '撤销一步' : '已经退到最初状态'}>
            <Button
              size="small"
              type="text"
              icon={<UndoOutlined />}
              disabled={!state?.can_undo}
              loading={undo.isPending}
              onClick={() => undo.mutate()}
              aria-label="撤销"
            />
          </Tooltip>
          <Tooltip title={state?.can_redo ? '重做一步' : '没有可重做的步骤'}>
            <Button
              size="small"
              type="text"
              icon={<RedoOutlined />}
              disabled={!state?.can_redo}
              loading={redo.isPending}
              onClick={() => redo.mutate()}
              aria-label="重做"
            />
          </Tooltip>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="text-faint m-0 text-xs">还没有任何编辑动作</p>
      ) : (
        <List
          size="small"
          split={false}
          dataSource={items}
          renderItem={(entry) => {
            // 指针之后的条目还没发生（可重做），指针位置之前的已经撤过去了
            const current = entry.seq === state?.seq
            const undone = entry.seq > (state?.seq ?? 0)
            return (
              <List.Item className="px-1! py-1!">
                <span className="flex min-w-0 items-center gap-1.5 text-xs">
                  <Tag
                    bordered={false}
                    color={current ? 'processing' : 'default'}
                    className="m-0 shrink-0"
                  >
                    {entry.seq}
                  </Tag>
                  <span className={`truncate ${undone ? 'text-faint line-through' : ''}`}>
                    {entry.label}
                  </span>
                </span>
              </List.Item>
            )
          }}
        />
      )}
    </div>
  )
}
