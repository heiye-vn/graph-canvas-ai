/**
 * 顶栏快捷工具条 —— 高频工具一键直达。
 *
 * 与 ToolPanel 的分工：这里是**入口**（点一下选中该工具），
 * 参数表单仍然只有一份（右侧 ToolPanel），自动跟着选中项切换。
 * 「入口平铺 + 表单单份」而不是「每个按钮各弹一个表单」，
 * 是因为两份表单迟早会对不上。
 *
 * 工具清单依旧**全部来自 /api/tools**：这里只决定「怎么摆」
 （按 group 分组、分组间用竖线隔开），不决定「有哪些」。
 */

import { useMemo } from 'react'
import { Button, Tooltip } from 'antd'

import type { ToolMeta } from '@/api/tools'

export default function QuickToolbar({
  tools,
  selected,
  onSelect,
}: {
  tools: ToolMeta[]
  selected: string | null
  onSelect: (name: string) => void
}) {
  const groups = useMemo(() => {
    const map = new Map<string, ToolMeta[]>()
    for (const tool of tools) {
      const list = map.get(tool.group) ?? []
      list.push(tool)
      map.set(tool.group, list)
    }
    return [...map.entries()]
  }, [tools])

  if (tools.length === 0) return null

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1">
      {groups.map(([group, items], groupIndex) => (
        <div key={group} className="flex items-center gap-1">
          {groupIndex > 0 && <span className="border-line mx-1 h-4 border-l" aria-hidden />}
          <span className="text-faint px-0.5 text-[11px]">{group}</span>
          {items.map((tool) => (
            <Tooltip key={tool.name} title={tool.description}>
              <Button
                size="small"
                type={selected === tool.name ? 'primary' : 'text'}
                onClick={() => onSelect(tool.name)}
              >
                {tool.label}
              </Button>
            </Tooltip>
          ))}
        </div>
      ))}
    </div>
  )
}
