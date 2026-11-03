import { create } from 'zustand'

export interface ActiveTask {
  runId: string
  prompt: string
  createdAt: number
}

interface TaskState {
  activeTask: ActiveTask | null
  minimized: boolean
  setActiveTask: (task: { runId: string; prompt: string } | null) => void
  setMinimized: (minimized: boolean) => void
  clearActiveTask: () => void
}

const STORAGE_KEY = 'gca.active_run_task'

function loadSavedTask(): ActiveTask | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as ActiveTask
    // 超过 30 分钟的任务不再恢复
    if (Date.now() - parsed.createdAt > 30 * 60 * 1000) {
      sessionStorage.removeItem(STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export const useTaskStore = create<TaskState>((set) => ({
  activeTask: loadSavedTask(),
  minimized: false,

  setActiveTask: (task) => {
    if (task) {
      const active: ActiveTask = {
        runId: task.runId,
        prompt: task.prompt,
        createdAt: Date.now(),
      }
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(active))
      } catch {
        // ignore
      }
      set({ activeTask: active, minimized: false })
    } else {
      try {
        sessionStorage.removeItem(STORAGE_KEY)
      } catch {
        // ignore
      }
      set({ activeTask: null })
    }
  },

  setMinimized: (minimized) => set({ minimized }),

  clearActiveTask: () => {
    try {
      sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
    set({ activeTask: null })
  },
}))

