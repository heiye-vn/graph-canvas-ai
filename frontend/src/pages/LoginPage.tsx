import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { APP_BADGE, APP_NAME, APP_TAGLINE } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const { signIn, signUp } = useAuthStore()

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'login') await signIn(email, password)
      else await signUp(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-card border border-line bg-paper p-7 shadow-card">
        <div className="mb-6">
          <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-control bg-brand-soft">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
              <rect x="3.5" y="5" width="10" height="9" rx="1.5" stroke="var(--color-brand)" strokeWidth="1.6" />
              <rect x="9.5" y="10" width="11" height="9" rx="1.5" stroke="var(--color-brand)" strokeWidth="1.6" />
              <circle cx="15" cy="14.5" r="1.6" fill="var(--color-accent)" />
            </svg>
          </div>
          <h1 className="flex items-center gap-2 text-xl font-medium text-ink">
            {APP_NAME}
            <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold tracking-wide text-dark">
              {APP_BADGE}
            </span>
          </h1>
          <p className="mt-1 text-sm text-muted">
            {mode === 'login' ? '登录后继续使用' : '创建账号开始使用'}
          </p>
        </div>

        <div className="mb-5 grid grid-cols-2 gap-1 rounded-control bg-soft p-1 text-sm">
          {(['login', 'register'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m)
                setError(null)
              }}
              className={`rounded-control px-3 py-1.5 transition ${
                mode === m
                  ? 'bg-paper font-medium text-ink shadow-control'
                  : 'text-muted hover:text-ink'
              }`}
            >
              {m === 'login' ? '登录' : '注册'}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-muted">邮箱</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-control border border-line bg-soft px-3 py-2 text-sm text-ink outline-none transition placeholder:text-faint focus:border-brand"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">密码</span>
            <input
              type="password"
              required
              minLength={mode === 'register' ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? '至少 8 位' : '输入密码'}
              className="w-full rounded-control border border-line bg-soft px-3 py-2 text-sm text-ink outline-none transition placeholder:text-faint focus:border-brand"
            />
          </label>

          {error && (
            <p className="rounded-control bg-danger/10 px-3 py-2 text-xs text-danger">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-control bg-brand px-3 py-2.5 text-sm font-medium text-white shadow-control transition hover:bg-brand-strong disabled:opacity-50"
          >
            {submitting ? '处理中…' : mode === 'login' ? '登录' : '注册并登录'}
          </button>
        </form>

        <p className="mt-5 text-center text-xs text-faint">{APP_TAGLINE}</p>
      </div>
    </div>
  )
}
