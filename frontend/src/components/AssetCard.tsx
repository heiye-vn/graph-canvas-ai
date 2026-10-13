/**
 * 素材卡 —— 创作页历史素材 / 素材库 / 候选页共用一份。
 *
 * 之前三个页面各写了一版 figure：圆角、图高、说明文字三处各调一遍，
 * 改一处必然漏两处。收进来之后页面间的差异只剩右下角那一颗按钮。
 *
 * `AssetOut` 天然满足 `AssetCardAsset`；候选页里「SSE 刚推过来、REST 还没刷到」
 * 的增量候选构造一个最小对象即可，不必先落库。
 *
 * `onDelete` 不传就不给删除入口 —— 候选页可以被分享出去，
 * 让点开链接的人顺手删掉原作者的素材是不合适的。
 */

import { Button, Card, Popconfirm, Tag, Tooltip } from 'antd'
import { DeleteOutlined, EditOutlined, ExportOutlined } from '@ant-design/icons'

export interface AssetCardAsset {
  id: string
  url: string
  width: number | null
  height: number | null
}

export default function AssetCard({
  asset,
  onDelete,
  onEdit,
  pending = false,
}: {
  asset: AssetCardAsset
  onDelete?: () => void
  /** 传了才出现「编辑」入口：用它这素材开一个编辑会话 */
  onEdit?: () => void
  /** 推流刚到还没进库的候选：只打「刚刚生成」，不给多余操作 */
  pending?: boolean
}) {
  const dimension =
    asset.width && asset.height ? `${asset.width}×${asset.height}` : '尺寸未知'

  return (
    <Card
      size="small"
      hoverable
      variant="outlined"
      classNames={{ body: 'px-3! py-2.5!' }}
      cover={<img src={asset.url} alt="" className="h-36 w-full object-cover" loading="lazy" />}
      actions={onEdit ? [<EditButton key="edit" onEdit={onEdit} />] : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        {pending ? (
          <Tag bordered={false} color="processing" className="m-0">
            刚刚生成
          </Tag>
        ) : (
          <span className="text-muted font-mono text-xs">{dimension}</span>
        )}

        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            type="link"
            size="small"
            href={asset.url}
            target="_blank"
            rel="noreferrer"
            icon={<ExportOutlined />}
          >
            查看原图
          </Button>

          {onDelete && (
            <Popconfirm
              title="删除这张素材？"
              description="删除后不可恢复。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={onDelete}
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label="删除素材"
              />
            </Popconfirm>
          )}
        </div>
      </div>
    </Card>
  )
}

function EditButton({ onEdit }: { onEdit: () => void }) {
  return (
    <Tooltip title="用它新建一个编辑会话">
      <Button type="text" icon={<EditOutlined />} onClick={onEdit} aria-label="编辑这张素材" />
    </Tooltip>
  )
}
