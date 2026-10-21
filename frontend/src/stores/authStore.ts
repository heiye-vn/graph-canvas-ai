import { create } from 'zustand'

import { fetchMe, login, register } from '@/api/auth'
import type { UserOut } from '@/api/auth'
import { tokenStore } from '@/api/client'
import { clearUserQueryCache } from '@/lib/queryClient'

let authRevision = 0

interface AuthState {
  user: UserOut | null
  loading: boolean
  bootstrap: () => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string, displayName?: string) => Promise<void>
  signOut: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,

  /** 刷新后凭 localStorage 里的 token 恢复会话 */
  bootstrap: async () => {
    const revision = ++authRevision
    const token = tokenStore.get()
    if (!token) {
      clearUserQueryCache()
      set({ user: null, loading: false })
      return
    }
    try {
      const user = await fetchMe()
      if (revision !== authRevision || token !== tokenStore.get()) return
      set({ user, loading: false })
    } catch {
      if (revision !== authRevision || token !== tokenStore.get()) return
      tokenStore.set(null)
      clearUserQueryCache()
      set({ user: null, loading: false })
    }
  },

  signIn: async (email, password) => {
    const revision = ++authRevision
    const res = await login({ email, password })
    if (revision !== authRevision) return
    clearUserQueryCache()
    tokenStore.set(res.token.access_token)
    set({ user: res.user, loading: false })
  },

  signUp: async (email, password, displayName) => {
    const revision = ++authRevision
    const res = await register({ email, password, display_name: displayName })
    if (revision !== authRevision) return
    clearUserQueryCache()
    tokenStore.set(res.token.access_token)
    set({ user: res.user, loading: false })
  },

  signOut: () => {
    ++authRevision
    tokenStore.set(null)
    clearUserQueryCache()
    set({ user: null, loading: false })
  },
}))
