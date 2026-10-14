/**
 * 图层面板。
 *
 * 顺序注意：`topDown()` —— 面板从上到下是「视觉上的从上到下」，
 * 文档数组是反的（从下到上）。这条转换只允许在这一处发生。
 */

import { Button, List, Tag, Tooltip } from 'antd'
import {
  EyeInvisibleOutlined,
  EyeOutlined,
  FileImageOutlined,
  FontSizeOutlined,
  BorderOutlined,
  StarOutlined,
} from '@ant-design/icons'

import type { Layer, LayerDocument } from '@/domain/layerDoc'
import { topDown } from '@/domain/layerDoc'

const TYPE_ICON: Record<Layer['type'], React.ReactNode> = {
  image: <FileImageOutlined />,
  text: <FontSizeOutlined />,
  shape: <BorderOutlined />,
}

export default function LayerPanel({
  doc,
  onToggleVisible,
  onSwitchCurrent,
  onSelect,
  selectedId,
  busy = false,
}: {
  doc: LayerDocument
  onToggleVisible: (layerId: string, visible: boolean) => void
  onSwitchCurrent: (layerId: string) => void
  /** 点图层行 = 选中（变换面板的滑杆作用对象），不产生任何文档改动 */
  onSelect?: (layerId: string) => void
  selectedId?: string | null
  /** 有请求在飞：禁用按钮，避免同一步连点两次而多出一条历史 */
  busy?: boolean
}) {
  return (
    <List
      size="small"
      dataSource={topDown(doc)}
      locale={{ emptyText: '这个会话还没有图层' }}
      renderItem={(layer) => {
        const active = layer.id === doc.active_layer_id
        const selected = layer.id === selectedId
        return (
          <List.Item
            className={`rounded-control cursor-pointer transition-colors ${
              selected ? 'bg-brand-soft/60 ring-brand ring-1' : active ? 'bg-brand-soft' : ''
            }`}
            onClick={() => onSelect?.(layer.id)}
            actions={[
              <Tooltip key="visible" title={layer.visible ? '隐藏' : '显示'}>
                <Button
                  type="text"
                  size="small"
                  disabled={busy}
                  icon={layer.visible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                  onClick={() => onToggleVisible(layer.id, !layer.visible)}
                  aria-label={layer.visible ? '隐藏图层' : '显示图层'}
                />
              </Tooltip>,
            ]}
          >
            <List.Item.Meta
              avatar={<span className="text-brand text-base">{TYPE_ICON[layer.type]}</span>}
              title={
                <span className="flex items-center gap-2">
                  <span className={`truncate text-sm ${layer.visible ? '' : 'text-faint'}`}>
                    {layer.name}
                  </span>
                  {active && (
                    <Tag bordered={false} color="processing" className="m-0">
                      当前
                    </Tag>
                  )}
                </span>
              }
              description={
                <span className="text-faint text-xs">
                  {layer.type === 'image' ? '图像层' : layer.type === 'text' ? '文字层' : '形状层'}
                  {` · 不透明度 ${Math.round(layer.opacity * 100)}%`}
                </span>
              }
            />
            {layer.type === 'image' && layer.visible === false && (
              <Tooltip title="把它设为当前图（其余候选图隐藏）">
                <Button
                  type="link"
                  size="small"
                  disabled={busy}
                  icon={<StarOutlined />}
                  onClick={() => onSwitchCurrent(layer.id)}
                >
                  设为当前图
                </Button>
              </Tooltip>
            )}
          </List.Item>
        )
      }}
    />
  )
}
