import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import { setUnauthorizedHandler } from './api/client'
import { antdTheme } from './lib/antdTheme'
import { useAuthStore } from './stores/authStore'
import './index.css'

// 401 时同步退出登录态，让路由守卫把用户送回登录页
setUnauthorizedHandler(() => useAuthStore.getState().signOut())

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 图像编辑场景：数据变更以显式操作为主，不要自动狂刷
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>,
)
