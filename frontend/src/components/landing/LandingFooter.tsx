import { Link } from 'react-router-dom'

import BrandMark from '@/components/BrandMark'
import { APP_TAGLINE } from '@/lib/brand'
import { useAuthStore } from '@/stores/authStore'

/**
 * 页脚导航必须**跟随登录态**，不能写死。
 *
 * 之前这里硬编码了「创作 / 登录」——已登录用户看到「登录」，点过去还是登录表单，
 * 第一反应就是「我是不是被登出去了」。落地页上所有入口的登录态必须同进同退。
 */
export default function LandingFooter() {
  const { user } = useAuthStore()

  return (
    <footer className="border-line bg-paper border-t py-8">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-8">
        <BrandMark />
        <p className="text-faint text-xs">{APP_TAGLINE}</p>
        <nav className="flex items-center gap-4 text-xs">
          {user ? (
            <>
              <Link to="/create" className="text-muted hover:text-ink transition">
                创作
              </Link>
              <Link to="/assets" className="text-muted hover:text-ink transition">
                素材
              </Link>
              <Link to="/editor" className="text-muted hover:text-ink transition">
                编辑
              </Link>
            </>
          ) : (
            <>
              <Link to="/create" className="text-muted hover:text-ink transition">
                创作
              </Link>
              <Link to="/login" className="text-muted hover:text-ink transition">
                登录
              </Link>
            </>
          )}
        </nav>
      </div>
    </footer>
  )
}
