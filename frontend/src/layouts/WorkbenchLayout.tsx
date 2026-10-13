/**
 * 工作台外壳：左侧导航 + 右侧 Outlet。
 *
 * 以前每个页面各自写一份 header（品牌标识、退出按钮、页面间跳转各抄一遍），
 * 页面一多必然漂移。现在导航只在这里定义，页面只管自己的内容区。
 *
 * 导航默认收起为图标，悬停展开文字 —— 参考画布类工具的通行做法：
 * 编辑区横向空间寸土寸金，常态不该被导航占掉。
 */

import { AppstoreOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { Avatar, Button } from 'antd'
import type { ReactNode } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import BrandMark from '@/components/BrandMark'
import { useAuthStore } from '@/stores/authStore'

// 图标统一走 @ant-design/icons，不再手拼 SVG path —— 线条粗细和视觉重量才是一套的
const NAV_ITEMS: { to: string; label: string; icon: ReactNode }[] = [
  { to: '/create', label: '创作', icon: <PlusOutlined /> },
  { to: '/assets', label: '素材', icon: <AppstoreOutlined /> },
  { to: '/editor', label: '编辑', icon: <EditOutlined /> },
]

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
                  <span className="flex w-5 shrink-0 justify-center text-[17px]">{item.icon}</span>
                  <span className="truncate opacity-0 transition-opacity group-hover:opacity-100">
                    {item.label}
                  </span>
                </NavLink>
              </li>
            ))}
          </ul>

          <div className="border-line mt-2 border-t px-2 pt-3">
            {/*
              这里的 Tailwind 类必须带 `!`：antd 的 CSS-in-JS 是运行时注入的，
              加载顺序在 Vite 产出的样式表之后，同优先级下会盖掉 Tailwind。
              收窄到最后这一处图标 Aligned 的间距上，不值得为它单独开一套 button token。
            */}
            <Button
              type="text"
              title={user ? `${user.email} · 退出登录` : '退出登录'}
              onClick={() => {
                signOut()
                navigate('/login', { replace: true })
              }}
              className="h-auto! w-full! gap-3! px-3! py-2.5! flex! items-center! justify-start!"
            >
              <Avatar
                size={20}
                className="bg-brand-soft! text-brand-strong! shrink-0 text-[11px] font-semibold"
              >
                {(user?.email ?? '?').slice(0, 1).toUpperCase()}
              </Avatar>
              <span className="truncate text-sm opacity-0 transition-opacity group-hover:opacity-100">
                退出登录
              </span>
            </Button>
          </div>
        </div>
      </nav>

      <main className="min-w-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
