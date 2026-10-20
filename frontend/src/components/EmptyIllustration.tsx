/**
 * 轻量空态插画：品牌蓝线稿「图层堆叠 + 星点」。
 *
 * 只画线不填色 —— 比 antd 默认灰盒子 SVG 有辨识度，又不至于抢文案的风头。
 * 统一给素材库 / 会话列表 / 导出清单的空态用，配合各自的指引文案。
 */

export default function EmptyIllustration({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 120 96"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* 三层堆叠（顶层完整，下两层只画前半边，营造纵深） */}
      <path
        d="M60 14 96 30 60 46 24 30Z"
        stroke="#2563eb"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M24 44l36 16 36-16"
        stroke="#93c5fd"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M24 58l36 16 36-16"
        stroke="#cbd5e1"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* 星点：AI 图层的暗示 */}
      <path
        d="M92 8l1.6 3.8 3.8 1.6-3.8 1.6L92 18.8l-1.6-3.8-3.8-1.6 3.8-1.6Z"
        fill="#2563eb"
        opacity="0.45"
      />
      <circle cx="20" cy="66" r="1.5" fill="#cbd5e1" />
    </svg>
  );
}
