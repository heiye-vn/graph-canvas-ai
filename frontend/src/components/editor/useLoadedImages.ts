/**
 * 把一批预签名 URL 变成 Konva 能画的 HTMLImageElement。
 *
 * 为什么必须自己加载：Konva 的 `<Image>` 要的是 DOM 图片对象而不是 URL，
 * 而且**跨域要注意设 crossOrigin** —— 不加的话画布一旦导出 JSON/PNG 就会
 * 被浏览器标成 tainted，导出直接失败。
 *
 * 三条与「图层凭空消失」直接相关的约定（M7 拆层踩过的坑）：
 *   1. **解码完成才算加载好**。onload 只代表字节到了，大图（3072×4096）
 *      首次 drawImage 仍可能是空帧 —— Konva 只在属性变化时重绘一次，
 *      那一帧画空，这一层就永远不出现了。
 *   2. **失败要重试一次**。预签名 URL 是短命资源，超时/5xx 常常下一次就通；
 *      一次失败就丢掉等于让图层静默消失。
 *   3. **同一素材不因签名换新而重下**。每次会话 refetch 都会生成新的
 *      预签名 URL（query 变了、path 没变），照 URL 去重会把 6MB 的底图
 *      反复拉一遍 —— 既慢又给失败制造机会。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type ImageMap = Record<string, HTMLImageElement>

interface CachedImage {
  image: HTMLImageElement
  /** 只在 path 变化（换素材）时失效，签名参数变化不算 */
  path: string
}

const pathOf = (url: string) => url.split('?')[0]

/** 一次加载：onload 后再 decode，失败重试一次。 */
function loadImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'

    let attempts = 0
    const retryOrGiveUp = () => {
      attempts += 1
      if (attempts > 1) {
        resolve(null)
        return
      }
      window.setTimeout(() => {
        img.src = url
      }, 400)
    }

    img.onload = () => {
      // decode 失败也把图交出去：宁可画一张可能没解码完的图，也不要整层消失
      void img
        .decode()
        .catch(() => undefined)
        .then(() => resolve(img))
    }
    img.onerror = retryOrGiveUp
    img.src = url
  })
}

export function useLoadedImages(urls: Record<string, string>): {
  images: ImageMap
  /** 还有图在下载/解码（失败的**不算**，否则会一直转圈） */
  pending: boolean
  /** 加载失败、当前没有可用图像的 asset_id */
  failed: string[]
  /** 手动重试失败的图（换新签名由调用方 invalidate 负责） */
  reload: () => void
} {
  const [images, setImages] = useState<ImageMap>({})
  const [failed, setFailed] = useState<string[]>([])
  const [nonce, setNonce] = useState(0)
  const cacheRef = useRef<Record<string, CachedImage>>({})

  // effect 只认「素材集合 + 路径」的签名：签名没变就不重下
  const signature = useMemo(
    () =>
      Object.entries(urls)
        .map(([id, url]) => `${id}|${pathOf(url)}`)
        .sort()
        .join(','),
    [urls],
  )
  const urlsRef = useRef(urls)
  urlsRef.current = urls

  useEffect(() => {
    let cancelled = false
    const entries = Object.entries(urlsRef.current)
    if (entries.length === 0) {
      setImages({})
      setFailed([])
      return
    }

    const ready: ImageMap = {}
    const todo: Array<[string, string]> = []
    for (const [assetId, url] of entries) {
      const cached = cacheRef.current[assetId]
      if (cached && cached.path === pathOf(url)) {
        ready[assetId] = cached.image
      } else {
        todo.push([assetId, url])
      }
    }

    // 先把已经有的图放上去：新素材还在路上时，旧图层不该跟着一起闪没
    if (Object.keys(ready).length > 0) setImages((prev) => ({ ...prev, ...ready }))

    if (todo.length === 0) {
      setImages(ready)
      setFailed([])
      return
    }

    void Promise.all(
      todo.map(async ([assetId, url]) => {
        const image = await loadImage(url)
        if (image) cacheRef.current[assetId] = { image, path: pathOf(url) }
        return [assetId, image] as const
      }),
    ).then((loaded) => {
      if (cancelled) return
      const next: ImageMap = { ...ready }
      const missing: string[] = []
      for (const [assetId, image] of loaded) {
        if (image) next[assetId] = image
        else missing.push(assetId)
      }
      setImages(next)
      setFailed(missing)
    })

    return () => {
      cancelled = true
    }
  }, [signature, nonce])

  const reload = useCallback(() => {
    // 只清失败的缓存项：已经加载好的图不该因为一次重试被重新下载
    for (const assetId of failed) delete cacheRef.current[assetId]
    setNonce((value) => value + 1)
  }, [failed])

  const wanted = Object.keys(urls).length
  const loadedCount = Object.keys(images).length
  return {
    images,
    pending: loadedCount < wanted - failed.length,
    failed,
    reload,
  }
}
