import {
  BarChartOutlined,
  BellOutlined,
  FileSearchOutlined,
  HomeOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Avatar } from 'antd'
import type { ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router'

import { ActionItemDetailPage } from '../../features/actions/ActionItemDetailPage'
import { AdminPage } from '../../features/admin/AdminPage'
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

const primaryNavigation: readonly { to: string; label: string; icon: ReactNode }[] = [
  { to: '/me/workbench', label: '我的工作', icon: <HomeOutlined aria-hidden /> },
  { to: '/review-cases', label: '审查活动', icon: <FileSearchOutlined aria-hidden /> },
  { to: '/me/notifications', label: '通知', icon: <BellOutlined aria-hidden /> },
  { to: '/management', label: '管理视图', icon: <BarChartOutlined aria-hidden /> },
]

const adminNavigation = {
  to: '/admin',
  label: '管理设置',
  icon: <SettingOutlined aria-hidden />,
}

export function ProductShell() {
  const { state } = useSession()
  if (state.status !== 'authenticated') {
    return null
  }

  const navigation =
    state.user.platform_role === 'system_admin'
      ? [...primaryNavigation, adminNavigation]
      : primaryNavigation

  return (
    <div className="app-shell">
      <div className="app-brand">
        <span className="app-brand-name">EasyAudit Next</span>
        <span className="app-brand-context">审查协作平台</span>
      </div>

      <header className="app-header">
        <span className="app-account">
          <Avatar size="small" icon={<UserOutlined aria-hidden />} />
          <span className="app-account-name">{state.user.display_name}</span>
        </span>
        <LogoutButton />
      </header>

      <nav className="app-nav" aria-label="主要导航">
        {navigation.map((item) => (
          <NavLink key={item.to} to={item.to}>
            {item.icon}
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <main className="app-content">
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
            element={<AdminPage />}
          />
          <Route path="*" element={<Navigate replace to="/me/workbench" />} />
        </Routes>
      </main>
    </div>
  )
}
