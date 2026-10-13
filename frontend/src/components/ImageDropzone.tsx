/**
 * 图片拖拽上传区。
 *
 * 保留点击选择这条兜底路径：拖拽发现率低，只放拖拽会让人不知道怎么上传。
 */

import { useRef, useState } from 'react'

const ACCEPT = 'image/png,image/jpeg,image/webp'

export default function ImageDropzone({
  onFile,
  disabled = false,
}: {
  onFile: (file: File) => void
  disabled?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function pick(files: FileList | null) {
    const file = files?.[0]
    if (file) onFile(file)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (!disabled) pick(e.dataTransfer.files)
      }}
      className={`rounded-card border border-dashed p-8 text-center transition ${
        dragging ? 'border-brand bg-brand-soft' : 'border-line-strong bg-soft'
      } ${disabled ? 'opacity-60' : ''}`}
    >
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          pick(e.target.files)
          if (input.current) input.current.value = ''
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className="rounded-control bg-brand px-4 py-2 text-sm font-medium text-white shadow-control transition hover:bg-brand-strong disabled:opacity-50"
      >
        {disabled ? '上传中…' : '选择图片'}
      </button>
      <p className="text-faint mt-2 text-xs">或把图片拖到这里 · PNG / JPEG / WebP，单张不超过 20MB</p>
    </div>
  )
}
