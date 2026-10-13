/**
 * 登录 / 注册页。
 *
 * 布局刻意做成「页面级留白 + 一张大圆角卡片」：
 *   左上角「返回首页」承担导航，卡片里只留必须的元素（logo、大标题、两个字段、
 *   一个主按钮、一条切换入口）。不做 tab 切换器 —— 登录/注册的切换
 *   用底部一行文字链接就够，少一个控件少一分视觉负担。
 *
 * 主按钮用 dark 而不是 brand：页面上唯一的品牌色块留给 logo，
 * 按钮保持中性深色，和落地页 CTA 区分出层级。
 */

import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'

import { APP_BADGE, APP_NAME } from '@/lib/brand'
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
    <div className="flex min-h-full flex-col px-6 py-10">
      <div className="mx-auto w-full max-w-md">
        <Link
          to="/"
          className="text-muted hover:text-ink inline-flex items-center gap-2 text-sm transition"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" aria-hidden="true">
            <path
              d="M19 12H5m0 0 6-6m-6 6 6 6"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          返回首页
        </Link>

        <div className="bg-paper border-line rounded-panel mt-8 border p-8 shadow-lift sm:p-10">
          <div className="flex items-center gap-3">
            <span className="bg-dark grid size-10 shrink-0 place-items-center rounded-control">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
                <rect
                  x="3.5"
                  y="5"
                  width="10"
                  height="9"
                  rx="2"
                  stroke="var(--color-accent)"
                  strokeWidth="1.8"
                />
                <rect
                  x="9.5"
                  y="10"
                  width="11"
                  height="9"
                  rx="2"
                  stroke="#ffffff"
                  strokeWidth="1.8"
                />
              </svg>
            </span>
            <span className="text-ink flex items-center gap-1.5 text-base font-medium">
              {APP_NAME}
              <span className="bg-accent text-dark rounded-full px-1.5 py-0.5 text-[10px] font-semibold">
                {APP_BADGE}
              </span>
            </span>
          </div>

          <h1 className="text-ink mt-8 text-3xl font-semibold tracking-tight">
            {mode === 'login' ? '登录' : '创建账号'}
          </h1>

          <form onSubmit={onSubmit} className="mt-8 space-y-5">
            <label className="block">
              <span className="text-ink mb-2 block text-sm">邮箱</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                className="border-line-strong bg-paper text-ink focus:border-brand w-full rounded-control border px-4 py-3 text-sm outline-none transition placeholder:text-faint"
              />
            </label>

            <label className="block">
              <span className="text-ink mb-2 block text-sm">密码</span>
              <input
                type="password"
                required
                minLength={mode === 'register' ? 8 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === 'register' ? '至少 8 位' : '输入密码'}
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                className="border-line-strong bg-paper text-ink focus:border-brand w-full rounded-control border px-4 py-3 text-sm outline-none transition placeholder:text-faint"
              />
            </label>

            {error && (
              <p className="bg-danger/10 text-danger rounded-control px-3 py-2.5 text-xs">{error}</p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="bg-dark hover:bg-ink w-full rounded-control px-4 py-3.5 text-sm font-medium text-white transition disabled:opacity-50"
            >
              {submitting ? '处理中…' : mode === 'login' ? '登录' : '注册并进入'}
            </button>
          </form>

          <p className="text-muted mt-6 text-sm">
            {mode === 'login' ? '还没有账号？' : '已有账号？'}
            <button
              type="button"
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login')
                setError(null)
              }}
              className="text-ink ml-1 font-medium transition hover:opacity-70"
            >
              {mode === 'login' ? '注册' : '登录'}
            </button>
          </p>
        </div>

        <p className="text-faint mt-6 text-center text-xs">
          一句话，交付可上架的商品物料
        </p>
      </div>
    </div>
  )
}
