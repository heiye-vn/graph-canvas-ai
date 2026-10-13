/**
 * 创作页：一次创作的起点。
 *
 * 刻意把「生成」「上传」「历史素材」放在同一屏 —— 这三件事是同一次创作的三种入口，
 * 拆成多个页面会让用户在还没开始之前就先迷路。
 *
 * 提交后**立刻跳到 /candidates/{runId}**，进度不留在这一屏：
 * 候选页是可刷新、可分享的独立 URL，把链路留在上一页等于把「刷新一下全丢」
 * 的风险甩给用户。
 *
 * 控件统一走 antd：原生 select 的下拉面板是系统自绘的，和主题完全两个世界；
 * 这正是当初界面显得「拼凑」的最大单一来源。
 */

import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Input, Select, Spin, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'

import { deleteAsset, listAssets } from '@/api/assets'
import { SIZE_PRESETS, createTextToImage } from '@/api/runs'
import type { RunOut } from '@/api/runs'
import AssetCard from '@/components/AssetCard'
import PageHeader from '@/components/PageHeader'
import { uploadAsset } from '@/domain/upload'

const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp']

export default function CreatePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()

  // 落地页 →（可能经过登录页）→ 这里，prompt 一路带过来
  const carriedPrompt = (location.state as { prompt?: string } | null)?.prompt ?? ''
  const [prompt, setPrompt] = useState(carriedPrompt)
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

  const draggerProps: UploadProps = {
    accept: ACCEPTED.join(','),
    multiple: false,
    showUploadList: false,
    disabled: upload.isPending,
    // 返回 false = 不走 antd 的自动上传，文件交给我们自己的两段式上传域逻辑
    beforeUpload(file) {
      if (!ACCEPTED.includes(file.type)) {
        setError('只支持 PNG / JPEG / WebP')
        return Upload.LIST_IGNORE
      }
      upload.mutate(file)
      return false
    },
  }

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <PageHeader title="创作" description="描述画面生成，或上传一张已有的图继续加工。" />

      <section className="border-line bg-paper shadow-card rounded-card border p-5">
        <label htmlFor="prompt" className="text-muted block text-xs">
          描述你想要的画面
        </label>
        <Input.TextArea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="例如：白色背景上的透明玻璃精华瓶，柔和顶光，电商主图质感"
          className="mt-2!"
        />

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <span className="text-muted mb-1.5 block text-xs">尺寸</span>
            <Select
              value={size}
              onChange={setSize}
              options={SIZE_PRESETS.map((preset) => ({ value: preset.value, label: preset.label }))}
              className="w-36"
            />
          </div>

          <div>
            <span className="text-muted mb-1.5 block text-xs">张数</span>
            <Select
              value={count}
              onChange={setCount}
              options={[1, 2, 3, 4].map((n) => ({ value: n, label: `${n} 张` }))}
              className="w-28"
            />
          </div>

          <Button
            type="primary"
            loading={generate.isPending}
            disabled={prompt.trim().length === 0}
            onClick={() => generate.mutate()}
          >
            生成
          </Button>
        </div>

        <p className="text-faint mt-3 text-xs">
          当前接入本地占位模型，出图会带 MOCK 标记 —— 用于验证链路，不是真实模型效果。
        </p>
      </section>

      {error && (
        <Alert
          className="mt-4"
          type="error"
          showIcon
          message={error}
          closable
          onClose={() => setError(null)}
        />
      )}

      <section className="mt-10">
        <h2 className="text-muted mb-3 text-sm font-medium">上传已有图片</h2>
        <Upload.Dragger {...draggerProps} className="bg-soft!">
          <p className="text-brand text-3xl">
            <InboxOutlined />
          </p>
          <p className="text-ink text-sm">点击或把图片拖到这里</p>
          <p className="text-faint mt-1 text-xs">PNG / JPEG / WebP，单张不超过 20MB</p>
        </Upload.Dragger>
      </section>

      <section className="mt-10">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-muted text-sm font-medium">历史素材</h2>
          <Link to="/assets">
            <Button type="link" size="small">
              管理全部素材
            </Button>
          </Link>
        </div>

        {assets.isLoading ? (
          <div className="flex justify-center py-10">
            <Spin />
          </div>
        ) : assets.data && assets.data.items.length === 0 ? (
          <p className="text-faint text-sm">还没有素材，先生成一张或上传一张。</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {assets.data?.items.slice(0, 8).map((asset) => (
              <AssetCard key={asset.id} asset={asset} onDelete={() => remove.mutate(asset.id)} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
