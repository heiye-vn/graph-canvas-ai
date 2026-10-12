import { useQuery } from '@tanstack/react-query'
import { fetchReady } from '@/api/health'

const CHECK_LABELS: Record<string, string> = {
  database: 'Postgres',
  redis: 'Redis',
  storage: '对象存储',
}

export default function LandingPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['ready'],
    queryFn: fetchReady,
  })

  return (
    <div className="min-h-full flex flex-col items-center justify-center gap-8 px-6">
      <header className="text-center">
        <h1 className="text-3xl font-medium tracking-tight">GraphCanvasAgent</h1>
        <p className="mt-2 text-sm text-neutral-400">
          自然语言驱动的多模态图像编辑工作台
        </p>
      </header>

      <section className="w-full max-w-md rounded-xl border border-white/10 bg-canvas-800 p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-medium">后端就绪状态</h2>
          <span className="text-xs text-neutral-400 font-mono">/ready</span>
        </div>

        {isLoading && <p className="text-sm text-neutral-400">探测中…</p>}
        {isError && (
          <p className="text-sm text-red-400">
            无法连接后端：{(error as Error).message}
          </p>
        )}

        {data && (
          <ul className="space-y-2">
            {Object.entries(data.checks).map(([key, ok]) => (
              <li key={key} className="flex items-center justify-between text-sm">
                <span className="text-neutral-300">{CHECK_LABELS[key] ?? key}</span>
                <span
                  className={
                    ok
                      ? 'rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300'
                      : 'rounded-md bg-red-500/15 px-2 py-0.5 text-xs text-red-300'
                  }
                >
                  {ok ? '就绪' : '不可用'}
                </span>
              </li>
            ))}
            <li className="flex items-center justify-between border-t border-white/10 pt-2 text-sm">
              <span className="text-neutral-300">模型 Provider</span>
              <span className="font-mono text-xs text-neutral-400">{data.provider}</span>
            </li>
          </ul>
        )}
      </section>

      <p className="text-xs text-neutral-500">
        骨架已就绪 · 编辑画布将在 M3 接入（React 19 + Konva）
      </p>
    </div>
  )
}
