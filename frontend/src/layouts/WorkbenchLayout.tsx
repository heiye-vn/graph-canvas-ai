/**
 * 工作台外壳：左侧导航 + 右侧 Outlet（对齐现代专业设计工具标准）。
 *
 * 常态 56px 紧凑收起，悬停平滑展开文字。
 */

import { AppstoreOutlined, BarChartOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { Avatar, Button } from 'antd'
import type { ReactNode } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'

import BrandMark from '@/components/BrandMark'
import { useAuthStore } from '@/stores/authStore'

const NAV_ITEMS: { to: string; label: string; icon: ReactNode }[] = [
  { to: '/create', label: '创作', icon: <PlusOutlined /> },
  { to: '/assets', label: '素材', icon: <AppstoreOutlined /> },
  { to: '/editor', label: '编辑', icon: <EditOutlined /> },
  { to: '/metrics', label: '数据', icon: <BarChartOutlined /> },
]

export default function WorkbenchLayout() {
  const navigate = useNavigate()
  const { user, signOut } = useAuthStore()

  return (
    <div className="flex h-full overflow-hidden bg-slate-100 text-slate-900">
      {/* select-none 只给导航壳：整页禁选会让用户连错误信息都复制不了 */}
      <nav className="relative z-30 w-14 shrink-0 select-none" aria-label="工作台导航">
        <div className="group absolute inset-y-0 left-0 flex w-14 flex-col overflow-hidden border-r border-slate-200 bg-white py-3.5 transition-[width,box-shadow] duration-200 hover:w-48 hover:shadow-lg">
          <div className="mb-5 flex items-center px-3">
            <Link to="/create" className="flex items-center overflow-hidden" title="Graph Canvas AI">
              <BrandMark responsive />
            </Link>
          </div>

          <ul className="flex flex-1 flex-col gap-1 px-2 m-0 p-0 list-none">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  title={item.label}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-md px-2.5 py-2 text-xs font-medium transition-all ${
                      isActive
                        ? 'bg-blue-50 text-blue-600 shadow-2xs'
                        : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                    }`
                  }
                >
                  <span className="flex w-5 shrink-0 justify-center text-base">{item.icon}</span>
                  <span className="truncate opacity-0 transition-opacity group-hover:opacity-100 font-medium">
                    {item.label}
                  </span>
                </NavLink>
              </li>
            ))}
          </ul>

          <div className="mt-2 border-t border-slate-100 px-2 pt-2.5">
            <Button
              type="text"
              title={user ? `${user.email} · 退出登录` : '退出登录'}
              onClick={() => {
                signOut()
                navigate('/login', { replace: true })
              }}
              className="h-auto! w-full! gap-2.5! px-2! py-2! flex! items-center! justify-start! rounded-md!"
            >
              <Avatar
                size={22}
                className="bg-blue-100! text-blue-700! shrink-0 text-[10px] font-bold"
              >
                {(user?.email ?? '?').slice(0, 1).toUpperCase()}
              </Avatar>
              <span className="truncate text-xs text-slate-600 opacity-0 transition-opacity group-hover:opacity-100">
                退出登录
              </span>
            </Button>
          </div>
        </div>
      </nav>

      <main className="min-w-0 flex-1 overflow-auto bg-slate-100">
        <Outlet />
      </main>
    </div>
  )
}

