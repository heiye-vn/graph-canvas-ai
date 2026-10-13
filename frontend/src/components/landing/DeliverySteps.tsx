import { DELIVERY_STEPS } from '@/lib/marketing'

export default function DeliverySteps() {
  return (
    <section className="border-line bg-paper border-y py-14">
      <div className="mx-auto max-w-6xl px-8">
        <h2 className="text-ink text-2xl font-medium tracking-tight">四步交付</h2>

        <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {DELIVERY_STEPS.map((step) => (
            <li key={step.index} className="relative">
              <span className="text-brand font-mono text-xs">{step.index}</span>
              <h3 className="text-ink mt-1 text-base font-medium">{step.title}</h3>
              <p className="text-muted mt-1.5 text-xs leading-relaxed">{step.hint}</p>
              <span className="bg-line mt-4 block h-px w-full" />
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
