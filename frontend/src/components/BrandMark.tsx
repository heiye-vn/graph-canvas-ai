import { APP_BADGE, APP_NAME } from "@/lib/brand";

/**
 * 现代专业 AI 画布矢量 Logo 图标。
 * 融合「多图层画板（Canvas Layers）」+「智能矢量节点（Graph Nodes）」+「AI 灵感星芒（Sparkle）」，
 * 采用自包含渐变与高精微几何，保证在任何分辨率下绝对锐利、富有科技质感。
 */
export function BrandLogoIcon({
  size = 32,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`shrink-0 select-none transition-transform duration-200 ${className}`}
      aria-hidden="true"
    >
      <defs>
        {/* 背景渐变：现代科技皇家蓝 -> 极光靛蓝 */}
        <linearGradient
          id="brand-bg-grad"
          x1="0"
          y1="0"
          x2="32"
          y2="32"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#2563EB" />
          <stop offset="55%" stopColor="#3B82F6" />
          <stop offset="100%" stopColor="#6366F1" />
        </linearGradient>

        {/* 顶层高亮画布渐变 */}
        <linearGradient
          id="brand-canvas-grad"
          x1="11"
          y1="6"
          x2="26"
          y2="21"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.96" />
          <stop offset="100%" stopColor="#EEF2FF" stopOpacity="0.88" />
        </linearGradient>

        {/* AI 灵感星芒金黄流光渐变 */}
        <linearGradient
          id="brand-sparkle-grad"
          x1="20"
          y1="4"
          x2="27"
          y2="11"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#FDE047" />
          <stop offset="100%" stopColor="#F59E0B" />
        </linearGradient>

        {/* 画布微投影滤镜 */}
        <filter
          id="canvas-depth"
          x="8"
          y="5"
          width="20"
          height="20"
          filterUnits="userSpaceOnUse"
        >
          <feDropShadow
            dx="0"
            dy="1.5"
            stdDeviation="1.5"
            floodColor="#1E3A8A"
            floodOpacity="0.22"
          />
        </filter>
      </defs>

      {/* 1. 圆角底座 */}
      <rect width="32" height="32" rx="8" fill="url(#brand-bg-grad)" />

      {/* 2. 顶部精致光泽描边 */}
      <rect
        x="0.5"
        y="0.5"
        width="31"
        height="31"
        rx="7.5"
        stroke="white"
        strokeOpacity="0.22"
        strokeWidth="1"
      />

      {/* 3. 底层图层 (Layer 1: 象征画布底层与图像图层) */}
      <rect
        x="6.5"
        y="11.5"
        width="13.5"
        height="13.5"
        rx="2.5"
        fill="white"
        fillOpacity="0.2"
        stroke="white"
        strokeOpacity="0.45"
        strokeWidth="1"
      />

      {/* 4. 顶层主画布 (Layer 2: 象征高亮工作区) */}
      <rect
        x="11.5"
        y="6.5"
        width="14"
        height="14"
        rx="3"
        fill="url(#brand-canvas-grad)"
        filter="url(#canvas-depth)"
      />

      {/* 5. 画布内的矢量绘制折线与图节点 */}
      <path
        d="M14 16L16.5 13L19 15.5L22 12"
        stroke="#2563EB"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22" cy="12" r="1" fill="#3B82F6" />
      <circle cx="14" cy="16" r="1" fill="#3B82F6" />

      {/* 6. AI 创意四芒星 (Sparkle: 象征 AI 生成与灵感) */}
      <path
        d="M24 3.5C24 5.3 25.2 6.5 27 6.5C25.2 6.5 24 7.7 24 9.5C24 7.7 22.8 6.5 21 6.5C22.8 6.5 24 5.3 24 3.5Z"
        fill="url(#brand-sparkle-grad)"
      />
      <circle cx="24" cy="6.5" r="0.75" fill="#FFFFFF" />

      {/* 7. 左上角微灵感星尘点 */}
      <circle cx="8" cy="8" r="0.75" fill="white" fillOpacity="0.6" />
    </svg>
  );
}

interface BrandMarkProps {
  /** 是否展开显示品牌文字。若为 false 则只显示图标 */
  expanded?: boolean;
  /** 是否响应侧边栏 group 悬停展开 (常态收起只露图标，悬停时平滑滑出文字) */
  responsive?: boolean;
  /** 图标尺寸，默认 32 */
  size?: number;
  /** 外部容器类名 */
  className?: string;
}

/**
 * 统一品牌标识组件。
 * 在桌面导航收起态（只露图标）、展开态（图标 + 文字）及各独立页面均保持一致的高水准视觉。
 */
export default function BrandMark({
  expanded = true,
  responsive = false,
  size = 32,
  className = "",
}: BrandMarkProps) {
  // 响应式模式：在父级 group 下常态隐藏文字，group-hover 时平滑展开
  if (responsive) {
    return (
      <span className={`flex items-center select-none ${className}`}>
        <BrandLogoIcon
          size={size}
          className="hover:scale-105 transition-transform"
        />
        <span className="flex items-center gap-1.5 overflow-hidden whitespace-nowrap opacity-0 max-w-0 transition-all duration-200 ease-out group-hover:opacity-100 group-hover:max-w-xs group-hover:ml-2.5">
          <span className="text-sm font-semibold tracking-tight text-slate-900">
            {APP_NAME}
          </span>
          <span className="rounded bg-gradient-to-r from-blue-600 to-indigo-600 px-1.5 py-0.5 text-[10px] font-bold text-white shadow-2xs">
            {APP_BADGE}
          </span>
        </span>
      </span>
    );
  }

  return (
    <span
      className={`flex items-center gap-2.5 overflow-hidden select-none ${className}`}
    >
      <BrandLogoIcon
        size={size}
        className="hover:scale-105 transition-transform"
      />
      {expanded && (
        <span className="flex items-center gap-1.5 text-sm font-semibold tracking-tight whitespace-nowrap text-slate-900">
          {APP_NAME}
          <span className="rounded bg-gradient-to-r from-blue-600 to-indigo-600 px-1.5 py-0.5 text-[10px] font-bold text-white shadow-2xs">
            {APP_BADGE}
          </span>
        </span>
      )}
    </span>
  );
}
