/**
 * 素材库：全量素材的管理页（列表 + 批量管理 + 编辑入口）。
 */

import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Spin } from 'antd'
import { PictureOutlined, PlusOutlined } from '@ant-design/icons'

import { deleteAsset, listAssets } from '@/api/assets'
import AssetCard from '@/components/AssetCard'
import { APP_TAGLINE } from '@/lib/brand'
import { useCreateSessionAndEdit } from '@/hooks/useCreateSession'


export default function AssetsPage() {
  const queryClient = useQueryClient()
  const openEditor = useCreateSessionAndEdit()

  const { data, isLoading } = useQuery({ queryKey: ['assets'], queryFn: listAssets })

  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  })

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 select-none">
      <div className="flex items-center justify-between pb-6 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 m-0">素材库</h1>
            <span className="rounded-full bg-blue-50 text-blue-600 px-2 py-0.5 text-xs font-semibold font-mono">
              {data?.items.length ?? 0}
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

      <div className="mt-6">
        {isLoading ? (
          <div className="flex justify-center py-24">
            <Spin size="large" />
          </div>
        ) : data && data.items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-12 text-center">
            <div className="h-12 w-12 rounded-full bg-slate-100 text-slate-400 mx-auto flex items-center justify-center text-xl mb-3">
              <PictureOutlined />
            </div>
            <p className="text-sm font-medium text-slate-700 m-0">暂无素材资源</p>
            <p className="text-xs text-slate-400 m-0 mt-1 mb-4">去创作中心生成或上传一张图片开启您的首个会话。</p>
            <Link to="/create">
              <Button type="primary" size="small" className="rounded-md!">
                去创作中心
              </Button>
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {data?.items.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                onDelete={() => remove.mutate(asset.id)}
                onEdit={() => openEditor.mutate({ asset_ids: [asset.id] })}
              />
            ))}
          </div>
        )}
      </div>

      <footer className="text-slate-400 mt-16 text-center text-xs font-mono">{APP_TAGLINE}</footer>
    </div>
  )
}

