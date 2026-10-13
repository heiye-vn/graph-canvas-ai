import { Card, Tag } from 'antd'

import { DELIVERY_STEPS } from '@/lib/marketing'

export default function DeliverySteps() {
  return (
    <section className="border-line bg-paper border-y py-14">
      <div className="mx-auto max-w-6xl px-8">
        <h2 className="text-ink text-2xl font-medium tracking-tight">四步交付</h2>

        <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {DELIVERY_STEPS.map((step) => (
            <li key={step.index} className="h-full">
              <Card size="small" variant="borderless" className="bg-soft h-full">
                <Tag bordered={false} color="processing" className="m-0 font-mono">
                  {step.index}
                </Tag>
                <h3 className="text-ink mt-2 text-base font-medium">{step.title}</h3>
                <p className="text-muted mt-1.5 text-xs leading-relaxed">{step.hint}</p>
              </Card>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
