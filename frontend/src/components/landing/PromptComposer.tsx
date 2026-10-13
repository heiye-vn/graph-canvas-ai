/**
 * 首屏输入区。
 *
 * 提交后的行为分两种情况，目的都是**不让 prompt 白写一遍**：
 *   - 已登录：带着 prompt 直接落到创作页
 *   - 未登录：先去登录，登录页再把 prompt 接力送过去
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { EXAMPLE_PROMPTS } from '@/lib/marketing'
import { useAuthStore } from '@/stores/authStore'

export default function PromptComposer() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const [prompt, setPrompt] = useState('')

  function submit() {
    const value = prompt.trim()
    if (!value) return
    if (user) {
      navigate('/create', { state: { prompt: value } })
      return
    }
    navigate('/login', { state: { next: '/create', prompt: value } })
  }

  return (
    <div className="bg-paper border-line rounded-card border p-4 shadow-card">
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
        }}
        rows={3}
        placeholder="描述你要的画面，例如：磨砂玻璃精华瓶立在亚克力台上，柔和顶光，白底电商主图"
        className="border-line bg-soft focus:border-brand text-ink w-full resize-none rounded-control border px-3 py-2.5 text-sm leading-relaxed outline-none transition"
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={prompt.trim().length === 0}
          className="bg-brand hover:bg-brand-strong rounded-control px-4 py-2 text-sm font-medium text-white shadow-control transition disabled:opacity-50"
        >
          {user ? '去生成' : '登录后生成'}
        </button>
        <span className="text-faint text-xs">⌘/Ctrl + Enter 提交</span>
      </div>

      <div className="border-line mt-4 border-t pt-3">
        <p className="text-faint mb-2 text-xs">试试这些</p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_PROMPTS.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setPrompt(example)}
              className="border-line bg-soft hover:border-brand text-muted hover:text-ink rounded-full border px-3 py-1 text-xs transition"
            >
              {example.length > 22 ? `${example.slice(0, 22)}…` : example}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
