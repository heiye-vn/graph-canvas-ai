import { QueryClient } from '@tanstack/react-query'

// 不依赖 API 或认证 store，避免 client → store → QueryClient 的循环导入。
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
})

export function clearUserQueryCache() {
  // 取消同步生效；不要等待后再 clear，否则可能清掉新账号刚发起的查询。
  void queryClient.cancelQueries()
  queryClient.clear()
}
