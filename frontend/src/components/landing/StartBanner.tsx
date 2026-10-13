import { Link } from 'react-router-dom'
import { Button, ConfigProvider } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'

import { APP_TAGLINE } from '@/lib/brand'
import { accentTheme } from '@/lib/antdTheme'
import { useAuthStore } from '@/stores/authStore'

export default function StartBanner() {
  const { user } = useAuthStore()

  return (
    <section className="mx-auto max-w-6xl px-8 py-14">
      <div className="rounded-card bg-dark relative overflow-hidden px-8 py-10 shadow-card">
        <span className="bg-accent absolute -right-8 -top-8 size-32 rounded-full opacity-20" />

        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div>
            <h2 className="text-xl font-medium text-white">现在就把那句话变成图</h2>
            <p className="mt-1.5 text-sm text-white/70">{APP_TAGLINE}</p>
          </div>

          {/* 深色区块上的 CTA 用强调色：它压在整个页面的视觉重心上，主色降不住 */}
          <ConfigProvider theme={accentTheme}>
            <Link to={user ? '/create' : '/login'}>
              <Button type="primary">
                {user ? '打开工作台' : '免费开始'}
                <ArrowRightOutlined />
              </Button>
            </Link>
          </ConfigProvider>
        </div>
      </div>
    </section>
  )
}
