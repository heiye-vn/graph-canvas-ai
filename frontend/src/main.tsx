import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './lib/queryClient'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import { setUnauthorizedHandler } from './api/client'
import { antdTheme } from './lib/antdTheme'
import { useAuthStore } from './stores/authStore'
import './index.css'

// 401 时同步退出登录态，让路由守卫把用户送回登录页
setUnauthorizedHandler(() => useAuthStore.getState().signOut())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>,
)
