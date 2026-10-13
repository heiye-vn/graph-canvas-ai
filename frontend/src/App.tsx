import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import ProtectedRoute from '@/components/ProtectedRoute'
import WorkbenchLayout from '@/layouts/WorkbenchLayout'
import CandidatesPage from '@/pages/CandidatesPage'
import CreatePage from '@/pages/CreatePage'
import EditorPage from '@/pages/EditorPage'
import HomePage from '@/pages/HomePage'
import LoginPage from '@/pages/LoginPage'
import { useAuthStore } from '@/stores/authStore'

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        {/* 鉴权与工作台外壳都做成布局路由：页面只管自己的内容区 */}
        <Route element={<ProtectedRoute />}>
          <Route element={<WorkbenchLayout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/create" element={<CreatePage />} />
            <Route path="/candidates/:runId" element={<CandidatesPage />} />
            <Route path="/editor" element={<EditorPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
