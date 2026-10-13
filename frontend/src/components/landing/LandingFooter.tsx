import { Link } from 'react-router-dom'
import { Button } from 'antd'

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

  const links = user
    ? [
        { to: '/create', label: '创作' },
        { to: '/assets', label: '素材' },
        { to: '/editor', label: '编辑' },
      ]
    : [
        { to: '/create', label: '创作' },
        { to: '/login', label: '登录' },
      ]

  return (
    <footer className="border-line bg-paper border-t py-8">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-8">
        <BrandMark />
        <p className="text-faint text-xs">{APP_TAGLINE}</p>
        <nav className="flex items-center">
          {links.map((link) => (
            <Link key={link.to} to={link.to}>
              <Button type="link" size="small">
                {link.label}
              </Button>
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  )
}
