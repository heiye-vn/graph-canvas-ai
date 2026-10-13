/**
 * 落地页文案与示例数据。
 *
 * 集中在这里是为了让「改一句 slogan」不用翻八个组件文件。
 * 文案一律面向**电商运营与内容创作者**，交付物统一叫「可上架的商品物料」。
 *
 * ⚠️ `ready: false` 的能力会在页面上打「即将上线」标记 —— 落地页不该宣称
 * 还没做出来的功能，演示时被追问会很尴尬。
 */

export interface Capability {
  id: string
  label: string
  title: string
  hint: string
  preview: 'generate' | 'edit' | 'local' | 'batch'
  ready: boolean
}

export const CAPABILITIES: Capability[] = [
  {
    id: 'generate',
    label: '文生图',
    title: '一句话，先出四张候选',
    hint: '描述画面要点，一次性给到多张候选。不满意就换一组，不用在参数里试半天。',
    preview: 'generate',
    ready: true,
  },
  {
    id: 'edit',
    label: '上传改图',
    title: '已有的图，接着改',
    hint: '上传现有素材，用自然语言或直接调用工具调整明暗、裁剪、构图。',
    preview: 'edit',
    ready: false,
  },
  {
    id: 'local',
    label: '局部重绘',
    title: '只改该改的那块',
    hint: '圈出要动的区域，其余像素保持原样 —— 换背景、去水印、补细节都用得上。',
    preview: 'local',
    ready: false,
  },
  {
    id: 'batch',
    label: '多尺寸物料',
    title: '一套图铺满所有坑位',
    hint: '主图、详情页、信息流各要一份尺寸，一次导出，不用手动裁四遍。',
    preview: 'batch',
    ready: false,
  },
]

export const EXAMPLE_PROMPTS = [
  '磨砂玻璃精华瓶立在亚克力台上，柔和顶光，白底电商主图',
  '木质桌面的中式早餐，自然侧逆光，浅景深氛围图',
  '模特手持保温杯站在户外阳光下，穿搭展示',
  '暖橙渐变背景的 618 大促海报，右侧留白放文案',
]

export interface DeliveryStep {
  index: string
  title: string
  hint: string
}

export const DELIVERY_STEPS: DeliveryStep[] = [
  { index: '01', title: '描述画面', hint: '把想要的成品说清楚，越具体越准' },
  { index: '02', title: '挑一张候选', hint: '候选图独立成页，可刷新、可分享给同事' },
  { index: '03', title: '精修到能上架', hint: '调色、去背景、局部调整，都在画布里完成' },
  { index: '04', title: '导出多尺寸', hint: '一次导出主图 / 详情页 / 信息流三套尺寸' },
]

export const DELIVERY_RATIOS = [
  { label: '1:1', usage: '商品主图' },
  { label: '3:4', usage: '详情页竖图' },
  { label: '4:3', usage: '场景横图' },
]
