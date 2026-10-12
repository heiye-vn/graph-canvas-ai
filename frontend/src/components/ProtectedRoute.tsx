import { Navigate } from 'react-router-dom'

import { useAuthStore } from '@/stores/authStore'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuthStore()

  if (loading) {
    return <div className="flex h-full items-center justify-center text-sm text-muted">加载中…</div>
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}
