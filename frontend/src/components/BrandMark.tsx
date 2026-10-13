import { APP_BADGE, APP_NAME } from '@/lib/brand'

/**
 * 品牌标识。集中在这里是为了让导航收起态（只露图标）与展开态（图标 + 文字）
 * 在任何页面都长一样——之前每个页面各写一份 header，改个名字要改三四处。
 */
export default function BrandMark({ expanded = true }: { expanded?: boolean }) {
  return (
    <span className="flex items-center gap-2 overflow-hidden">
      <span className="bg-brand grid size-8 shrink-0 place-items-center rounded-control text-[11px] font-medium text-white">
        {APP_NAME}
      </span>
      <span
        className={`flex items-center gap-1.5 text-sm font-medium whitespace-nowrap text-ink transition-opacity ${
          expanded ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {APP_NAME}
        <span className="bg-accent rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-dark">
          {APP_BADGE}
        </span>
      </span>
    </span>
  )
}
