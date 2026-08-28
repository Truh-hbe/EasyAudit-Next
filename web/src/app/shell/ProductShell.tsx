import { NavLink, Navigate, Route, Routes } from 'react-router'

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
          <Route
            path="/me/workbench"
            element={
              <PlaceholderPage
                title="我的工作"
                slice="M3.5.2"
                description="Workbench 业务内容将在后续切片接入现有服务器 read-side。"
              />
            }
          />
          <Route
            path="/review-cases/*"
            element={
              <PlaceholderPage
                title="审查活动"
                slice="M3.5.2–M3.5.3"
                description="ReviewCase、Finding 与 Action 协作界面将在后续切片实现。"
              />
            }
          />
          <Route
            path="/me/notifications"
            element={
              <PlaceholderPage
                title="通知"
                slice="M3.5.4"
                description="Notification Center 将直接消费已合并的持久通知能力。"
              />
            }
          />
          <Route
            path="/management"
            element={
              <PlaceholderPage
                title="管理视图"
                slice="M3.5.4"
                description="管理进度与逾期视图将在后续切片消费现有 management read-side。"
              />
            }
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
