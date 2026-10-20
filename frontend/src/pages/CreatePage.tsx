/**
 * 创作页：对齐参考项目标准的高效创作工作流。
 * 包含：多比例/多数量文生图、商业灵感推荐、极简原生拖拽上传、生图历史任务卡片流（带删除与全量资产库链接）。
 */

import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Popconfirm, Spin } from 'antd'
import {
  DeleteOutlined,
  DownOutlined,
  InboxOutlined,
  PictureOutlined,
  ThunderboltOutlined,
  UpOutlined,
} from '@ant-design/icons'

import {
  SIZE_PRESETS,
  createTextToImage,
  deleteRun,
  listRunAssets,
  listRuns,
} from '@/api/runs'
import type { RunOut } from '@/api/runs'
import { useCreateSessionAndEdit } from '@/hooks/useCreateSession'
import { uploadAsset } from '@/domain/upload'

const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp']

/** 详尽高质量商业灵感提示词（包含景深、光影、材质、构图等电商/商业宣传关键词） */
const INSPIRATION_PRESETS = [
  {
    category: '3C 数码',
    tag: '科技降噪耳机',
    ratio: '1:1',
    size: '1024x1024',
    prompt:
      '未来科技感无线降噪耳机，黑色阳极氧化铝合金耳壳与哑光亲肤硅胶耳罩，悬浮在深色极简展台中央，深蓝色与冷紫色渐变科技氛围背光，侧面轮廓高光，超精细金属拉丝与微孔网格细节，商业广告静物摄影，8k 分辨率，大师级光影渲染',
  },
  {
    category: '轻奢美妆',
    tag: '透明精华安瓶',
    ratio: '4:5',
    size: '816x1020',
    prompt:
      '高端轻奢透明玻璃精华液安瓶，淡粉色微凝胶质地，瓶身折射晨光水波倒影，浅米白色大理石托盘，背景点缀柔和飞溅的水滴与湿润白色山茶花瓣，纯净透亮，柔光漫反射，高端时尚杂志大片，超微距特写',
  },
  {
    category: '北欧家居',
    tag: '白瓷香薰蜡烛',
    ratio: '3:4',
    size: '768x1024',
    prompt:
      '极简主义白瓷香薰蜡烛与木质扩香石，置于浅原木纹理长桌，左侧落地窗斜洒晨间温暖逆光，丁达尔漫射光束，背景微模糊米白色亚麻窗帘，温馨惬意静谧氛围，MUJI 侘寂美学摄影，胶片柔焦景深',
  },
  {
    category: '商业特调',
    tag: '拉花拿铁咖啡',
    ratio: '1:1',
    size: '1024x1024',
    prompt:
      '手工拉花拿铁咖啡，深烘焙细腻油脂泡沫与郁金香拉花，装在哑光墨绿色粗陶马克杯中，杯旁散落深褐色烘焙咖啡豆与肉桂棒，深木质复古桌面，侧面柔光摄影箱棚拍，热气升腾微烟雾感，暖调电影质感',
  },
  {
    category: '精密机械',
    tag: '陀飞轮镂空腕表',
    ratio: '16:9',
    size: '1024x576',
    prompt:
      '瑞士精密机械镂空腕表，蓝宝石镜面与精钢表壳，内部金色陀飞轮与齿轮运转微距特写，深色碳纤维纹理斜切背景，边缘带有锐利冷调切光，高反光金属折射，高端奢侈品海报级商业渲染',
  },
]

