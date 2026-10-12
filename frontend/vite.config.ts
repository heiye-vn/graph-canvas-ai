import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 后端 API 与 SSE 的代理目标（本地开发用；生产由后端同源托管 dist）
const API_TARGET = 'http://127.0.0.1:7302'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 7301,
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      // 探针与 SSE 刻意不挂 /api 前缀（后端同规则），便于反向代理单独关闭缓冲
      '/health': { target: API_TARGET, changeOrigin: true },
      '/ready': { target: API_TARGET, changeOrigin: true },
      '/events': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
