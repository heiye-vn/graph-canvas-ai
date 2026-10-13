/**
 * antd 的设计 token —— 全部映射自 index.css 的手写主题。
 *
 * ⚠️ 这两处不许各调各的：改了主题色 / 圆角 / 字体，必须同步这里，
 * 否则 antd 组件和手写 Tailwind 部分会一眼看出是两套系统。
 */

import type { ThemeConfig } from 'antd'

/** 与 index.css 对应的几个原始色值，局部主题里复用，避免再抄一遍十六进制 */
const BRAND = '#5f98ad'
const ACCENT = '#d9ff6e'
const DARK = '#1e211e'

export const antdTheme: ThemeConfig = {
  token: {
    // 与 index.css 的 --color-* 一一对应
    colorPrimary: BRAND, // brand
    colorInfo: BRAND,
    colorSuccess: '#3b8a61', // success
    colorError: '#d95656', // danger
    colorWarning: '#ba7517',
    colorTextBase: '#171917', // ink
    colorBgLayout: '#eff1ee', // canvas
    colorBgContainer: '#ffffff', // paper
    colorBorder: '#d7dbd6', // line-strong
    colorBorderSecondary: '#e5e8e4', // line

    borderRadius: 12, // radius-control
    // large 尺寸给到 48：登录表单用它，和原来手写的 py-3.5 大致一个节奏
    controlHeightLG: 48,
    fontFamily: "system-ui, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Button: {
      // 主按钮加高到与手写输入框同一节奏（py-3 ≈ 40px 控件高）
      controlHeight: 40,
    },
    Progress: {
      // 进度条压细，接近之前手写的 h-1.5
      lineBorderRadius: 4,
    },
  },
}

/**
 * 局部主题 —— 用 `ConfigProvider` 只包住某一个按钮，避免为一个例外污染全局 token。
 *
 * 全局只有一个主色是对的：主色的语义是「整个产品里最该点的那一下」，
 * 页面上出现两个主色，层级就崩了。所以这两个例外必须显式、局部、有注释。
 */

/** 登录页提交按钮：中性深色，和落地页的品牌色 CTA 拉开层级 */
export const darkPrimaryTheme: ThemeConfig = { token: { colorPrimary: DARK } }

/** 落地页深色区块上的强调色 CTA：亮色底必须配深字，否则对比度不够 */
export const accentTheme: ThemeConfig = {
  token: { colorPrimary: ACCENT, colorTextLightSolid: DARK },
}
