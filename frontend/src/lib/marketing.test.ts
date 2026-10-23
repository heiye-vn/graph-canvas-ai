import { describe, expect, it } from 'vitest'

import { DELIVERY_RATIOS as EXPORT_RATIOS } from '@/api/exports'
import { DELIVERY_RATIOS } from './marketing'

describe('落地页交付能力', () => {
  it('宣传的投放比例与实际导出能力一致', () => {
    // 落地页是承诺，导出是兑现：两处列表必须同一套比例，不能各写各的
    expect(DELIVERY_RATIOS.map((ratio) => ratio.label)).toEqual([...EXPORT_RATIOS])
  })
})
