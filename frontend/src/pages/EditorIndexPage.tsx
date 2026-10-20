/**
 * 编辑入口页。
 *
 * session id 必须在 URL 上（`/editor/{id}`），所以 `/editor` 这一层是
 * 会话中心（项目工程列表），支持打开、重命名、删除历史会话。
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Empty, Input, Modal, Popconfirm, Result, Skeleton, Tag, message } from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  ProjectOutlined,
} from '@ant-design/icons'

import { deleteSession, listSessions, renameSession, type SessionSummary } from '@/api/sessions'
import EmptyIllustration from '@/components/EmptyIllustration'
import PageHeader from '@/components/PageHeader'

export default function EditorIndexPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['sessions'],
    queryFn: listSessions,
    refetchOnMount: 'always',
  })

  // 重命名弹窗状态
  const [editingItem, setEditingItem] = useState<SessionSummary | null>(null)
  const [newTitle, setNewTitle] = useState('')

  // 删除会话
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSession(id),
    onSuccess: () => {
      message.success('编辑会话已删除')
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (err: Error) => {
      message.error(`删除失败: ${err.message}`)
    },
  })

  // 重命名会话
  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameSession(id, title),
    onSuccess: () => {
      message.success('已修改会话名称')
      setEditingItem(null)
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (err: Error) => {
      message.error(`修改失败: ${err.message}`)
    },
  })

  const handleStartRename = (item: SessionSummary) => {
    setEditingItem(item)
    setNewTitle(item.title)
  }

  const handleConfirmRename = () => {
    if (!editingItem) return
    const trimmed = newTitle.trim()
    if (!trimmed) {
      message.warning('会话名称不能为空')
      return
    }
    renameMutation.mutate({ id: editingItem.id, title: trimmed })
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <PageHeader
        title="编辑工作区"
        description="管理与继续您的 AI 多图层编辑项目，支持图层调整、局部重绘与扩展合成。"
        extra={
          <Link to="/create">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              className="bg-blue-600 hover:bg-blue-700 h-9 px-4 font-medium shadow-xs"
            >
              新建创作
            </Button>
          </Link>
        }
      />

      {isLoading && (
        <div className="bg-white rounded-xl border border-slate-200/80 p-6 shadow-2xs space-y-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      )}

      {isError && (
        <div className="bg-white rounded-xl border border-slate-200/80 p-8 shadow-2xs">
          <Result status="error" title="会话列表加载失败" subTitle="请检查网络或后端服务状态" />
        </div>
      )}

      {data &&
        (data.length === 0 ? (
          <div className="bg-white rounded-xl border border-slate-200/80 p-12 text-center shadow-2xs">
            <Empty
              image={<EmptyIllustration className="mx-auto h-20" />}
              description="暂无编辑会话。您可以去创作新图，或在素材库挑选图片进入编辑工作台。"
            >
              <div className="flex justify-center gap-3 mt-4">
                <Link to="/create">
                  <Button type="primary" className="bg-blue-600">
                    立即去生图
                  </Button>
                </Link>
                <Link to="/assets">
                  <Button>去素材库挑选</Button>
                </Link>
              </div>
            </Empty>
          </div>
        ) : (
          <div className="space-y-3">
            {data.map((item) => (
              <div
                key={item.id}
                onClick={() => navigate(`/editor/${item.id}`)}
                className="group flex items-center justify-between gap-4 p-4 rounded-xl border border-slate-200/80 bg-white hover:border-blue-300 hover:shadow-xs transition-all cursor-pointer"
              >
                {/* 左侧图标与会话信息 */}
                <div className="flex items-center gap-3.5 min-w-0 flex-1">
                  <div className="size-11 rounded-lg bg-blue-50 border border-blue-100/80 flex items-center justify-center text-blue-600 shrink-0 group-hover:scale-105 transition-transform">
                    <ProjectOutlined className="text-xl" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold text-slate-900 truncate m-0 group-hover:text-blue-600 transition-colors">
                        {item.title || '未命名编辑会话'}
                      </h3>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleStartRename(item)
                        }}
                        title="重命名会话"
                        className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-blue-600 p-1 rounded transition-opacity cursor-pointer"
                      >
                        <EditOutlined className="text-xs" />
                      </button>
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-slate-400">
                      <Tag bordered={false} className="m-0 bg-slate-100 text-slate-600 text-[11px] px-1.5 py-0 leading-5">
                        {item.layer_count} 图层
                      </Tag>
                      <span>{item.asset_count} 素材</span>
                      <span>·</span>
                      <span>更新于 {new Date(item.updated_at).toLocaleString('zh-CN')}</span>
                    </div>
                  </div>
                </div>

                {/* 右侧动作按钮区 */}
                <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                  <Popconfirm
                    title="删除编辑会话"
                    description="确定要删除该编辑工程吗？画布内容及撤销记录将不可恢复。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true, size: 'small' }}
                    cancelButtonProps={{ size: 'small' }}
                    onConfirm={() => deleteMutation.mutate(item.id)}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      size="small"
                      className="text-slate-400 hover:text-red-500 hover:bg-red-50"
                      title="删除会话"
                    />
                  </Popconfirm>

                  <Link to={`/editor/${item.id}`}>
                    <Button
                      type="primary"
                      icon={<FolderOpenOutlined />}
                      size="small"
                      className="bg-blue-600 hover:bg-blue-700 font-medium px-3 text-xs"
                    >
                      打开
                    </Button>
                  </Link>
                </div>
              </div>
            ))}
          </div>
        ))}

      {/* 重命名模态框 */}
      <Modal
        title="重命名编辑会话"
        open={Boolean(editingItem)}
        onOk={handleConfirmRename}
        onCancel={() => setEditingItem(null)}
        confirmLoading={renameMutation.isPending}
        okText="保存"
        cancelText="取消"
      >
        <div className="py-2">
          <Input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onPressEnter={handleConfirmRename}
            placeholder="请输入会话名称"
            maxLength={60}
            showCount
            autoFocus
          />
        </div>
      </Modal>
    </div>
  )
}
