import { Navigate, Outlet } from 'react-router-dom'

import { useAuthStore } from '@/stores/authStore'

/**
 * 路由守卫。两种用法都支持：
 *   - `<ProtectedRoute><Page /></ProtectedRoute>`      包单个页面
 *   - `<Route element={<ProtectedRoute />}>`           作为布局路由，内部渲染 `<Outlet />`
 */
export default function ProtectedRoute({ children }: { children?: React.ReactNode }) {
  const { user, loading } = useAuthStore()

  if (loading) {
    return <div className="flex h-full items-center justify-center text-sm text-muted">加载中…</div>
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children ?? <Outlet />}</>
}
