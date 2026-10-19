/**
 * 工具面板 —— 动态参数表单卡片。
 *
 * 当顶栏或外部选中工具时自适应展示表单，未选中时保持克制，避免破坏工作台的信息层级。
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Input, InputNumber, Select, Switch, Tooltip } from 'antd'
import { CloseOutlined, LockOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons'

import { invokeTool, listTools } from '@/api/tools'
import type { ToolParamMeta } from '@/api/tools'

export default function ToolPanel({
  sessionId,
  selected = null,
  onSelect,
  onQueuedRun,
}: {
  sessionId: string
  selected?: string | null
  onSelect?: (name: string) => void
  onQueuedRun?: (runId: string, tool: string) => void
}) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['tools'], queryFn: listTools })

  const [localName, setLocalName] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})

  const toolName = selected ?? localName

  const tool = useMemo(
    () => data?.items.find((item) => item.name === toolName) ?? null,
    [data, toolName],
  )

  const visibleParams = useMemo(
    () => (tool?.params ?? []).filter((param) => !param.agent_hidden),
    [tool],
  )

  const invoke = useMutation({
    mutationFn: () => invokeTool(tool!.name, sessionId, values),
    onSuccess: (result) => {
      queryClient.setQueryData(['session', sessionId], result.session)
      void queryClient.invalidateQueries({ queryKey: ['history', sessionId] })
      if (result.run_id) onQueuedRun?.(result.run_id, result.tool)
    },
  })

  if (isLoading) return null
  if (!data || data.items.length === 0) return null

  if (!tool) {
    return (
      <div className="rounded-md border border-slate-200/80 bg-slate-50/50 p-2 text-xs text-slate-500 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-slate-500">
          <ToolOutlined />
          <span>更多高级工具</span>
        </span>
        <Select<string>
          size="small"
          className="w-32"
          placeholder="选择工具…"
          value={undefined}
          onChange={(value: string) => {
            setLocalName(value)
            setValues({})
            onSelect?.(value)
          }}
          options={data.items.map((item) => ({
            value: item.name,
            label: item.label,
          }))}
        />

      </div>
    )
  }

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/20 p-2.5 text-xs shadow-2xs space-y-2.5">
      <div className="flex items-center justify-between border-b border-blue-100 pb-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-slate-800">{tool.label}</span>
          <span className="text-[10px] text-slate-400 font-mono">({tool.name})</span>
        </div>
        <button
          type="button"
          onClick={() => {
            setLocalName(null)
            onSelect?.('')
          }}
          className="text-slate-400 hover:text-slate-600 cursor-pointer"
        >
          <CloseOutlined className="text-[10px]" />
        </button>
      </div>

      {visibleParams.length === 0 ? (
        <p className="text-slate-400 m-0 text-[11px] leading-relaxed">
          该工具无需输入参数
          {tool.name.startsWith('erase_') || tool.name === 'replace_region'
            ? '，执行时将直接作用于当前选区。'
            : '，点击执行即可。'}
        </p>
      ) : (
        visibleParams.map((param) => (
          <ParamField
            key={param.name}
            param={param}
            value={values[param.name] ?? param.default ?? undefined}
            onChange={(value) => setValues((prev) => ({ ...prev, [param.name]: value }))}
          />
        ))
      )}

      <Button
        block
        type="primary"
        size="small"
        icon={<ThunderboltOutlined />}
        loading={invoke.isPending}
        onClick={() => invoke.mutate()}
        className="h-7! text-xs! font-medium rounded!"
      >
        执行 {tool.label}
      </Button>

      {invoke.data && <p className="text-emerald-600 text-xs m-0">{invoke.data.message}</p>}
      {invoke.isError && (
        <p className="text-red-500 text-xs m-0">{(invoke.error as Error).message}</p>
      )}
    </div>
  )
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
  return (
    <label className="block">
      <span className="text-slate-600 mb-1 flex items-center gap-1 text-xs font-medium">
        {param.label}
        {param.required && <span className="text-red-500">*</span>}
        {param.agent_hidden && (
          <Tooltip title="模型不可见的内部字段">
            <LockOutlined className="text-slate-400 text-[10px]" />
          </Tooltip>
        )}
      </span>

      <FieldControl param={param} value={value} onChange={onChange} />

      {param.description && (
        <span className="text-slate-400 mt-0.5 block text-[10px] leading-tight">
          {param.description}
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
        size="small"
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
        size="small"
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
      size="small"
      value={(value as string) ?? ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={param.required ? '必填' : '可留空'}
    />
  )
}


