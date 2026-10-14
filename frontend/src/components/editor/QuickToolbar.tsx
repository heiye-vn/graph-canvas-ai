/**
 * 顶栏快捷工具条 —— 高频工具一键直达。
 *
 * 与 ToolPanel 的分工：这里是**入口**（点一下选中该工具），
 * 参数表单仍然只有一份（右侧 ToolPanel），自动跟着选中项切换。
 *
 * 16 个工具全平铺会把顶栏挤成两行（上一版截图的问题），
 * 所以规则是：**注册表前 8 个平铺，其余收进「更多」下拉**（按 group 分组展示）。
 * 这个 8 是展示策略不是工具身份，增删工具仍然不用改前端。
 *
 * 刻意不放分组文字标签：分组信息挪进下拉的 group 标题和按钮 tooltip，
 * 顶栏每个像素都要为「可点的工具」服务。
 */

import { useMemo } from 'react'
import { Button, Dropdown, Tooltip } from 'antd'
import { DownOutlined } from '@ant-design/icons'

import type { ToolMeta } from '@/api/tools'

const FLAT_LIMIT = 8

export default function QuickToolbar({
  tools,
  selected,
  onSelect,
}: {
  tools: ToolMeta[]
  selected: string | null
  onSelect: (name: string) => void
}) {
  // 注册顺序即展示顺序：builtins 里相邻注册的工具天然同组
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
    <div className="flex flex-nowrap items-center gap-0.5">
      {flat.map((tool) => {
        const divider = previousGroup !== null && tool.group !== previousGroup
        previousGroup = tool.group
        return (
          <div key={tool.name} className="flex shrink-0 items-center gap-0.5">
            {divider && <span className="bg-line mx-1 h-4 w-px" aria-hidden />}
            <Tooltip title={tool.description}>
              <Button
                size="small"
                type={selected === tool.name ? 'primary' : 'text'}
                onClick={() => onSelect(tool.name)}
              >
                {tool.label}
              </Button>
            </Tooltip>
          </div>
        )
      })}

      {rest.length > 0 && (
        <Dropdown menu={moreMenu} trigger={['click']} placement="bottomRight">
          <Button size="small" type="text" icon={<DownOutlined />}>
            更多
          </Button>
        </Dropdown>
      )}
    </div>
  )
}
