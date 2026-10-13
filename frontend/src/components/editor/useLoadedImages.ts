/**
 * 把一批预签名 URL 变成 Konva 能画的 HTMLImageElement。
 *
 * 为什么必须自己加载：Konva 的 `<Image>` 要的是 DOM 图片对象而不是 URL，
 * 而且**跨域要注意设 crossOrigin** —— 不加的话画布一旦导出 JSON/PNG 就会
 * 被浏览器标成 tainted，导出直接失败。
 */

import { useEffect, useState } from 'react'

export type ImageMap = Record<string, HTMLImageElement>

export function useLoadedImages(urls: Record<string, string>): {
  images: ImageMap
  pending: boolean
} {
  const [images, setImages] = useState<ImageMap>({})

  useEffect(() => {
    let cancelled = false
    const entries = Object.entries(urls)
    if (entries.length === 0) {
      setImages({})
      return
    }

    const loaders = entries.map(
      ([assetId, url]) =>
        new Promise<[string, HTMLImageElement | null]>((resolve) => {
          const img = new Image()
          img.crossOrigin = 'anonymous'
          img.onload = () => resolve([assetId, img])
          img.onerror = () => resolve([assetId, null]) // 单张失败不让整个画布崩
          img.src = url
        }),
    )

    void Promise.all(loaders).then((loaded) => {
      if (cancelled) return
      const next: ImageMap = {}
      for (const [assetId, img] of loaded) {
        if (img) next[assetId] = img
      }
      setImages(next)
    })

    return () => {
      cancelled = true
    }
  }, [urls])

  const wanted = Object.keys(urls).length
  return { images, pending: Object.keys(images).length < wanted }
}
