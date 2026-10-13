/**
 * 页面头部的统一写法。
 *
 * 之前创作页 / 素材库 / 候选页各自手写一份标题 + 说明，
 * 字号间距各对一套 —— 收敛在这里之后，页面头再也不会漂移。
 */

export default function PageHeader({
  title,
  description,
  extra,
}: {
  title: string
  description?: string
  extra?: React.ReactNode
}) {
  return (
    <header className="mb-8 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-ink text-2xl font-medium tracking-tight">{title}</h1>
        {description && <p className="text-muted mt-1 text-sm">{description}</p>}
      </div>
      {extra && <div className="shrink-0">{extra}</div>}
    </header>
  )
}
