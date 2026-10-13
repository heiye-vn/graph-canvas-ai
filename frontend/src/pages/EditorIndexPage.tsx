/**
 * 编辑入口页。
 *
 * session id 必须在 URL 上（`/editor/{id}`），所以 `/editor` 这一层只能是
 * 「选一个会话」。做成列表而不是「恢复最近一次」：后者一旦恢复错会话，
 * 用户会以为自己的改动丢了。
 */

import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button, Empty, List, Result, Skeleton, Spin, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { listSessions } from '@/api/sessions'
import PageHeader from '@/components/PageHeader'

export default function EditorIndexPage() {
  const { data, isLoading, isError } = useQuery({ queryKey: ['sessions'], queryFn: listSessions })

  return (
    <div className="mx-auto w-full max-w-4xl px-8 py-8">
      <PageHeader
        title="编辑工作区"
        description="打开一个已有会话，或从素材 / 候选图新建一个。"
        extra={
          <Link to="/create">
            <Button type="primary" icon={<PlusOutlined />}>
              新建创作
            </Button>
          </Link>
        }
      />

      {isLoading && <Skeleton active paragraph={{ rows: 5 }} />}
      {isError && <Result status="error" title="会话列表加载失败" />}

      {data &&
        (data.length === 0 ? (
          <Empty description="还没有编辑会话。去素材库挑一张图，或从候选图继续。">
            <div className="flex justify-center gap-2">
              <Link to="/assets">
                <Button type="primary">去素材库</Button>
              </Link>
              <Link to="/create">
                <Button>去创作</Button>
              </Link>
            </div>
          </Empty>
        ) : (
          <List
            dataSource={data}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Link key="open" to={`/editor/${item.id}`}>
                    <Button type="primary">打开</Button>
                  </Link>,
                ]}
              >
                <List.Item.Meta
                  title={<span className="text-ink text-sm">{item.title}</span>}
                  description={
                    <span className="text-faint inline-flex items-center gap-2 text-xs">
                      <Tag bordered={false} className="m-0">
                        {item.layer_count} 图层
                      </Tag>
                      {item.asset_count} 素材
                      {` · 更新于 ${new Date(item.updated_at).toLocaleString('zh-CN')}`}
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        ))}

      {!isLoading && !isError && !data && <Spin />}
    </div>
  )
}
