import { Card, Tag } from 'antd'

import CapabilityPreview from './Previews'
import { CAPABILITIES } from '@/lib/marketing'

export default function CapabilityShowcase() {
  return (
    <section className="mx-auto max-w-6xl px-8 py-14">
      <h2 className="text-ink text-2xl font-medium tracking-tight">从一句话到能上架</h2>
      <p className="text-muted mt-2 text-sm">整条链路在同一个工作台里，不在多个工具之间来回导。</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {CAPABILITIES.map((capability) => (
          <Card
            key={capability.id}
            size="small"
            hoverable={capability.ready}
            variant="outlined"
            classNames={{ body: 'pt-3!' }}
            cover={
              <div className="bg-soft aspect-[16/11] p-3">
                <CapabilityPreview kind={capability.preview} />
              </div>
            }
          >
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <Tag bordered={false} color="processing" className="m-0">
                {capability.label}
              </Tag>
              {!capability.ready && (
                <Tag bordered={false} className="m-0">
                  即将上线
                </Tag>
              )}
            </div>
            <h3 className="text-ink text-sm font-medium">{capability.title}</h3>
            <p className="text-muted mt-1.5 text-xs leading-relaxed">{capability.hint}</p>
          </Card>
        ))}
      </div>

      <p className="text-faint mt-5 text-xs">示意图为界面结构演示，不代表真实模型产出。</p>
    </section>
  )
}
