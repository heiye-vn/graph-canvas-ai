import { afterEach, expect, it, vi } from 'vitest'
import { downloadExportZip } from './exports'

const click = vi.fn()
afterEach(() => vi.unstubAllGlobals())

it('ZIP 下载传递取消信号，blob 迟到后也不触发旧会话下载', async () => {
  vi.stubGlobal('localStorage', { getItem: () => 'token' })
  vi.stubGlobal('document', { createElement: () => ({ click }) })
  let finish!: (value: Blob) => void
  const blob = new Promise<Blob>((resolve) => { finish = resolve })
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: () => blob })
  vi.stubGlobal('fetch', fetchMock)
  const controller = new AbortController()
  const pending = downloadExportZip('session', ['asset'], 'export.zip', controller.signal)
  const result = pending.catch((error: Error) => error)
  await Promise.resolve()
  controller.abort()
  finish(new Blob(['zip']))
  const error = await result
  expect(error).toBeInstanceOf(Error)
  expect((error as Error).name).toBe('AbortError')
  expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal)
  expect(click).not.toHaveBeenCalled()
})
