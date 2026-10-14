/**
 * 工具面板。
 *
 * 表单是**按元数据渲染**的：字段类型、范围、默认值都来自 `/api/tools`。
 * 这里唯一的领域知识是「每种 JSON 类型该用哪个控件」——
 * 一旦开始为某个具体工具写分支（if tool === 'adjust_color'），
 * 就又回到了「加工具要改前端」的老路。
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Empty, Input, InputNumber, Select, Switch, Tooltip } from 'antd'
import { LockOutlined, ThunderboltOutlined } from '@ant-design/icons'

import { invokeTool, listTools } from '@/api/tools'
import type { ToolParamMeta } from '@/api/tools'

export default function ToolPanel({
  sessionId,
  selected = null,
  onSelect,
}: {
  sessionId: string
  /** 外部（快捷工具条）选中的工具；不传则用面板自己的下拉 */
  selected?: string | null
  onSelect?: (name: string) => void
}) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['tools'], queryFn: listTools })

  const [localName, setLocalName] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})

  // 受控优先：快捷工具条点了谁，这里就显示谁的表单
  const toolName = selected ?? localName

  const tool = useMemo(
    () => data?.items.find((item) => item.name === toolName) ?? null,
    [data, toolName],
  )

  const invoke = useMutation({
    mutationFn: () => invokeTool(tool!.name, sessionId, values),
    onSuccess: (result) => {
      queryClient.setQueryData(['session', sessionId], result.session)
      void queryClient.invalidateQueries({ queryKey: ['history', sessionId] })
    },
  })

  if (isLoading) return <Empty description="加载工具…" />
  if (!data || data.items.length === 0) return <Empty description="后端没有注册任何工具" />

  return (
    <div>
      <Select
        className="w-full"
        placeholder="选择一个工具"
        value={toolName}
        onChange={(value) => {
          setLocalName(value)
          setValues({})
          onSelect?.(value)
        }}
        options={data.items.map((item) => ({
          value: item.name,
          label: `${item.label} · ${item.description}`,
        }))}
      />

      {tool && (
        <div className="mt-4 space-y-3">
          {tool.params.map((param) => (
            <ParamField
              key={param.name}
              param={param}
              value={values[param.name] ?? param.default ?? undefined}
              onChange={(value) => setValues((prev) => ({ ...prev, [param.name]: value }))}
            />
          ))}

          <Button
            block
            icon={<ThunderboltOutlined />}
            loading={invoke.isPending}
            onClick={() => invoke.mutate()}
          >
            执行
          </Button>

          {invoke.data && <SuccessHint text={invoke.data.message} />}
          {invoke.isError && (
            <p className="text-danger text-xs">{(invoke.error as Error).message}</p>
          )}
        </div>
      )}
    </div>
  )
}

function SuccessHint({ text }: { text: string }) {
  return <p className="text-success text-xs">{text}</p>
}

function ParamField({
  param,
  value,
  onChange,
}: {
  param: ToolParamMeta
  value: unknown
  onChange: (value: unknown) => void
}) {
  const suffix = param.agent_hidden ? '（由界面选择，模型不可见）' : ''

  return (
    <label className="block">
      <span className="text-muted mb-1 flex items-center gap-1 text-xs">
        {param.label}
        {param.required && <span className="text-danger">*</span>}
        {param.agent_hidden && (
          <Tooltip title="这个字段不会出现在给模型的 schema 里，避免模型编造 id">
            {/* 图标一律走图标库：emoji 当图标在跨平台渲染里高度和基线都不可控 */}
            <LockOutlined className="text-faint" />
          </Tooltip>
        )}
      </span>

      <FieldControl param={param} value={value} onChange={onChange} />

      {param.description && (
        <span className="text-faint mt-1 block text-[11px]">
          {param.description}
          {suffix}
        </span>
      )}
    </label>
  )
}

function FieldControl({
  param,
  value,
  onChange,
}: {
  param: ToolParamMeta
  value: unknown
  onChange: (value: unknown) => void
}) {
  if (param.type === 'boolean') {
    return <Switch size="small" checked={Boolean(value)} onChange={onChange} />
  }

  if (param.type === 'enum' && param.enum) {
    return (
      <Select
        className="w-full"
        value={value as string}
        onChange={onChange}
        options={param.enum.map((option) => ({ value: option, label: String(option) }))}
      />
    )
  }

  if (param.type === 'number' || param.type === 'integer') {
    return (
      <InputNumber
        className="w-full"
        value={value as number | undefined}
        onChange={(next) => onChange(next)}
        min={param.min ?? undefined}
        max={param.max ?? undefined}
        precision={param.type === 'integer' ? 0 : undefined}
      />
    )
  }

  return (
    <Input
      value={(value as string) ?? ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={param.required ? '必填' : '可留空'}
    />
  )
}

