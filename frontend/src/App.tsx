import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Spin } from 'antd'

import ProtectedRoute from '@/components/ProtectedRoute'
import WorkbenchLayout from '@/layouts/WorkbenchLayout'
import AssetsPage from '@/pages/AssetsPage'
import CandidatesPage from '@/pages/CandidatesPage'
import CreatePage from '@/pages/CreatePage'
import EditorIndexPage from '@/pages/EditorIndexPage'
import LandingPage from '@/pages/LandingPage'
import LoginPage from '@/pages/LoginPage'
import { useAuthStore } from '@/stores/authStore'

/**
 * 画布按需加载：Konva 有 330KB（gzip 后 100KB），而落地页和登录页用不到它。
 * 静态 import 会让每个访客都为一张还没打开的画布付带宽。
 */
const EditorPage = lazy(() => import('@/pages/EditorPage'))

function EditorFallback() {
  return (
    <div className="flex h-full items-center justify-center py-24">
      <Spin size="large" />
    </div>
  )
}

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  return (
    <BrowserRouter>
      <Routes>
        {/* 落地页公开：销售页不该先要求登录 */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />

        {/* 鉴权与工作台外壳都做成布局路由：页面只管自己的内容区 */}
        <Route element={<ProtectedRoute />}>
          <Route element={<WorkbenchLayout />}>
            <Route path="/assets" element={<AssetsPage />} />
            <Route path="/create" element={<CreatePage />} />
            <Route path="/candidates/:runId" element={<CandidatesPage />} />
            {/* session id 必须进 URL：刷新/分享都要能回到同一个画布 */}
            <Route path="/editor" element={<EditorIndexPage />} />
            <Route
              path="/editor/:sessionId"
              element={
                <Suspense fallback={<EditorFallback />}>
                  <EditorPage />
                </Suspense>
              }
            />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
