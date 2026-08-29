import { type FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError } from '../../api/client'
import {
  createAdminDepartment,
  createAdminUser,
  getAdminOrganization,
  getAdminScenarioStatus,
  listAdminDepartments,
  listAdminUsers,
  resetAdminUserCredential,
  updateAdminDepartment,
  updateAdminUser,
} from '../../api/admin'
import type {
  AdminScenarioStatusItem,
  DepartmentResponse,
  OrganizationResponse,
} from '../../api/admin'
import type { PlatformRole, UserResponse } from '../../api/contracts'
import { formatDateTime } from '../../product/format'

interface AdminData {
  organization: OrganizationResponse
  departments: DepartmentResponse[]
  users: UserResponse[]
  scenarios: AdminScenarioStatusItem[]
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; data: AdminData }
  | { status: 'error'; message: string }

export function adminErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const messages: Record<number, string> = {
      401: '登录状态已失效，请重新登录。',
      403: '当前账号没有管理员权限。',
      404: '目标数据不存在或已被移除。',
      409: '服务器检测到状态冲突，请刷新后重试。',
      422: '提交内容不符合当前规则，请检查后重试。',
    }
    return messages[error.status] ?? `请求失败（HTTP ${error.status}）。`
  }
  return error instanceof Error ? error.message : fallback
}

export function scenarioVersionLabel(scenarioKey: string, version: number): string {
  return `${scenarioKey}@${version}`
}

function dateText(value: string): string {
  return formatDateTime(value)
}

function departmentName(departments: DepartmentResponse[], id: string | null): string {
  if (id === null) return '未分配'
  return departments.find((department) => department.id === id)?.name ?? '未知部门'
}

