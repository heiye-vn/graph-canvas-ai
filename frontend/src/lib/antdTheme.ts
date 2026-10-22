/**
 * antd 的设计 token —— 全部映射自 index.css 的手写主题。
 *
 * 保持与 index.css 的 --color-* / 圆角 / 字体完全一致。
 */

import type { ThemeConfig } from 'antd'

/** 与 index.css 对应的设计系统核心色值 */
const BRAND = '#2563eb'
const ACCENT = '#ec4899'

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: BRAND,
    colorInfo: BRAND,
    colorSuccess: '#10b981',
    colorError: '#ef4444',
    colorWarning: '#f59e0b',
    colorTextBase: '#0f1419',
    colorBgLayout: '#f8fafc',
    colorBgContainer: '#ffffff',
    colorBorder: '#cbd5e1',
    colorBorderSecondary: '#e2e8f0',

    // 专业级工具微圆角
    borderRadius: 6,
    borderRadiusSM: 4,
    borderRadiusLG: 8,

    controlHeight: 32,
    controlHeightSM: 26,
    controlHeightLG: 40,

    // 与 index.css body 的 font-family 逐字一致（别分叉）
    fontFamily:
      "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'HarmonyOS Sans SC', 'Hiragino Sans GB', 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Button: {
      controlHeight: 32,
      controlHeightSM: 26,
      controlHeightLG: 40,
      borderRadius: 6,
      borderRadiusSM: 4,
      fontWeight: 500,
    },
    Input: {
      controlHeight: 32,
      controlHeightLG: 40,
      borderRadius: 6,
    },
    Segmented: {
      borderRadius: 6,
      controlHeight: 28,
    },
    Slider: {
      trackBg: '#2563eb',
      handleColor: '#2563eb',
      handleActiveColor: '#1d4ed8',
    },
    Progress: {
      lineBorderRadius: 3,
    },
    Card: {
      borderRadiusLG: 8,
    },
  },
}

/** 强调色主题 */
export const accentTheme: ThemeConfig = {
  token: { colorPrimary: ACCENT, colorTextLightSolid: '#ffffff' },
}

