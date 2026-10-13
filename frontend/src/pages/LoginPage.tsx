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
import { Alert, Button, ConfigProvider, Form, Input } from 'antd'
import { ArrowLeftOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'

import BrandMark from '@/components/BrandMark'
import { APP_TAGLINE } from '@/lib/brand'
import { darkPrimaryTheme } from '@/lib/antdTheme'
import { useAuthStore } from '@/stores/authStore'

interface LoginLocationState {
  /** 从落地页输入完 prompt 被拦到登录页时，记下要去哪、带什么 */
  next?: string
  prompt?: string
}

interface LoginForm {
  email: string
  password: string
}

export default function LoginPage() {
  const location = useLocation()
  const { user, loading, signIn, signUp } = useAuthStore()

  const next = (location.state as LoginLocationState | null)?.next ?? '/create'
  const carriedPrompt = (location.state as LoginLocationState | null)?.prompt

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
      <Navigate to={next} replace state={carriedPrompt ? { prompt: carriedPrompt } : undefined} />
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
    <div className="bg-canvas flex min-h-full flex-col px-6 py-10">
      <div className="mx-auto w-full max-w-md">
        <Link to="/">
          <Button type="text" size="small" icon={<ArrowLeftOutlined />}>
            返回首页
          </Button>
        </Link>

        <div className="bg-paper border-line rounded-panel mt-6 border p-8 shadow-lift sm:p-10">
          <BrandMark />

          <h1 className="text-ink mt-8 text-3xl font-semibold tracking-tight">
            {mode === 'login' ? '登录' : '创建账号'}
          </h1>

          <Form
            form={form}
            className="mt-8"
            size="large"
            layout="vertical"
            requiredMark={false}
            onFinish={onSubmit}
          >
            <Form.Item
              name="email"
              label="邮箱"
              rules={[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '邮箱格式不正确' },
              ]}
            >
              <Input
                prefix={<MailOutlined className="text-faint" />}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Form.Item>

            <Form.Item
              name="password"
              label="密码"
              rules={[
                { required: true, message: '请输入密码' },
                ...(mode === 'register'
                  ? [{ min: 8, message: '密码至少 8 位' } as const]
                  : []),
              ]}
            >
              <Input.Password
                prefix={<LockOutlined className="text-faint" />}
                placeholder={mode === 'register' ? '至少 8 位' : '输入密码'}
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
              />
            </Form.Item>

            {error && (
              <Alert
                className="mb-5"
                type="error"
                showIcon
                message={error}
                closable
                onClose={() => setError(null)}
              />
            )}

            {/* 局部覆盖主色：只影响这一个按钮，全局主色仍是品牌色 */}
            <ConfigProvider theme={darkPrimaryTheme}>
              <Button block type="primary" htmlType="submit" loading={submitting}>
                {mode === 'login' ? '登录' : '注册并进入'}
              </Button>
            </ConfigProvider>
          </Form>

          <p className="text-muted mt-6 text-sm">
            {mode === 'login' ? '还没有账号？' : '已有账号？'}
            <Button type="link" size="small" onClick={toggleMode}>
              {mode === 'login' ? '注册' : '登录'}
            </Button>
          </p>
        </div>

        <p className="text-faint mt-6 text-center text-xs">{APP_TAGLINE}</p>
      </div>
    </div>
  )
}
