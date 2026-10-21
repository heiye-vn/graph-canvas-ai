/**
 * 登录 / 注册页。
 *
 * 布局刻意做成「页面级留白 + 一张大圆角卡片」：
 *   左上角「返回首页」承担导航，卡片里只留必须的元素（品牌标识、大标题、两个字段、
 *   一个主按钮、一条切换入口）。不做 tab 切换器 —— 登录/注册的切换
 *   用底部一行文字链接就够，少一个控件少一分视觉负担。
 *
 * 主按钮用深色而不是品牌色：卡片里唯一的品牌色块留给品牌标识，
 * 按钮保持中性深色，和落地页 CTA 区分出层级。深色主色是**局部覆盖**
 * （见下方包住提交按钮的 ConfigProvider），不动全局 token。
 *
 * 表单校验交给 antd Form 而不是原生 required：原生气泡是浏览器自绘的，
 * 样式不受主题控制，报错位置和文案也和组件库的其余部分对不齐。
 */

import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { Alert, Button, Form, Input } from 'antd'
import { ArrowLeftOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'

import BrandMark from '@/components/BrandMark'
import { APP_TAGLINE } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'


interface LoginLocationState {
  /** 从落地页输入完 prompt 被拦到登录页时，记下要去哪、带什么 */
  next?: string
  prompt?: string
  nextState?: unknown
}

interface LoginForm {
  email: string
  password: string
}

export default function LoginPage() {
  const location = useLocation()
  const { user, loading, signIn, signUp } = useAuthStore()

  const state = location.state as LoginLocationState | null
  const requestedNext = state?.next
  const next = typeof requestedNext === 'string'
    && /^\/(create|assets|candidates|editor|metrics)(?:[/?#]|$)/.test(requestedNext)
    && !requestedNext.includes('\\')
    ? requestedNext : '/create'
  const nextState = state?.nextState ?? (typeof state?.prompt === 'string' ? { prompt: state.prompt } : undefined)

  // hooks 必须全部在任何提前 return 之前调用
  const [form] = Form.useForm<LoginForm>()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // bootstrap 还没跑完先不渲染表单，避免已登录用户看到登录页闪一下
  if (loading) {
    return (
      <div className="flex min-h-full items-center justify-center">
        <span className="text-muted text-sm">加载中…</span>
      </div>
    )
  }

  // 登录成功后 user 变化同样会走到这里 —— 导航只发生在这一处，prompt 不会丢。
  if (user) {
    return (
      <Navigate to={next} replace state={nextState} />
    )
  }

  async function onSubmit(values: LoginForm) {
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'login') await signIn(values.email, values.password)
      else await signUp(values.email, values.password)
      // 不在这里 navigate：登录成功会让上面的 user 判定接管跳转（含 prompt 接力）
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  function toggleMode() {
    setMode(mode === 'login' ? 'register' : 'login')
    setError(null)
  }

  return (
    <div className="relative flex min-h-full flex-col justify-center overflow-hidden bg-slate-50 px-6 py-12">
      {/* 顶部品牌柔光：门面页别一片素灰 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.10),transparent_55%)]"
      />
      <div className="relative mx-auto w-full max-w-sm">
        <div className="mb-4">
          <Link to="/">
            <Button type="text" size="small" icon={<ArrowLeftOutlined />} className="text-slate-500 hover:text-slate-800">
              返回首页
            </Button>
          </Link>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 sm:p-8 shadow-md">
          <div className="flex justify-center mb-2">
            <BrandMark />
          </div>

          <h1 className="text-center text-xl font-bold tracking-tight text-slate-900 mt-4">
            {mode === 'login' ? '登录工作台' : '开启创作之旅'}
          </h1>
          <p className="text-center text-xs text-slate-500 mt-1 mb-6">
            多图层 AI 图像生成与微调平台
          </p>

          <Form
            form={form}
            size="middle"
            layout="vertical"
            requiredMark={false}
            onFinish={onSubmit}
          >
            <Form.Item
              name="email"
              label={<span className="text-xs font-medium text-slate-700">工作邮箱</span>}
              rules={[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '邮箱格式不正确' },
              ]}
              className="mb-3.5!"
            >
              <Input
                prefix={<MailOutlined className="text-slate-400 text-xs" />}
                placeholder="you@example.com"
                autoComplete="email"
                className="rounded-md!"
              />
            </Form.Item>

            <Form.Item
              name="password"
              label={<span className="text-xs font-medium text-slate-700">账号密码</span>}
              rules={[
                { required: true, message: '请输入密码' },
                ...(mode === 'register'
                  ? [{ min: 8, message: '密码至少 8 位' } as const]
                  : []),
              ]}
              className="mb-4!"
            >
              <Input.Password
                prefix={<LockOutlined className="text-slate-400 text-xs" />}
                placeholder={mode === 'register' ? '至少 8 位字符' : '输入您的密码'}
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                className="rounded-md!"
              />
            </Form.Item>

            {error && (
              <Alert
                className="mb-4 rounded-md text-xs"
                type="error"
                showIcon
                message={error}
                closable
                onClose={() => setError(null)}
              />
            )}

            <Button
              block
              type="primary"
              htmlType="submit"
              loading={submitting}
              className="rounded-md! h-9! text-xs! font-semibold"
            >
              {mode === 'login' ? '登 录' : '创建新账号'}
            </Button>
          </Form>

          <div className="mt-6 text-center text-xs text-slate-500 pt-4 border-t border-slate-100">
            <span>{mode === 'login' ? '还没有账号？' : '已有账号？'}</span>
            <button
              type="button"
              onClick={toggleMode}
              className="ml-1.5 text-blue-600 hover:text-blue-700 font-semibold cursor-pointer underline-offset-2 hover:underline"
            >
              {mode === 'login' ? '免费注册' : '返回登录'}
            </button>
          </div>
        </div>

        <p className="mt-6 text-center text-[11px] text-slate-400 font-mono">{APP_TAGLINE}</p>
      </div>
    </div>
  )
}

