import { Link } from 'react-router-dom'

import BrandMark from '@/components/BrandMark'
import { APP_TAGLINE } from '@/lib/brand'

export default function LandingFooter() {
  return (
    <footer className="border-line bg-paper border-t py-8">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-8">
        <BrandMark />
        <p className="text-faint text-xs">{APP_TAGLINE}</p>
        <nav className="flex items-center gap-4 text-xs">
          <Link to="/create" className="text-muted hover:text-ink transition">
            创作
          </Link>
          <Link to="/login" className="text-muted hover:text-ink transition">
            登录
          </Link>
        </nav>
      </div>
    </footer>
  )
}
