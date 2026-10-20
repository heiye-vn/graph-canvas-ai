import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 后端 API 与 SSE 的代理目标（本地开发用；生产由后端同源托管 dist）
// 端口段 74xx：本项目的固定号段，整体平移时同步 .env 与 docker-compose.yml
const API_TARGET = 'http://127.0.0.1:7402'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 7401,
    strictPort: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (err, _req, _res) => {
            console.error('[Vite Proxy API Error]', err.message)
          })
        },
      },
      // 探针与 SSE 刻意不挂 /api 前缀（后端同规则），便于反向代理单独关闭缓冲
      '/health': { target: API_TARGET, changeOrigin: true },
      '/ready': { target: API_TARGET, changeOrigin: true },
      '/events': {
        target: API_TARGET,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (err, _req, _res) => {
            console.error('[Vite Proxy Events Error]', err.message)
          })
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['connection'] = 'keep-alive'
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // antd 体积占了一半以上、变更频率远低于业务代码 —— 单独成块，
        // 改一行页面逻辑不该让用户把整个组件库重新下一遍。
        manualChunks: {
          antd: ['antd', '@ant-design/icons'],
          konva: ['konva', 'react-konva'],
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
