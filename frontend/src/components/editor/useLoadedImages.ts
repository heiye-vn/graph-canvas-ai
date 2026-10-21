/** 按素材路径复用已解码图片，失败后允许新签名和手动 reload 真正重试。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type ImageMap = Record<string, HTMLImageElement>
interface CachedImage {
  image: HTMLImageElement
  path: string
}
const pathOf = (url: string) => url.split('?')[0]

function loadImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const attempt = (retry: boolean) => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      const fail = () => {
        if (retry) window.setTimeout(() => attempt(false), 400)
        else resolve(null)
      }
      img.onload = () => {
        void img.decode().then(() => resolve(img), fail)
      }
      img.onerror = fail
      img.src = url
    }
    attempt(true)
  })
}

export function useLoadedImages(urls: Record<string, string>): {
  images: ImageMap
  pending: boolean
  failed: string[]
  reload: () => void
} {
  const [loaded, setLoaded] = useState<ImageMap>({})
  const [failures, setFailures] = useState<Record<string, string>>({})
  const [nonce, setNonce] = useState(0)
  const cacheRef = useRef<Record<string, CachedImage>>({})
  // 签名变化需要重试失败项；成功项仍按路径命中缓存，不重复下载。
  const signature = useMemo(() => JSON.stringify(Object.entries(urls).sort()), [urls])

  useEffect(() => {
    let cancelled = false
    const entries: Array<[string, string]> = JSON.parse(signature)
    const ready: ImageMap = {}
    const todo: Array<[string, string]> = []
    for (const [assetId, url] of entries) {
      const cached = cacheRef.current[assetId]
      if (cached?.path === pathOf(url)) ready[assetId] = cached.image
      else todo.push([assetId, url])
    }
    setLoaded(ready)
    setFailures({})
    void Promise.all(todo.map(async ([assetId, url]) => {
      const image = await loadImage(url)
      return { assetId, url, image }
    })).then((results) => {
      if (cancelled) return
      const next = { ...ready }
      const missing: Record<string, string> = {}
      for (const { assetId, url, image } of results) {
        if (image) {
          cacheRef.current[assetId] = { image, path: pathOf(url) }
          next[assetId] = image
        } else missing[assetId] = url
      }
      setLoaded(next)
      setFailures(missing)
    })
    return () => { cancelled = true }
  }, [signature, nonce])

  const reload = useCallback(() => setNonce((value) => value + 1), [])
  // 按当前引用计算，不能拿旧文档的图片数量判断新文档是否就绪。
  const images: ImageMap = {}
  const failed: string[] = []
  let pending = false
  for (const [assetId, url] of Object.entries(urls)) {
    if (loaded[assetId] && cacheRef.current[assetId]?.path === pathOf(url)) {
      images[assetId] = loaded[assetId]
    } else if (failures[assetId] === url) failed.push(assetId)
    else pending = true
  }
  return { images, pending, failed, reload }
}
