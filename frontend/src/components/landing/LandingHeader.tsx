import { Link } from 'react-router-dom'

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
            <Link
              to="/create"
              className="bg-brand hover:bg-brand-strong rounded-control px-3 py-1.5 text-xs font-medium text-white shadow-control transition"
            >
              进入工作台
            </Link>
          ) : (
            <>
              <Link
                to="/login"
                className="text-muted hover:text-ink rounded-control px-3 py-1.5 text-xs transition"
              >
                登录
              </Link>
              <Link
                to="/login"
                className="bg-brand hover:bg-brand-strong rounded-control px-3 py-1.5 text-xs font-medium text-white shadow-control transition"
              >
                免费开始
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}
