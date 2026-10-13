/**
 * 素材库：全量素材的管理页（列表 + 删除）。
 *
 * 上传入口不在这里 —— 它在创作页，那里才是「一次创作的起点」。这里只放一个跳转，
 * 避免同一份上传 UI 在两处各维护一遍。
 */

import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Empty, Spin } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { deleteAsset, listAssets } from '@/api/assets'
import AssetCard from '@/components/AssetCard'
import { APP_TAGLINE } from '@/lib/brand'
import PageHeader from '@/components/PageHeader'

export default function AssetsPage() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({ queryKey: ['assets'], queryFn: listAssets })

  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  })

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <PageHeader
        title="素材库"
        description={`共 ${data?.items.length ?? 0} 张`}
        extra={
          <Link to="/create">
            <Button type="primary" icon={<PlusOutlined />}>
              上传或生成
            </Button>
          </Link>
        }
      />

      {isLoading ? (
        <div className="flex justify-center py-28">
          <Spin size="large" />
        </div>
      ) : data && data.items.length === 0 ? (
        <Empty description="还没有素材，先去创作页生成或上传一张。">
          <Link to="/create">
            <Button type="primary">去创作</Button>
          </Link>
        </Empty>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {data?.items.map((asset) => (
            <AssetCard key={asset.id} asset={asset} onDelete={() => remove.mutate(asset.id)} />
          ))}
        </div>
      )}

      <footer className="text-faint mt-12 text-center text-xs">{APP_TAGLINE}</footer>
    </div>
  )
}
