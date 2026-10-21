/**
 * 素材库：生成结果与编辑产物的管理页。
 *
 * 素材表里其实混着三类东西：作品（image）、投放尺寸（export）、选区遮罩（mask）。
 * 后两者是**中间产物** —— 默认只看作品，需要时再切 Tab。否则一次导出物料就塞三张
 * 1080 系列、一次选区再多一张遮罩，找原图只能靠翻。
 *
 * 历史数据说明：本改动之前生成的投放尺寸都记成了 image，无法回溯区分，
 * 会继续留在「作品」里。
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Spin } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { deleteAsset, listAssets } from '@/api/assets'
import type { AssetOut } from '@/api/assets'
import AssetCard from '@/components/AssetCard'
import EmptyIllustration from '@/components/EmptyIllustration'
import { APP_TAGLINE } from '@/lib/brand'
import { useCreateSessionAndEdit } from '@/hooks/useCreateSession'

const FILTERS = [
  { key: 'image', label: '作品' },
  { key: 'export', label: '投放尺寸' },
  { key: 'mask', label: '选区遮罩' },
  { key: 'all', label: '全部' },
] as const

type FilterKey = (typeof FILTERS)[number]['key']

/** 只有 export / mask 是独立类型，其余一律算作品（含历史上写成 image 的导出图） */
function kindOf(asset: AssetOut): 'image' | 'export' | 'mask' {
  return asset.kind === 'export' || asset.kind === 'mask' ? asset.kind : 'image'
}

export default function AssetsPage() {
  const queryClient = useQueryClient()
  const openEditor = useCreateSessionAndEdit()
  const [filter, setFilter] = useState<FilterKey>('image')

  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['assets'], queryFn: listAssets })

  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  })

  const items = data?.items ?? []

  const counts = useMemo(() => {
    const result = { image: 0, export: 0, mask: 0, all: items.length }
    for (const item of items) result[kindOf(item)] += 1
    return result
  }, [items])

  const visible = useMemo(
    () => (filter === 'all' ? items : items.filter((item) => kindOf(item) === filter)),
    [items, filter],
  )

  const emptyHint =
    filter === 'export'
      ? '还没有导出过投放尺寸，去编辑器顶栏「导出 → 导出物料」生成。'
      : filter === 'mask'
        ? '还没有选区遮罩，在画布上用点选或笔刷选中区域后会自动保存。'
        : '去创作中心生成或上传一张图片开启您的首个会话。'

  return (
    <div className="mx-auto max-w-5xl px-3 py-6 sm:px-6 sm:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-6 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 m-0">素材库</h1>
            <span className="rounded-full bg-blue-50 text-blue-600 px-2 py-0.5 text-xs font-semibold font-mono">
              {items.length}
            </span>
          </div>
          <p className="text-xs text-slate-500 m-0 mt-1">
            浏览已生成的全量历史版本及上传素材，支持直接加载进多图层画布精修。
          </p>
        </div>

        <Link to="/create">
          <Button type="primary" icon={<PlusOutlined />} className="rounded-lg! h-8! text-xs! font-medium">
            创作新图像
          </Button>
        </Link>
      </div>

      {/* 来源筛选：默认「作品」，投放尺寸与遮罩收起来 */}
      <div className="mt-4 flex w-fit max-w-full flex-wrap items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-1">
        {FILTERS.map((item) => {
          const active = filter === item.key
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setFilter(item.key)}
              className={`flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors ${
                active
                  ? 'bg-slate-900 font-medium text-white'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
              }`}
            >
              {item.label}
              <span
                className={`font-mono text-[10px] tabular-nums ${
                  active ? 'text-white/70' : 'text-slate-400'
                }`}
              >
                {counts[item.key]}
              </span>
            </button>
          )
        })}
      </div>

      <div className="mt-5">
        {isLoading ? (
          <div className="flex justify-center py-24">
            <Spin size="large" />
          </div>
        ) : isError ? (
          <Alert type="error" showIcon message="素材库加载失败"
            description={error.message}
            action={<Button size="small" onClick={() => void refetch()}>重试</Button>}
          />
        ) : visible.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-12 text-center">
            <EmptyIllustration className="mx-auto mb-3 h-20" />
            <p className="text-sm font-medium text-slate-700 m-0">暂无素材资源</p>
            <p className="text-xs text-slate-400 m-0 mt-1 mb-4">{emptyHint}</p>
            {filter === 'image' && (
              <Link to="/create">
                <Button type="primary" size="small" className="rounded-md!">
                  去创作中心
                </Button>
              </Link>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {visible.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                onDelete={() => remove.mutate(asset.id)}
                // 遮罩不是图片，进不了画布
                onEdit={
                  kindOf(asset) === 'mask'
                    ? undefined
                    : () => openEditor.mutate({ asset_ids: [asset.id] })
                }
              />
            ))}
          </div>
        )}
      </div>

      <footer className="text-slate-400 mt-16 text-center text-xs font-mono">{APP_TAGLINE}</footer>
    </div>
  )
}
