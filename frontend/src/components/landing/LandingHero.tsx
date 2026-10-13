import { APP_BADGE, APP_NAME, APP_TAGLINE } from '@/lib/brand'
import { DELIVERY_RATIOS } from '@/lib/marketing'
import PromptComposer from './PromptComposer'

export default function LandingHero() {
  return (
    <section className="mx-auto max-w-6xl px-8 pt-16 pb-12">
      <div className="grid items-start gap-10 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <p className="bg-brand-soft text-brand-strong inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs">
            <span className="bg-brand size-1.5 rounded-full" />
            面向电商运营与内容创作者
          </p>

          <h1 className="text-ink mt-4 text-4xl leading-tight font-medium tracking-tight sm:text-5xl">
            {APP_NAME}
            <span className="bg-accent text-dark mx-2 rounded-full px-2.5 py-1 align-middle text-sm font-semibold">
              {APP_BADGE}
            </span>
            <br />
            {APP_TAGLINE}
          </h1>

          <p className="text-muted mt-5 max-w-xl text-base leading-relaxed">
            不用在参数面板里试半天。把想要的效果说清楚，剩下的交给 {APP_NAME}：
            出候选、挑图、精修，一直到导出能直接上架的物料。
          </p>

          <dl className="mt-8 flex flex-wrap gap-x-8 gap-y-3">
            {DELIVERY_RATIOS.map((ratio) => (
              <div key={ratio.label} className="border-line border-l-2 pl-3">
                <dt className="text-ink font-mono text-sm">{ratio.label}</dt>
                <dd className="text-faint text-xs">{ratio.usage}</dd>
              </div>
            ))}
          </dl>
        </div>

        <PromptComposer />
      </div>
    </section>
  )
}