/** 格式化日期：例如 08/31 14:18 */
function formatRunTime(isoString?: string) {
  if (!isoString) return ''
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return ''
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const min = String(date.getMinutes()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:${min}`
}

/** 现代原生受控拖拽上传区域，消除任何第三方封装层级带来的样式错乱 */
function ImageDropzone({
  onFileSelected,
  isUploading,
}: {
  onFileSelected: (file: File) => void
  isUploading: boolean
}) {
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      onFileSelected(e.dataTransfer.files[0])
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setIsDragOver(true)
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      onClick={() => fileInputRef.current?.click()}
      className={`relative rounded-2xl border-2 border-dashed p-7 text-center transition-all cursor-pointer select-none ${
        isDragOver
          ? 'border-blue-500 bg-blue-50/40 shadow-xs'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/40'
      }`}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED.join(',')}
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files[0]) {
            onFileSelected(e.target.files[0])
          }
        }}
      />
      <div className="flex flex-col items-center justify-center">
        {isUploading ? (
          <Spin size="small" />
        ) : (
          <InboxOutlined className="text-2xl text-slate-400 mb-1" />
        )}
        <p className="text-slate-800 text-sm font-medium m-0 mt-1">
          拖入图片，或点击选择
        </p>
        <p className="text-slate-400 mt-1 text-xs m-0">
          JPG / PNG / WebP，单张不超过 20 MB
        </p>
      </div>
    </div>
  )
}

/** 单条生图历史任务卡片 */
function RunHistoryItem({
  run,
  onDeleted,
}: {
  run: RunOut
  onDeleted: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()
  const openEditor = useCreateSessionAndEdit()

  // 展开时才拉取该任务产出的候选图片列表
  const assetsQuery = useQuery({
    queryKey: ['run-assets', run.id],
    queryFn: () => listRunAssets(run.id),
    enabled: expanded,
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteRun(run.id),
    onSuccess: onDeleted,
  })

  const promptText = (run.params?.prompt as string) || '无提示词描述'
  const count =
    (run.result?.asset_ids as string[])?.length ||
    (run.params?.n as number) ||
    1
  const timeStr = formatRunTime(run.created_at)

  return (
    <div className="rounded-xl border border-slate-200/90 bg-white transition-all hover:border-slate-300 hover:shadow-2xs overflow-hidden">
      <div className="flex items-center justify-between p-3.5 gap-4 select-none">
        {/* 左侧可点击区域：封面、提示词与信息 */}
        <div
          className="flex items-center gap-3.5 min-w-0 flex-1 cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          {/* 封面缩略图 */}
          <div className="size-12 rounded-lg bg-slate-100 overflow-hidden shrink-0 border border-slate-200/60 flex items-center justify-center">
            {run.cover_url ? (
              <img src={run.cover_url} alt="" className="size-full object-cover" />
            ) : (
              <PictureOutlined className="text-slate-400 text-lg" />
            )}
          </div>
          {/* 提示词标题与元信息 */}
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-slate-900 truncate m-0 leading-snug">
              {promptText}
            </h3>
            <p className="text-xs text-slate-400 m-0 mt-1 flex items-center gap-1.5">
              <span>{count} 张</span>
              {timeStr && (
                <>
                  <span>·</span>
                  <span>{timeStr}</span>
                </>
              )}
            </p>
          </div>
        </div>

        {/* 右侧操作按钮组：阻止事件冒泡到展开逻辑 */}
        <div
          className="flex items-center gap-2 shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <Popconfirm
            title="删除历史任务"
            description="确定要删除这条生成历史记录吗？"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true, size: 'small' }}
            cancelButtonProps={{ size: 'small' }}
            onConfirm={(e) => {
              e?.stopPropagation()
              deleteMutation.mutate()
            }}
            onCancel={(e) => {
              e?.stopPropagation()
            }}
          >
            <button
              type="button"
              onClick={(e) => e.stopPropagation()}
              title="删除任务记录"
              className="text-slate-400 hover:text-red-500 p-1.5 rounded hover:bg-red-50 transition-colors cursor-pointer"
            >
              <DeleteOutlined className="text-xs" />
            </button>
          </Popconfirm>

          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setExpanded(!expanded)
            }}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            {expanded ? (
              <>
                <span>收起</span>
                <UpOutlined className="text-[10px]" />
              </>
            ) : (
              <>
                <span>展开</span>
                <DownOutlined className="text-[10px]" />
              </>
            )}
          </button>
        </div>
      </div>

      {/* 展开的候选图片网格 */}
      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50/60 p-4 pt-3.5">
          {assetsQuery.isLoading ? (
            <div className="flex justify-center py-4">
              <Spin size="small" />
            </div>
          ) : assetsQuery.data && assetsQuery.data.length > 0 ? (
            <div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {assetsQuery.data.map((asset) => (
                  <div
                    key={asset.id}
                    className="group relative rounded-lg border border-slate-200 bg-white overflow-hidden shadow-2xs"
                  >
                    <img src={asset.url} alt="" className="w-full aspect-square object-cover" />
                    <div className="absolute inset-0 bg-slate-900/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center p-2">
                      <Button
                        size="small"
                        type="primary"
                        onClick={(e) => {
                          e.stopPropagation()
                          openEditor.mutate({
                            asset_ids: [asset.id],
                            title: `编辑 · ${promptText.slice(0, 15)}...`,
                          })
                        }}
                        className="text-xs!"
                      >
                        编辑图层
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex justify-end">
                <Button
                  size="small"
                  type="link"
                  onClick={() => navigate(`/candidates/${run.id}`)}
                  className="text-xs text-blue-600 p-0 font-medium hover:text-blue-700"
                >
                  进入候选页全部精修 →
                </Button>
              </div>
            </div>
          ) : (
            <div className="py-2.5 text-center">
              <p className="text-xs text-slate-400 m-0">该任务生成的图片此前已在素材库中被删除</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function CreatePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState<string>(SIZE_PRESETS[0].value)
  const [count, setCount] = useState(1)
  const [error, setError] = useState<string | null>(null)

  // 历史任务列表：只查询文生图任务，且只取最近 5 条展示，保证页面紧凑利落
  const runs = useQuery({
    queryKey: ['runs', 'text_to_image'],
    queryFn: () => listRuns({ tool: 'text_to_image', limit: 5 }),
  })
  const invalidateRuns = () => {
    queryClient.invalidateQueries({ queryKey: ['runs'] })
    queryClient.invalidateQueries({ queryKey: ['assets'] })
  }

  const openEditor = useCreateSessionAndEdit()

  const generate = useMutation({
    mutationFn: () => createTextToImage({ prompt: prompt.trim(), size, n: count }),
    onSuccess: (run: RunOut) => {
      setError(null)
      setPrompt('')
      invalidateRuns()
      navigate(`/candidates/${run.id}`)
    },
    onError: (err: Error) => setError(err.message),
  })

  const upload = useMutation({
    mutationFn: (file: File) => uploadAsset(file),
    onSuccess: (asset) => {
      setError(null)
      invalidateRuns()
      // 上传成功后直接开启多图层精修会话
      openEditor.mutate({
        asset_ids: [asset.id],
        title: `编辑 · 上传素材`,
      })
    },
    onError: (err: Error) => setError(err.message),
  })

  const handleFileSelected = (file: File) => {
    if (!ACCEPTED.includes(file.type)) {
      setError('只支持 PNG / JPEG / WebP 格式图片')
      return
    }
    upload.mutate(file)
  }

  // 回车快捷键生成
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (prompt.trim().length > 0 && !generate.isPending) {
        generate.mutate()
      }
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* 极简大标题 */}
      <h1 className="text-2xl font-bold tracking-tight text-slate-900 mb-6 m-0">
        创作
      </h1>

      {/* 核心文生图卡片 */}
      <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs transition-all focus-within:border-slate-300 focus-within:shadow-sm">
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          placeholder="描述你想要的画面，例如：白色陶瓷马克杯放在浅木色桌面，晨光从左侧照入。回车生成，Shift+Enter 换行"
          className="w-full resize-none border-none bg-transparent p-0 text-sm text-slate-800 placeholder-slate-400 outline-none leading-relaxed"
        />

        {/* 商业灵感推荐栏 */}
        <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1 pt-2.5 border-t border-slate-100 scrollbar-none">
          <span className="flex items-center gap-1 text-[11px] font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded shrink-0">
            <ThunderboltOutlined className="text-xs" />
            灵感推荐
          </span>
          {INSPIRATION_PRESETS.map((item) => (
            <button
              key={item.tag}
              type="button"
              onClick={() => {
                setPrompt(item.prompt)
                setSize(item.size)
              }}
              title={`点击填入提示词并自选比例 ${item.ratio}:\n${item.prompt}`}
              className="shrink-0 flex items-center gap-1.5 text-xs text-slate-600 hover:text-blue-600 bg-slate-50 hover:bg-blue-50/60 border border-slate-200/80 hover:border-blue-200 px-2.5 py-1 rounded-md transition-all cursor-pointer group"
            >
              <span className="text-[10px] text-slate-400 group-hover:text-blue-400 font-mono">
                [{item.category}]
              </span>
              <span className="font-medium">{item.tag}</span>
              <span className="text-[10px] text-slate-400 font-mono bg-white px-1 rounded border border-slate-200/60">
                {item.ratio}
              </span>
            </button>
          ))}
        </div>

        {/* 底部内嵌设置工具栏 */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100">
          <div className="flex flex-wrap items-center gap-4">
            {/* 比例选择 */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-400 font-medium mr-1">比例</span>
              {SIZE_PRESETS.map((preset) => {
                const active = size === preset.value
                return (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => setSize(preset.value)}
                    className={`px-2.5 py-1 text-xs font-medium rounded transition-all cursor-pointer ${
                      active
                        ? 'bg-slate-900 text-white font-semibold shadow-2xs'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                    }`}
                  >
                    {preset.label}
                  </button>
                )
              })}
            </div>

            {/* 数量选择 */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-400 font-medium mr-1">数量</span>
              {[1, 2, 4].map((n) => {
                const active = count === n
                return (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setCount(n)}
                    className={`px-2 py-1 text-xs font-medium rounded text-center transition-all cursor-pointer min-w-6 ${
                      active
                        ? 'bg-slate-900 text-white font-semibold shadow-2xs'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                    }`}
                  >
                    {n}
                  </button>
                )
              })}
            </div>

            {/* 快捷键提示 */}
            <span className="text-[11px] text-slate-400 hidden sm:inline">
              回车生成 · Shift+Enter 换行
            </span>
          </div>

          {/* 生成按钮 */}
          <Button
            type="primary"
            size="middle"
            loading={generate.isPending}
            disabled={prompt.trim().length === 0}
            onClick={() => generate.mutate()}
            className="px-6! text-sm! font-medium rounded-lg bg-slate-800! hover:bg-slate-900! text-white! border-none! shadow-xs"
          >
            生成
          </Button>
        </div>
      </section>

      {error && (
        <Alert
          className="mt-4 rounded-lg"
          type="error"
          showIcon
          message={error}
          closable
          onClose={() => setError(null)}
        />
      )}

      {/* 上传区域：纯净原生拖拽与受控卡片，彻底避免任何样式遮挡 */}
      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold text-slate-800 m-0">
          上传已有图片
        </h2>
        <ImageDropzone
          onFileSelected={handleFileSelected}
          isUploading={upload.isPending}
        />
      </section>

      {/* 历史素材列表 */}
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-800 m-0">
              历史素材
            </h2>
            <span className="text-xs text-slate-400 font-normal">
              （最近生成任务）
            </span>
          </div>
          <Link
            to="/assets"
            className="text-xs text-blue-600 hover:text-blue-700 font-medium transition-colors"
          >
            查看全部素材库 →
          </Link>
        </div>

        {runs.isLoading ? (
          <div className="flex justify-center py-10">
            <Spin />
          </div>
        ) : runs.data && runs.data.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center text-xs text-slate-400">
            暂无文生图历史，在上方输入描述并生成第一组画面。
          </div>
        ) : (
          <div className="space-y-3">
            {runs.data?.map((run) => (
              <RunHistoryItem
                key={run.id}
                run={run}
                onDeleted={invalidateRuns}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}


