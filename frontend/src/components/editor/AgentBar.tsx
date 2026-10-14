/**
 * 一句话指令条（Agent 单步入口）。
 *
 * 结果刻意**逐步展示**：用户发了一句指令，想知道的就是「它到底做了什么」。
 * 只回一个新文档等于让他自己 diff 两张图。
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Input, List, Tag } from 'antd'
import { SendOutlined } from '@ant-design/icons'

import { agentStep } from '@/api/tools'
import type { StepResult } from '@/api/tools'

export default function AgentBar({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient()
  const [instruction, setInstruction] = useState('')
  const [steps, setSteps] = useState<StepResult[] | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const run = useMutation({
    mutationFn: () => agentStep(sessionId, instruction.trim()),
    onSuccess: (outcome) => {
      setSteps(outcome.steps)
      setNote(outcome.note)
      queryClient.setQueryData(['session', sessionId], outcome.session)
      // 模型这条链路同样写历史 —— 撤销面板要跟着长出来，
      // 否则用户会以为「自动帮我做的那些退不回去」
      void queryClient.invalidateQueries({ queryKey: ['history', sessionId] })
      setInstruction('')
    },
  })

  return (
    <div>
      <div className="flex gap-2">
        <Input
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onPressEnter={() => instruction.trim() && run.mutate()}
          placeholder="用一句话说要改什么，例如：把图变亮一点、隐藏文字层"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          loading={run.isPending}
          disabled={instruction.trim().length === 0}
          onClick={() => run.mutate()}
        >
          执行
        </Button>
      </div>

      {run.isError && (
        <Alert
          className="mt-3"
          type="error"
          showIcon
          message={(run.error as Error).message}
        />
      )}

      {note && <p className="text-faint mt-3 text-xs">{note}</p>}

      {steps && steps.length > 0 && (
        <List
          className="mt-3"
          size="small"
          dataSource={steps}
          renderItem={(step, index) => (
            <List.Item key={`${step.tool}-${index}`}>
              <span className="flex items-center gap-2 text-sm">
                <Tag bordered={false} color={step.ok ? 'success' : 'error'} className="m-0">
                  {step.tool}
                </Tag>
                {step.message}
                {step.ok && !step.changed && (
                  <Tag bordered={false} className="m-0">
                    画布未变
                  </Tag>
                )}
              </span>
            </List.Item>
          )}
        />
      )}
    </div>
  )
}
