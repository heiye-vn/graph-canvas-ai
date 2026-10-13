import { Link } from 'react-router-dom'
import { Button } from 'antd'

import BrandMark from '@/components/BrandMark'
import { APP_TAGLINE } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'

/** 落地页顶栏。已登录直接给「进入工作台」，不再让用户绕登录页。 */
export default function LandingHeader() {
  const { user } = useAuthStore()

  return (
    <header className="bg-paper/85 border-line sticky top-0 z-40 border-b backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-8 py-3">
        <Link to="/" aria-label="回到首页">
          <BrandMark />
        </Link>

        <nav className="flex items-center gap-2">
          <span className="text-faint mr-2 hidden text-xs sm:inline">{APP_TAGLINE}</span>
          {user ? (
            <Link to="/create">
              <Button type="primary">进入工作台</Button>
            </Link>
          ) : (
            <>
              <Link to="/login">
                <Button type="text">登录</Button>
              </Link>
              <Link to="/login">
                <Button type="primary">免费开始</Button>
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}
