/**
 * 创作页：一次创作的起点。
 *
 * 刻意把「生成」「上传」「历史素材」放在同一屏 —— 这三件事是同一次创作的三种入口，
 * 拆成多个页面会让用户在还没开始之前就先迷路。
 *
 * 提交后**立刻跳到 /candidates/{runId}**，进度不留在这一屏：
 * 候选页是可刷新、可分享的独立 URL，把链路留在上一页等于把「刷新一下全丢」
 * 的风险甩给用户。
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { deleteAsset, listAssets } from '@/api/assets'
import type { AssetOut } from '@/api/assets'
import { SIZE_PRESETS, createTextToImage } from '@/api/runs'
import type { RunOut } from '@/api/runs'
import ImageDropzone from '@/components/ImageDropzone'
import { uploadAsset } from '@/domain/upload'

const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp']

export default function CreatePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState<string>(SIZE_PRESETS[0].value)
  const [count, setCount] = useState(1)
  const [error, setError] = useState<string | null>(null)

  const assets = useQuery({ queryKey: ['assets'], queryFn: listAssets })
  const invalidateAssets = () => queryClient.invalidateQueries({ queryKey: ['assets'] })

  const generate = useMutation({
    mutationFn: () => createTextToImage({ prompt, size, n: count }),
    onSuccess: (run: RunOut) => {
      setError(null)
      setPrompt('')
      navigate(`/candidates/${run.id}`)
    },
    onError: (err: Error) => setError(err.message),
  })

  const upload = useMutation({
    mutationFn: (file: File) => uploadAsset(file),
    onSuccess: () => {
      setError(null)
      invalidateAssets()
    },
    onError: (err: Error) => setError(err.message),
  })

  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: invalidateAssets,
  })

  function onFile(file: File) {
    if (!ACCEPTED.includes(file.type)) {
      setError('只支持 PNG / JPEG / WebP')
      return
    }
    upload.mutate(file)
  }

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <header className="mb-8">
        <h1 className="text-ink text-2xl font-medium tracking-tight">创作</h1>
        <p className="text-muted mt-1 text-sm">描述画面生成，或上传一张已有的图继续加工。</p>
      </header>

      <section className="border-line bg-paper shadow-card rounded-card border p-5">
        <label htmlFor="prompt" className="text-muted block text-xs">
          描述你想要的画面
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="例如：白色背景上的透明玻璃精华瓶，柔和顶光，电商主图质感"
          className="border-line bg-soft focus:border-brand text-ink mt-2 w-full resize-none rounded-control border px-3 py-2 text-sm outline-none transition"
        />

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <span className="text-muted block text-xs">尺寸</span>
            <select
              value={size}
              onChange={(e) => setSize(e.target.value)}
              className="border-line bg-soft focus:border-brand text-ink mt-1 rounded-control border px-3 py-2 text-sm outline-none transition"
            >
              {SIZE_PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <span className="text-muted block text-xs">张数</span>
            <select
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="border-line bg-soft focus:border-brand text-ink mt-1 rounded-control border px-3 py-2 text-sm outline-none transition"
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n} 张
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            disabled={generate.isPending || prompt.trim().length === 0}
            onClick={() => generate.mutate()}
            className="bg-brand hover:bg-brand-strong rounded-control px-5 py-2 text-sm font-medium text-white shadow-control transition disabled:opacity-50"
          >
            {generate.isPending ? '提交中…' : '生成'}
          </button>
        </div>

        <p className="text-faint mt-3 text-xs">
          当前接入本地占位模型，出图会带 MOCK 标记 —— 用于验证链路，不是真实模型效果。
        </p>
      </section>

      {error && (
        <p className="bg-danger/10 text-danger mt-4 rounded-control px-4 py-3 text-sm">{error}</p>
      )}

      <section className="mt-10">
        <h2 className="text-muted mb-3 text-sm font-medium">上传已有图片</h2>
        <ImageDropzone onFile={onFile} disabled={upload.isPending} />
      </section>

      <section className="mt-10">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-muted text-sm font-medium">历史素材</h2>
          <Link to="/" className="text-brand hover:text-brand-strong text-xs transition">
            管理全部素材
          </Link>
        </div>

        {assets.isLoading && <p className="text-muted text-sm">加载中…</p>}
        {assets.data && assets.data.items.length === 0 && (
          <p className="text-faint text-sm">还没有素材，先生成一张或上传一张。</p>
        )}

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {assets.data?.items.slice(0, 8).map((asset) => (
            <AssetCard key={asset.id} asset={asset} onDelete={() => remove.mutate(asset.id)} />
          ))}
        </div>
      </section>
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
