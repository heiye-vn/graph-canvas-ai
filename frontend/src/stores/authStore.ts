import { create } from 'zustand'

import { fetchMe, login, register } from '@/api/auth'
import type { UserOut } from '@/api/auth'
import { tokenStore } from '@/api/client'

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
    if (!tokenStore.get()) {
      set({ user: null, loading: false })
      return
    }
    try {
      set({ user: await fetchMe(), loading: false })
    } catch {
      tokenStore.set(null)
      set({ user: null, loading: false })
    }
  },

  signIn: async (email, password) => {
    const res = await login({ email, password })
    tokenStore.set(res.token.access_token)
    set({ user: res.user })
  },

  signUp: async (email, password, displayName) => {
    const res = await register({ email, password, display_name: displayName })
    tokenStore.set(res.token.access_token)
    set({ user: res.user })
  },

  signOut: () => {
    tokenStore.set(null)
    set({ user: null })
  },
}))
