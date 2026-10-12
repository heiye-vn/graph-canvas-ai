import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { deleteAsset, listAssets } from '@/api/assets'
import type { AssetOut } from '@/api/assets'
import { APP_BADGE, APP_NAME, APP_TAGLINE } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'
import { uploadAsset } from '@/domain/upload'

export default function HomePage() {
  const { user, signOut } = useAuthStore()
  const fileInput = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['assets'],
    queryFn: listAssets,
  })

  const upload = useMutation({
    mutationFn: (file: File) => uploadAsset(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  })

  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assets'] }),
  })

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    try {
      await upload.mutateAsync(file)
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
    } finally {
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-medium text-ink">
            素材库
            <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold tracking-wide text-dark">
              {APP_BADGE}
            </span>
          </h1>
          <p className="mt-1 text-xs text-faint">
            {APP_NAME} · {user?.email}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/create"
            className="rounded-control border border-line bg-paper px-3 py-1.5 text-xs text-ink shadow-control transition hover:border-brand"
          >
            生成图片
          </Link>
          <Link
            to="/editor"
            className="rounded-control border border-line bg-paper px-3 py-1.5 text-xs text-ink shadow-control transition hover:border-brand"
          >
            进入编辑器
          </Link>
          <button
            type="button"
            onClick={signOut}
            className="rounded-control px-3 py-1.5 text-xs text-muted transition hover:text-ink"
          >
            退出
          </button>
        </div>
      </header>

      <div className="mb-6 rounded-card border border-dashed border-line-strong bg-soft p-6 text-center">
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={onPick}
        />
        <button
          type="button"
          disabled={upload.isPending}
          onClick={() => fileInput.current?.click()}
          className="rounded-control bg-brand px-4 py-2 text-sm font-medium text-white shadow-control transition hover:bg-brand-strong disabled:opacity-50"
        >
          {upload.isPending ? '上传中…' : '选择图片上传'}
        </button>
        <p className="mt-2 text-xs text-faint">支持 PNG / JPEG / WebP，单张不超过 20MB</p>
        {error && (
          <p className="mx-auto mt-2 max-w-sm rounded-control bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </p>
        )}
      </div>

      {isLoading && <p className="text-sm text-muted">加载中…</p>}
      {data && data.items.length === 0 && (
        <p className="text-sm text-muted">还没有素材，先上传一张图。</p>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {data?.items.map((asset) => (
          <AssetCard key={asset.id} asset={asset} onDelete={() => remove.mutate(asset.id)} />
        ))}
      </div>

      <footer className="mt-12 text-center text-xs text-faint">{APP_TAGLINE}</footer>
    </div>
  )
}

function AssetCard({ asset, onDelete }: { asset: AssetOut; onDelete: () => void }) {
  return (
    <figure className="overflow-hidden rounded-card border border-line bg-paper shadow-card">
      <img src={asset.url} alt="" className="h-32 w-full object-cover" loading="lazy" />
      <figcaption className="flex items-center justify-between px-3 py-2 text-xs text-muted">
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
