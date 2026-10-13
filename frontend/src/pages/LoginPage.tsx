import { useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { APP_BADGE, APP_NAME, APP_TAGLINE } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'

interface LoginLocationState {
  /** 从落地页输入完 prompt 被拦到登录页时，记下要去哪、带什么 */
  next?: string
  prompt?: string
}

export default function LoginPage() {
  const location = useLocation()
  const { user, loading, signIn, signUp } = useAuthStore()

  const next = (location.state as LoginLocationState | null)?.next ?? '/create'
  const carriedPrompt = (location.state as LoginLocationState | null)?.prompt

  // hooks 必须全部在任何提前 return 之前调用
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // bootstrap 还没跑完先不渲染表单，避免已登录用户看到登录页闪一下
  if (loading) {
    return (
      <div className="flex min-h-full items-center justify-center text-sm text-muted">加载中…</div>
    )
  }

  // 登录成功后 user 变化同样会走到这里 —— 导航只发生在这一处，prompt 不会丢。
  if (user) {
    return (
      <Navigate
        to={next}
        replace
        state={carriedPrompt ? { prompt: carriedPrompt } : undefined}
      />
    )
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'login') await signIn(email, password)
      else await signUp(email, password)
      // 不在这里 navigate：登录成功会让上面的 user 判定接管跳转（含 prompt 接力）
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
          <div className="bg-brand-soft mb-3 inline-flex h-10 w-10 items-center justify-center rounded-control">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
              <rect x="3.5" y="5" width="10" height="9" rx="1.5" stroke="var(--color-brand)" strokeWidth="1.6" />
              <rect x="9.5" y="10" width="11" height="9" rx="1.5" stroke="var(--color-brand)" strokeWidth="1.6" />
              <circle cx="15" cy="14.5" r="1.6" fill="var(--color-accent)" />
            </svg>
          </div>
          <h1 className="text-ink flex items-center gap-2 text-xl font-medium">
            {APP_NAME}
            <span className="bg-accent text-dark rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-wide">
              {APP_BADGE}
            </span>
          </h1>
          <p className="text-muted mt-1 text-sm">
            {mode === 'login' ? '登录后继续使用' : '创建账号开始使用'}
          </p>
        </div>

        <div className="bg-soft mb-5 grid grid-cols-2 gap-1 rounded-control p-1 text-sm">
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
                  ? 'bg-paper text-ink font-medium shadow-control'
                  : 'text-muted hover:text-ink'
              }`}
            >
              {m === 'login' ? '登录' : '注册'}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block">
            <span className="text-muted mb-1 block text-xs">邮箱</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="border-line bg-soft focus:border-brand text-ink w-full rounded-control border px-3 py-2 text-sm outline-none transition placeholder:text-faint"
            />
          </label>
          <label className="block">
            <span className="text-muted mb-1 block text-xs">密码</span>
            <input
              type="password"
              required
              minLength={mode === 'register' ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? '至少 8 位' : '输入密码'}
              className="border-line bg-soft focus:border-brand text-ink w-full rounded-control border px-3 py-2 text-sm outline-none transition placeholder:text-faint"
            />
          </label>

          {error && (
            <p className="bg-danger/10 text-danger rounded-control px-3 py-2 text-xs">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="bg-brand hover:bg-brand-strong w-full rounded-control px-3 py-2.5 text-sm font-medium text-white shadow-control transition disabled:opacity-50"
          >
            {submitting ? '处理中…' : mode === 'login' ? '登录' : '注册并登录'}
          </button>
        </form>

        <p className="text-faint mt-5 text-center text-xs">{APP_TAGLINE}</p>
      </div>
    </div>
  )
}
