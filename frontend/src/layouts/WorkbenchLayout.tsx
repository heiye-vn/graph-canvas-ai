/**
 * 工作台外壳：左侧导航 + 右侧 Outlet。
 *
 * 以前每个页面各自写一份 header（品牌标识、退出按钮、页面间跳转各抄一遍），
 * 页面一多必然漂移。现在导航只在这里定义，页面只管自己的内容区。
 *
 * 导航默认收起为图标，悬停展开文字 —— 参考画布类工具的通行做法：
 * 编辑区横向空间寸土寸金，常态不该被导航占掉。
 */

import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import BrandMark from '@/components/BrandMark'
import { useAuthStore } from '@/stores/authStore'

const NAV_ITEMS = [
  { to: '/create', label: '创作', icon: 'M12 4v16m8-8H4' },
  { to: '/assets', label: '素材', icon: 'M4 6h16M4 12h16M4 18h10' },
  { to: '/editor', label: '编辑', icon: 'M4 20h4L20 8l-4-4L4 16v4z' },
]

function NavIcon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="size-5 shrink-0" aria-hidden>
      <path d={path} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export default function WorkbenchLayout() {
  const navigate = useNavigate()
  const { user, signOut } = useAuthStore()

  return (
    <div className="flex h-full overflow-hidden">
      <nav className="relative z-30 w-16 shrink-0" aria-label="工作台导航">
        <div className="group border-line bg-paper absolute inset-y-0 left-0 flex w-16 flex-col overflow-hidden border-r py-4 transition-[width,box-shadow] duration-200 hover:w-52 hover:shadow-card">
          <div className="mb-6 px-4">
            <BrandMark expanded={false} />
          </div>

          <ul className="flex flex-1 flex-col gap-1 px-2">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  title={item.label}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-control px-3 py-2.5 text-sm transition-colors ${
                      isActive
                        ? 'bg-brand-soft text-brand-strong font-medium'
                        : 'text-muted hover:bg-soft hover:text-ink'
                    }`
                  }
                >
                  <NavIcon path={item.icon} />
                  <span className="truncate opacity-0 transition-opacity group-hover:opacity-100">
                    {item.label}
                  </span>
                </NavLink>
              </li>
            ))}
          </ul>

          <div className="border-line mt-2 border-t px-2 pt-3">
            <button
              type="button"
              onClick={() => {
                signOut()
                navigate('/login', { replace: true })
              }}
              title={user ? `${user.email} · 退出登录` : '退出登录'}
              className="text-muted hover:bg-soft hover:text-ink flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-sm transition-colors"
            >
              <span className="bg-brand-soft text-brand-strong grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold">
                {(user?.email ?? '?').slice(0, 1).toUpperCase()}
              </span>
              <span className="truncate opacity-0 transition-opacity group-hover:opacity-100">
                退出登录
              </span>
            </button>
          </div>
        </div>
      </nav>

      <main className="min-w-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
