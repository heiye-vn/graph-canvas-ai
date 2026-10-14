/**
 * 撤销 / 重做。
 *
 * 两个开关不放在 PageHeader 的 extra 里而单独成一个件，是因为它们的可用性
 * 来自**服务端指针**而不是本地有没有改动：刷新之后能不能撤，得问服务端。
 *
 * 历史列表刻意只显示标签与位置 —— 快照是服务端的东西，
 * 前端要还原某一步就退到那一步，不必自己拼文档。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, List, Space, Tag, Tooltip } from 'antd'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'

import { getHistory, redoStep, undoStep } from '@/api/history'
import type { SessionOut } from '@/api/sessions'

export default function HistoryBar({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient()

  const history = useQuery({
    queryKey: ['history', sessionId],
    queryFn: () => getHistory(sessionId),
    retry: false,
  })

  function adopt(result: { session: SessionOut; can_undo: boolean; can_redo: boolean; seq: number }) {
    // 服务端返回的文档就是新的真相源，顺带把指针状态也一起吸收，
    // 省得为了更新按钮再发一轮 GET（连点的时候这个窗口很明显）
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
    <div className="border-line bg-paper shadow-card rounded-card mb-6 border p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-muted text-sm font-medium">编辑记录</h2>
        <Space size="small">
          <Tooltip title={state?.can_undo ? '撤销一步' : '已经退到最初状态'}>
            <Button
              size="small"
              icon={<UndoOutlined />}
              disabled={!state?.can_undo}
              loading={undo.isPending}
              onClick={() => undo.mutate()}
            >
              撤销
            </Button>
          </Tooltip>
          <Tooltip title={state?.can_redo ? '重做一步' : '没有可重做的步骤'}>
            <Button
              size="small"
              icon={<RedoOutlined />}
              disabled={!state?.can_redo}
              loading={redo.isPending}
              onClick={() => redo.mutate()}
            >
              重做
            </Button>
          </Tooltip>
        </Space>
      </div>

      {items.length === 0 ? (
        <p className="text-faint m-0 text-xs">还没有任何编辑动作</p>
      ) : (
        <List
          size="small"
          dataSource={items}
          renderItem={(entry) => {
            // 指针之后的条目还没发生（可重做），指针位置之前的已经撤过去了
            const current = entry.seq === state?.seq
            const undone = entry.seq > (state?.seq ?? 0)
            return (
              <List.Item className="py-1">
                <Space size="small">
                  <Tag bordered={false} color={current ? 'processing' : 'default'} className="m-0">
                    {entry.seq}
                  </Tag>
                  <span className={undone ? 'text-faint line-through' : ''}>{entry.label}</span>
                  {!entry.changed && (
                    <Tag bordered={false} color="default" className="m-0">
                      画布未变
                    </Tag>
                  )}
                </Space>
              </List.Item>
            )
          }}
        />
      )}
    </div>
  )
}
