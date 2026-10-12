import { rootGet } from './client'

export interface ReadyPayload {
  status: 'ready' | 'degraded'
  checks: {
    database: boolean
    redis: boolean
    storage: boolean
  }
  provider: string
}

/** readiness：探 Postgres / Redis / 对象存储，不就绪返回 503 */
export const fetchReady = () => rootGet<ReadyPayload>('/ready')

export const fetchHealth = () => rootGet<{ status: string; version: string }>('/health')
