/**
 * 全局后台生成任务悬浮挂件。
 *
 * 当用户在后台有正在进行的文生图任务、并切换到了其他页面（如素材库、编辑工作台或创作页输入区）时，
 * 此组件在屏幕右下角保持常驻，提供实时进度、阶段提示与一键切回候选页能力。
 */

import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ArrowRightOutlined,
  CheckCircleFilled,
  CloseOutlined,
  DownOutlined,
  LoadingOutlined,
  UpOutlined,
} from '@ant-design/icons'
import { Button, message, Progress } from 'antd'

import { useTaskStore } from '@/stores/taskStore'
import { useRunStream } from '@/hooks/useRunStream'
import { isTerminalStatus, STATUS_LABEL } from '@/domain/events'

export default function GlobalTaskFloating() {
  const navigate = useNavigate()
  const location = useLocation()
  const { activeTask, minimized, setMinimized, clearActiveTask } = useTaskStore()

  // 处于当前任务的候选页面时隐藏浮窗，避免与页面主体进度卡片重叠
  const isOnCandidatePage =
    Boolean(activeTask?.runId) &&
    location.pathname === `/candidates/${activeTask?.runId}`

  const stream = useRunStream(activeTask?.runId ?? null)
  const prevStatusRef = useRef<string | null>(null)

  useEffect(() => {
    if (!activeTask?.runId) return

    // 当任务从进行中变为成功时，发出全局轻量提醒
    if (
      stream.status === 'succeeded' &&
      prevStatusRef.current &&
      prevStatusRef.current !== 'succeeded'
    ) {
      message.success('AI 图像生成已完成！点击浮窗即可查看结果')
    }
    prevStatusRef.current = stream.status
  }, [stream.status, activeTask?.runId])

  if (!activeTask || isOnCandidatePage) {
    return null
  }

  const status = stream.status ?? 'queued'
  const isFinished = isTerminalStatus(status)
  const isSuccess = status === 'succeeded'
  const isFailed = status === 'failed' || status === 'cancelled'
  const progressPercent = Math.min(100, Math.max(stream.progress, status === 'queued' ? 5 : 10))

  const handleOpenCandidates = () => {
    navigate(`/candidates/${activeTask.runId}`)
  }

  // 最小化胶囊状态
  if (minimized) {
    return (
      <div className="fixed bottom-6 right-6 z-50 animate-in fade-in slide-in-from-bottom-2 duration-200">
        <button
          type="button"
          onClick={() => setMinimized(false)}
          className="flex items-center gap-2.5 rounded-full border border-blue-200/80 bg-white/95 px-3.5 py-2 text-xs font-medium text-slate-700 shadow-lg backdrop-blur-md transition-all hover:border-blue-400 hover:shadow-xl cursor-pointer"
        >
          {isSuccess ? (
            <CheckCircleFilled className="text-emerald-500 text-sm" />
          ) : isFailed ? (
            <span className="inline-block size-2 rounded-full bg-red-500" />
          ) : (
            <LoadingOutlined className="text-blue-600 text-sm" />
          )}
          <span className="max-w-[120px] truncate">{activeTask.prompt || '生成任务'}</span>
          <span className="font-semibold text-blue-600">
            {isSuccess ? '已完成' : `${progressPercent}%`}
          </span>
          <UpOutlined className="text-[10px] text-slate-400" />
        </button>
      </div>
    )
  }

  // 展开的现代任务卡片
  return (
    <div className="fixed bottom-6 right-6 z-50 w-80 rounded-xl border border-slate-200/90 bg-white/95 p-4 shadow-xl backdrop-blur-md animate-in fade-in slide-in-from-bottom-3 duration-200">
      {/* 头部标题与控制栏 */}
      <div className="flex items-center justify-between pb-2 border-b border-slate-100">
        <div className="flex items-center gap-2">
          {isSuccess ? (
            <CheckCircleFilled className="text-emerald-500 text-sm" />
          ) : isFailed ? (
            <span className="size-2 rounded-full bg-red-500" />
          ) : (
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-blue-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-blue-600" />
            </span>
          )}
          <span className="text-xs font-semibold text-slate-800">
            {isSuccess ? '生成完成' : isFailed ? '生成未成功' : '后台生成中'}
          </span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 font-mono">
            {STATUS_LABEL[status] ?? status}
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setMinimized(true)}
            title="最小化"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors cursor-pointer"
          >
            <DownOutlined className="text-[10px]" />
          </button>
          <button
            type="button"
            onClick={clearActiveTask}
            title="关闭浮窗"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors cursor-pointer"
          >
            <CloseOutlined className="text-[10px]" />
          </button>
        </div>
      </div>

      {/* 任务内容与进度 */}
      <div className="pt-3">
        <p className="text-xs text-slate-600 line-clamp-2 m-0 mb-2 leading-relaxed">
          {activeTask.prompt}
        </p>

        <div className="mb-2">
          <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
            <span>{stream.stage || (status === 'queued' ? '排队分配资源中…' : '正在渲染画面…')}</span>
            <span className="font-semibold text-slate-700">{progressPercent}%</span>
          </div>
          <Progress
            percent={progressPercent}
            showInfo={false}
            status={isFailed ? 'exception' : isSuccess ? 'success' : 'active'}
            strokeColor={isSuccess ? '#10b981' : isFailed ? '#ef4444' : '#2563eb'}
            className="m-0! p-0!"
            size={['100%', 5]}
          />
        </div>

        {/* 候选图片略缩预览（产出时立即展示） */}
        {stream.candidates.length > 0 && (
          <div className="flex items-center gap-1.5 py-1.5 overflow-x-auto">
            {stream.candidates.map((c) => (
              <img
                key={c.assetId}
                src={c.url}
                alt=""
                className="size-8 rounded object-cover border border-slate-200"
              />
            ))}
          </div>
        )}

        {/* 底部前往操作 */}
        <div className="mt-3 flex items-center justify-between pt-2 border-t border-slate-100">
          <span className="text-[10px] text-slate-400">
            {isFinished ? '产物已就绪' : '切页面不影响进度'}
          </span>
          <Button
            size="small"
            type="primary"
            onClick={handleOpenCandidates}
            className="h-7! text-xs! rounded-md shadow-xs flex items-center gap-1"
          >
            <span>{isSuccess ? '查看候选图' : '查看实时进度'}</span>
            <ArrowRightOutlined className="text-[10px]" />
          </Button>
        </div>
      </div>
    </div>
  )
}
