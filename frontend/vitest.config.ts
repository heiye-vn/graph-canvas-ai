import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

/**
 * 领域层测试配置。
 *
 * 只跑 `src/**\/*.test.ts`：这里测的是纯函数，不需要浏览器环境，
 * 也不需要 jsdom（组件级的验证留给 e2e，配一套 DOM 环境换来的覆盖率不值）。
 */
export default defineConfig({
  envDir: false,
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