export function AdminPage() {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const requestSequence = useRef(0)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [departmentId, setDepartmentId] = useState<string | null>(null)
  const [departmentNameInput, setDepartmentNameInput] = useState('')
  const [departmentParentId, setDepartmentParentId] = useState('')
  const [departmentActive, setDepartmentActive] = useState(true)

  const [userId, setUserId] = useState<string | null>(null)
  const [userDisplayName, setUserDisplayName] = useState('')
  const [userLoginName, setUserLoginName] = useState('')
  const [userInitialPassword, setUserInitialPassword] = useState('')
  const [userRole, setUserRole] = useState<PlatformRole>('ordinary_user')
  const [userDepartmentId, setUserDepartmentId] = useState('')
  const [userActive, setUserActive] = useState(true)

  const [resetUserId, setResetUserId] = useState('')
  const [resetPassword, setResetPassword] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setState({ status: 'loading' })
    setActionMessage(null)

    void Promise.all([
      getAdminOrganization(controller.signal),
      listAdminDepartments(controller.signal),
      listAdminUsers(controller.signal),
      getAdminScenarioStatus(controller.signal),
    ])
      .then(([organization, departments, users, scenarios]) => {
        if (controller.signal.aborted || requestSequence.current !== sequence) return
        setState({ status: 'ready', data: { organization, departments, users, scenarios: scenarios.items } })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestSequence.current !== sequence) return
        setState({ status: 'error', message: adminErrorMessage(error, '管理员数据读取失败。') })
      })

    return () => controller.abort()
  }, [revision])

  if (state.status === 'loading') {
    return <section className="surface-page"><section className="surface-card"><p>正在读取管理员数据…</p></section></section>
  }

  if (state.status === 'error') {
    return (
      <section className="surface-page" aria-labelledby="admin-title">
        <div className="page-heading"><div><p className="eyebrow">M5.4 · administration</p><h1 id="admin-title">管理设置</h1></div></div>
        <section className="surface-card" role="alert">
          <p>{state.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </section>
      </section>
    )
  }

  const { organization, departments, users, scenarios } = state.data

  function clearDepartmentForm() {
    setDepartmentId(null)
    setDepartmentNameInput('')
    setDepartmentParentId('')
    setDepartmentActive(true)
  }

  function editDepartment(department: DepartmentResponse) {
    setDepartmentId(department.id)
    setDepartmentNameInput(department.name)
    setDepartmentParentId(department.parent_id ?? '')
    setDepartmentActive(department.is_active)
  }

  function clearUserForm() {
    setUserId(null)
    setUserDisplayName('')
    setUserLoginName('')
    setUserInitialPassword('')
    setUserRole('ordinary_user')
    setUserDepartmentId('')
    setUserActive(true)
  }

  function editUser(user: UserResponse) {
    setUserId(user.id)
    setUserDisplayName(user.display_name)
    setUserLoginName('')
    setUserInitialPassword('')
    setUserRole(user.platform_role)
    setUserDepartmentId(user.primary_department_id ?? '')
    setUserActive(user.is_active)
  }

  async function refreshAfter(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setActionMessage(null)
    try {
      await action()
      clearDepartmentForm()
      clearUserForm()
      setActionMessage(success)
      setRevision((value) => value + 1)
    } catch (error: unknown) {
      setActionMessage(adminErrorMessage(error, '操作失败，请重试。'))
    } finally {
      setBusy(false)
    }
  }

  async function submitDepartment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = departmentNameInput.trim()
    if (name.length === 0) {
      setActionMessage('请输入部门名称。')
      return
    }
    const parentId = departmentParentId.trim() === '' ? null : departmentParentId
    if (departmentId === null) {
      await refreshAfter(
        () => createAdminDepartment({ name, parent_id: parentId }),
        '部门已由服务器创建。',
      )
      return
    }
    await refreshAfter(
      () => updateAdminDepartment(departmentId, { name, parent_id: parentId, is_active: departmentActive }),
      '部门已由服务器更新。',
    )
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const displayName = userDisplayName.trim()
    if (displayName.length === 0) {
      setActionMessage('请输入用户名称。')
      return
    }
    const primaryDepartmentId = userDepartmentId.trim() === '' ? null : userDepartmentId
    if (userId === null) {
      if (userLoginName.trim().length === 0 || userInitialPassword.length < 12) {
        setActionMessage('新用户需要登录名和至少 12 个字符的初始密码。')
        return
      }
      await refreshAfter(
        () => createAdminUser({
          display_name: displayName,
          login_name: userLoginName,
          initial_password: userInitialPassword,
          platform_role: userRole,
          primary_department_id: primaryDepartmentId,
          must_change_password: true,
        }),
        '用户已由服务器创建。',
      )
      setUserInitialPassword('')
      return
    }
    await refreshAfter(
      () => updateAdminUser(userId, {
        display_name: displayName,
        platform_role: userRole,
        primary_department_id: primaryDepartmentId,
        is_active: userActive,
      }),
      '用户已由服务器更新。',
    )
  }

  async function submitReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const targetUserId = resetUserId
    const temporaryPassword = resetPassword
    // The secret is intentionally removed before the request starts and is
    // never retained for an automatic retry.
    setResetPassword('')
    if (targetUserId === '' || temporaryPassword.length < 12) {
      setActionMessage('请选择用户并输入至少 12 个字符的临时密码。')
      return
    }
    setBusy(true)
    setActionMessage(null)
    try {
      await resetAdminUserCredential(targetUserId, { temporary_password: temporaryPassword })
      setActionMessage('临时凭据已重置；目标用户下次登录必须修改密码。')
      setRevision((value) => value + 1)
    } catch (error: unknown) {
      setActionMessage(adminErrorMessage(error, '凭据重置失败，请重新输入临时密码后重试。'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="surface-page" aria-labelledby="admin-title">
      <div className="page-heading">
        <div><p className="eyebrow">M5.4 · minimal pilot administration</p><h1 id="admin-title">管理设置</h1></div>
        <p>{organization.name} · {organization.is_active ? '启用' : '停用'}</p>
      </div>

      {actionMessage !== null ? <p role="status">{actionMessage}</p> : null}

      <section className="surface-card" aria-labelledby="admin-departments-title">
        <div className="section-heading"><h2 id="admin-departments-title">部门</h2><span>{departments.length} 个</span></div>
        <form onSubmit={(event) => { void submitDepartment(event) }}>
          <label>部门名称<input value={departmentNameInput} onChange={(event) => setDepartmentNameInput(event.target.value)} disabled={busy} required /></label>
          <label>上级部门
            <select value={departmentParentId} onChange={(event) => setDepartmentParentId(event.target.value)} disabled={busy}>
              <option value="">无</option>
              {departments.filter((department) => department.id !== departmentId).map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
            </select>
          </label>
          {departmentId !== null ? <label><input type="checkbox" checked={departmentActive} onChange={(event) => setDepartmentActive(event.target.checked)} disabled={busy} /> 部门启用</label> : null}
          <div className="command-stack"><button type="submit" disabled={busy}>{departmentId === null ? '创建部门' : '保存部门'}</button>{departmentId !== null ? <button type="button" className="secondary" onClick={clearDepartmentForm} disabled={busy}>取消编辑</button> : null}</div>
        </form>
        <ul className="surface-list">
          {departments.map((department) => <li key={department.id}><div><strong>{department.name}</strong><p>上级：{departmentName(departments, department.parent_id)}</p></div><span>{department.is_active ? '启用' : '停用'}</span><button type="button" className="secondary" onClick={() => editDepartment(department)} disabled={busy}>编辑</button></li>)}
        </ul>
      </section>

      <section className="surface-card" aria-labelledby="admin-users-title">
        <div className="section-heading"><h2 id="admin-users-title">用户</h2><span>{users.length} 个</span></div>
        <form onSubmit={(event) => { void submitUser(event) }}>
          <div className="form-grid">
            <label>显示名称<input value={userDisplayName} onChange={(event) => setUserDisplayName(event.target.value)} disabled={busy} required /></label>
            {userId === null ? <label>登录名<input value={userLoginName} onChange={(event) => setUserLoginName(event.target.value)} disabled={busy} required /></label> : null}
            {userId === null ? <label>初始密码<input type="password" value={userInitialPassword} onChange={(event) => setUserInitialPassword(event.target.value)} disabled={busy} autoComplete="new-password" required /></label> : null}
            <label>平台角色<select value={userRole} onChange={(event) => setUserRole(event.target.value as PlatformRole)} disabled={busy}><option value="ordinary_user">普通用户</option><option value="system_admin">系统管理员</option></select></label>
            <label>主要部门<select value={userDepartmentId} onChange={(event) => setUserDepartmentId(event.target.value)} disabled={busy}><option value="">未分配</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
          </div>
          {userId !== null ? <label><input type="checkbox" checked={userActive} onChange={(event) => setUserActive(event.target.checked)} disabled={busy} /> 用户启用</label> : null}
          <div className="command-stack"><button type="submit" disabled={busy}>{userId === null ? '创建用户' : '保存用户'}</button>{userId !== null ? <button type="button" className="secondary" onClick={clearUserForm} disabled={busy}>取消编辑</button> : null}</div>
        </form>
        <ul className="surface-list">
          {users.map((user) => <li key={user.id}><div><strong>{user.display_name}</strong><p>{user.platform_role} · {departmentName(departments, user.primary_department_id)}</p></div><span>{user.is_active ? '启用' : '停用'}</span><button type="button" className="secondary" onClick={() => editUser(user)} disabled={busy}>编辑</button></li>)}
        </ul>
      </section>

      <section className="surface-card" aria-labelledby="admin-reset-title">
        <h2 id="admin-reset-title">临时凭据重置</h2>
        <p className="field-help">临时密码只用于本次提交，服务器不会返回或显示它。</p>
        <form onSubmit={(event) => { void submitReset(event) }}>
          <label>目标用户<select value={resetUserId} onChange={(event) => setResetUserId(event.target.value)} disabled={busy}><option value="">请选择</option>{users.map((user) => <option key={user.id} value={user.id}>{user.display_name}</option>)}</select></label>
          <label>临时密码<input type="password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} disabled={busy} autoComplete="new-password" /></label>
          <button type="submit" disabled={busy}>重置凭据</button>
        </form>
      </section>

      <section className="surface-card" aria-labelledby="admin-scenarios-title">
        <div className="section-heading"><h2 id="admin-scenarios-title">已安装场景状态</h2><span>服务器精确版本</span></div>
        {scenarios.length === 0 ? <p className="empty-note">当前组织没有已发布场景。</p> : <ul className="surface-list">{scenarios.map((scenario) => <li key={scenario.scenario_key}><div><strong>{scenario.display_name}</strong><p>{scenario.scenario_key} · {scenario.is_active ? '组织启用' : '组织停用'}</p></div><div>{scenario.versions.length === 0 ? <span>没有已发布版本</span> : scenario.versions.map((version) => <p key={scenarioVersionLabel(scenario.scenario_key, version.scenario_version)}>{scenarioVersionLabel(scenario.scenario_key, version.scenario_version)} · {dateText(version.published_at)} · {version.registry_present ? '代码已注册' : '代码未注册'} · {version.ready ? '可用' : '不可用'}</p>)}</div></li>)}</ul>}
      </section>
    </section>
  )
}
