import CapabilityPreview from './Previews'
import { CAPABILITIES } from '@/lib/marketing'

export default function CapabilityShowcase() {
  return (
    <section className="mx-auto max-w-6xl px-8 py-14">
      <h2 className="text-ink text-2xl font-medium tracking-tight">从一句话到能上架</h2>
      <p className="text-muted mt-2 text-sm">整条链路在同一个工作台里，不在多个工具之间来回导。</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {CAPABILITIES.map((capability) => (
          <article
            key={capability.id}
            className="bg-paper border-line rounded-card border shadow-card overflow-hidden"
          >
            <div className="border-line bg-soft border-b p-3">
              <div className="aspect-[16/11]">
                <CapabilityPreview kind={capability.preview} />
              </div>
            </div>

            <div className="p-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="bg-brand-soft text-brand-strong rounded-full px-2 py-0.5 text-[11px]">
                  {capability.label}
                </span>
                {!capability.ready && (
                  <span className="text-faint rounded-full border border-line px-2 py-0.5 text-[11px]">
                    即将上线
                  </span>
                )}
              </div>
              <h3 className="text-ink text-sm font-medium">{capability.title}</h3>
              <p className="text-muted mt-1.5 text-xs leading-relaxed">{capability.hint}</p>
            </div>
          </article>
        ))}
      </div>

      <p className="text-faint mt-5 text-xs">
        示意图为界面结构演示，不代表真实模型产出。
      </p>
    </section>
  )
}
