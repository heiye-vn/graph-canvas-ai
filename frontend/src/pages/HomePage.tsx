/**
 * 素材库：全量素材的管理页（列表 + 删除）。
 *
 * 上传入口不在这里 —— 它在创作页，那里才是「一次创作的起点」。这里只放一个跳转，
 * 避免同一份上传 UI 在两处各维护一遍。
 */

import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { deleteAsset, listAssets } from '@/api/assets'
import type { AssetOut } from '@/api/assets'
import { APP_TAGLINE } from '@/lib/brand'

export default function HomePage() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({ queryKey: ['assets'], queryFn: listAssets })

  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  })

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-ink text-2xl font-medium tracking-tight">素材库</h1>
          <p className="text-muted mt-1 text-sm">共 {data?.items.length ?? 0} 张</p>
        </div>
        <Link
          to="/create"
          className="border-line bg-paper hover:border-brand rounded-control border px-3 py-1.5 text-xs text-ink shadow-control transition"
        >
          上传或生成
        </Link>
      </header>

      {isLoading && <p className="text-muted text-sm">加载中…</p>}
      {data && data.items.length === 0 && (
        <p className="text-faint text-sm">还没有素材，先去创作页生成或上传一张。</p>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {data?.items.map((asset) => (
          <AssetCard key={asset.id} asset={asset} onDelete={() => remove.mutate(asset.id)} />
        ))}
      </div>

      <footer className="text-faint mt-12 text-center text-xs">{APP_TAGLINE}</footer>
    </div>
  )
}

function AssetCard({ asset, onDelete }: { asset: AssetOut; onDelete: () => void }) {
  return (
    <figure className="border-line bg-paper shadow-card overflow-hidden rounded-card border">
      <img src={asset.url} alt="" className="h-32 w-full object-cover" loading="lazy" />
      <figcaption className="text-muted flex items-center justify-between px-3 py-2 text-xs">
        <span className="font-mono">
          {asset.width}×{asset.height}
        </span>
        <button type="button" onClick={onDelete} className="text-danger transition hover:opacity-70">
          删除
        </button>
      </figcaption>
    </figure>
  )
}
