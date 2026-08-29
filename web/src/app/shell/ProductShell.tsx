import { NavLink, Navigate, Route, Routes } from 'react-router'

import { ActionItemDetailPage } from '../../features/actions/ActionItemDetailPage'
import { FindingDetailPage } from '../../features/findings/FindingDetailPage'
import { ManagementCaseProgressPage } from '../../features/management/ManagementCaseProgressPage'
import { ManagementPage } from '../../features/management/ManagementPage'
import { NotificationCenterPage } from '../../features/notifications/NotificationCenterPage'
import { ReviewCaseCollectionPage } from '../../features/reviewCases/ReviewCaseCollectionPage'
import { ReviewCaseDetailPage } from '../../features/reviewCases/ReviewCaseDetailPage'
import { ReviewCaseCreatePage } from '../../features/reviewPlans/ReviewCaseCreatePage'
import { ReviewPlanCreatePage } from '../../features/reviewPlans/ReviewPlanCreatePage'
import { WorkbenchPage } from '../../features/workbench/WorkbenchPage'
import { LogoutButton } from '../auth/LogoutButton'
import { useSession } from '../auth/session'
import { PlaceholderPage } from './PlaceholderPage'

const primaryNavigation = [
  { to: '/me/workbench', label: '我的工作' },
  { to: '/review-cases', label: '审查活动' },
  { to: '/me/notifications', label: '通知' },
  { to: '/management', label: '管理视图' },
] as const

export function ProductShell() {
  const { state } = useSession()
  if (state.status !== 'authenticated') {
    return null
  }

  return (
    <div className="product-shell">
      <header className="product-header">
        <div>
          <p className="product-name">EasyAudit Next</p>
          <p className="product-context">审查协作平台</p>
        </div>
        <div className="account-area">
          <span>{state.user.display_name}</span>
          <LogoutButton className="compact-button" />
        </div>
      </header>

      <nav className="primary-nav" aria-label="主要导航">
        {primaryNavigation.map((item) => (
          <NavLink key={item.to} to={item.to}>
            {item.label}
          </NavLink>
        ))}
        {state.user.platform_role === 'system_admin' ? (
          <NavLink to="/admin">管理设置</NavLink>
        ) : null}
      </nav>

      <main className="product-content">
        <Routes>
          <Route path="/me/workbench" element={<WorkbenchPage />} />
          <Route path="/review-cases" element={<ReviewCaseCollectionPage />} />
          <Route path="/review-cases/:caseId" element={<ReviewCaseDetailPage />} />
          <Route path="/review-plans/new" element={<ReviewPlanCreatePage />} />
          <Route
            path="/review-plans/:planId/review-cases/new"
            element={<ReviewCaseCreatePage />}
          />
          <Route path="/findings/:findingId" element={<FindingDetailPage />} />
          <Route path="/action-items/:actionItemId" element={<ActionItemDetailPage />} />
          <Route path="/me/notifications" element={<NotificationCenterPage />} />
          <Route path="/management" element={<ManagementPage />} />
          <Route
            path="/management/review-cases/:caseId"
            element={<ManagementCaseProgressPage />}
          />
          <Route
            path="/admin/*"
            element={
              <PlaceholderPage
                title="管理设置"
                slice="Later Product Surface"
                description="平台管理入口仅作为导航提示；后端平台授权仍是唯一权限边界。"
              />
            }
          />
          <Route path="*" element={<Navigate replace to="/me/workbench" />} />
        </Routes>
      </main>
    </div>
  )
}
