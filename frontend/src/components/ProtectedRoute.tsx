import { Fragment } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Spin } from 'antd'

import { useAuthStore } from '@/stores/authStore'

/**
 * 路由守卫。两种用法都支持：
 *   - `<ProtectedRoute><Page /></ProtectedRoute>`      包单个页面
 *   - `<Route element={<ProtectedRoute />}>`           作为布局路由，内部渲染 `<Outlet />`
 *
 * bootstrap 期间必须给占位，不能直接放行：localStorage 里的令牌要验一次才知道
 * 有没有过期，那一瞬间用户既不算「已登录」也不算「未登录」。
 */
export default function ProtectedRoute({ children }: { children?: React.ReactNode }) {
  const { user, loading } = useAuthStore()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spin size="large" />
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" replace state={{
      next: location.pathname + location.search + location.hash,
      nextState: location.state,
    }} />
  }
  return <Fragment key={user.id}>{children ?? <Outlet />}</Fragment>
}
