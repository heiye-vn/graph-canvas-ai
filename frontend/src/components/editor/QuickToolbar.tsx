/**
 * 顶栏快捷工具条 —— 高频工具一键直达（对齐参考项目图1标准）。
 *
 * 紧凑微胶囊按钮排布，高密度信息架构。
 */

import { useMemo } from 'react'
import { Dropdown, Tooltip } from 'antd'
import {
  BgColorsOutlined,
  ClearOutlined,
  DownOutlined,
  ExpandOutlined,
  RotateRightOutlined,
  ScissorOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'

import type { ToolMeta } from '@/api/tools'

const FLAT_LIMIT = 9

/** 常用高频工具的图标映射，增强专业设计工具感 */
const TOOL_ICONS: Record<string, React.ReactNode> = {
  crop: <ScissorOutlined />,
  flip_horizontal: <SwapOutlined />,
  flip_vertical: <SwapOutlined className="rotate-90" />,
  rotate_layer: <RotateRightOutlined />,
  remove_background: <ClearOutlined />,
  expand_image: <ExpandOutlined />,
  super_resolution: <ThunderboltOutlined />,
  adjust_color: <BgColorsOutlined />,
}

export default function QuickToolbar({
  tools,
  selected,
  onSelect,
}: {
  tools: ToolMeta[]
  selected: string | null
  onSelect: (name: string) => void
}) {
  const flat = useMemo(() => tools.slice(0, FLAT_LIMIT), [tools])
  const rest = useMemo(() => tools.slice(FLAT_LIMIT), [tools])

  const moreMenu = useMemo(() => {
    const groups = new Map<string, ToolMeta[]>()
    for (const tool of rest) {
      const list = groups.get(tool.group) ?? []
      list.push(tool)
      groups.set(tool.group, list)
    }
    return {
      items: [...groups.entries()].map(([group, items]) => ({
        type: 'group' as const,
        label: group,
        children: items.map((tool) => ({ key: tool.name, label: tool.label })),
      })),
      onClick: ({ key }: { key: string }) => onSelect(key),
    }
  }, [rest, onSelect])

  if (tools.length === 0) return null

  let previousGroup: string | null = null

  return (
    <div className="flex flex-nowrap items-center gap-1 overflow-x-auto py-0.5 scrollbar-none">
      {flat.map((tool) => {
        const divider = previousGroup !== null && tool.group !== previousGroup
        previousGroup = tool.group
        const isSelected = selected === tool.name
        const icon = TOOL_ICONS[tool.name]

        return (
          <div key={tool.name} className="flex shrink-0 items-center gap-1">
            {divider && <span className="bg-slate-200 mx-1 h-3.5 w-px shrink-0" aria-hidden />}
            <Tooltip title={tool.description} mouseEnterDelay={0.4}>
              <button
                type="button"
                onClick={() => onSelect(tool.name)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-all duration-150 cursor-pointer shrink-0 border ${
                  isSelected
                    ? 'bg-blue-50 text-blue-600 border-blue-200 shadow-xs'
                    : 'bg-transparent text-slate-700 border-transparent hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                {icon && <span className="text-[11px] opacity-80">{icon}</span>}
                <span className="whitespace-nowrap">{tool.label}</span>
              </button>
            </Tooltip>
          </div>
        )
      })}

      {rest.length > 0 && (
        <Dropdown menu={moreMenu} trigger={['click']} placement="bottomRight">
          <button
            type="button"
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 border border-transparent transition-all cursor-pointer shrink-0"
          >
            <span>更多</span>
            <DownOutlined className="text-[9px]" />
          </button>
        </Dropdown>
      )}
    </div>
  )
}

