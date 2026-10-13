/**
 * 落地页（未登录也能看）。
 *
 * 路由刻意放在 `/` 且**不套 WorkbenchLayout**：销售页不该先要求登录，
 * 也不该被工作台的左侧导航占掉横向空间。
 */

import { useEffect } from 'react'

import CapabilityShowcase from '@/components/landing/CapabilityShowcase'
import DeliverySteps from '@/components/landing/DeliverySteps'
import LandingFooter from '@/components/landing/LandingFooter'
import LandingHeader from '@/components/landing/LandingHeader'
import LandingHero from '@/components/landing/LandingHero'
import StartBanner from '@/components/landing/StartBanner'
import { APP_NAME, APP_TAGLINE } from '@/lib/brand'

export default function LandingPage() {
  useEffect(() => {
    document.title = `${APP_NAME} AI · ${APP_TAGLINE}`
  }, [])

  return (
    <div className="min-h-screen">
      <LandingHeader />
      <main>
        <LandingHero />
        <CapabilityShowcase />
        <DeliverySteps />
        <StartBanner />
      </main>
      <LandingFooter />
    </div>
  )
}
