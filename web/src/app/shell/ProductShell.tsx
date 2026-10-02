import {
  BarChartOutlined,
  BellOutlined,
  FileSearchOutlined,
  HomeOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Avatar } from 'antd'
import { lazy } from 'react'
import type { ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router'

import { WorkbenchPage } from '../../features/workbench/WorkbenchPage'
import { LogoutButton } from '../auth/LogoutButton'
import { useSession } from '../auth/session'
import { RouteBoundary } from '../router/RouteBoundary'

// 登录后的落地页 /me/workbench 留在入口包：懒加载会让页面内容晚一个请求往返出现（实测见 PR 描述）。
// 其余业务页面按路由拆分，避免 Table 等重组件进入入口包。
const ActionItemDetailPage = lazy(() =>
  import('../../features/actions/ActionItemDetailPage').then((m) => ({ default: m.ActionItemDetailPage })),
)
const AdminPage = lazy(() =>
  import('../../features/admin/AdminPage').then((m) => ({ default: m.AdminPage })),
)
const FindingDetailPage = lazy(() =>
  import('../../features/findings/FindingDetailPage').then((m) => ({ default: m.FindingDetailPage })),
)
const ManagementCaseProgressPage = lazy(() =>
  import('../../features/management/ManagementCaseProgressPage').then((m) => ({ default: m.ManagementCaseProgressPage })),
)
const ManagementPage = lazy(() =>
  import('../../features/management/ManagementPage').then((m) => ({ default: m.ManagementPage })),
)
const NotificationCenterPage = lazy(() =>
  import('../../features/notifications/NotificationCenterPage').then((m) => ({ default: m.NotificationCenterPage })),
)
const ReviewCaseCollectionPage = lazy(() =>
  import('../../features/reviewCases/ReviewCaseCollectionPage').then((m) => ({ default: m.ReviewCaseCollectionPage })),
)
const ReviewCaseDetailPage = lazy(() =>
  import('../../features/reviewCases/ReviewCaseDetailPage').then((m) => ({ default: m.ReviewCaseDetailPage })),
)
const ReviewCaseCreatePage = lazy(() =>
  import('../../features/reviewPlans/ReviewCaseCreatePage').then((m) => ({ default: m.ReviewCaseCreatePage })),
)
const ReviewPlanCreatePage = lazy(() =>
  import('../../features/reviewPlans/ReviewPlanCreatePage').then((m) => ({ default: m.ReviewPlanCreatePage })),
)

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
        <RouteBoundary>
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
        </RouteBoundary>
      </main>
    </div>
  )
}
