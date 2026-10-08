import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Flex, Form, Input, Result, Select, Spin, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { useSession } from '../../app/auth/session'
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
import type { UserResponse } from '../../api/contracts'
import {
  BUSY_FAILURE,
  NOT_AVAILABLE_TEXT,
  classifyCommandFailure,
  failureAlertType,
  failureNeedsRefresh,
} from '../../product/commandFailure'
import type { CommandFailure, CommandResult } from '../../product/commandFailure'
import { formatDateTime } from '../../product/format'
import { FieldError } from '../../ui/FieldError'
import { InitialLoading } from '../../ui/InitialLoading'
import { ItemList } from '../../ui/ItemList'
import { PageHeader } from '../../ui/PageHeader'
import { useConfirm } from '../../ui/useConfirm'
import { DepartmentDrawer } from './DepartmentDrawer'
import type { DepartmentInput } from './DepartmentDrawer'
import { UserDrawer } from './UserDrawer'
import type { UserCreateInput, UserUpdateInput } from './UserDrawer'

interface AdminData {
  organization: OrganizationResponse
  departments: DepartmentResponse[]
  users: UserResponse[]
  scenarios: AdminScenarioStatusItem[]
}

type LoadState =
  | { status: 'loading' }
  // refreshing：写操作成功后在后台重新读取，旧内容保留。
  | { status: 'ready'; data: AdminData; refreshing: boolean }
  | { status: 'error'; message: string }
  // 401/403/404：保护内容整体移除，不显示后端 detail。
  | { status: 'denied' }

export function adminErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return `请求失败（状态码 ${error.status}）。`
  return error instanceof Error ? error.message : fallback
}

export function scenarioVersionLabel(scenarioKey: string, version: number): string {
  return `${scenarioKey}@${version}`
}

function isDenied(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404)
}

// 管理写操作沿用统一的失败分类：422 按错误码映射中文（不含用户输入，凭据类校验信息不会被回显）。
function adminFailure(error: unknown, label: string, unknownHint: string): CommandFailure {
  const failure = classifyCommandFailure(error, { label })
  if (failure.kind === 'unknown-result') return { ...failure, message: `${failure.message}${unknownHint}` }
  return failure
}

function departmentName(departments: DepartmentResponse[], id: string | null): string {
  if (id === null) return '未分配'
  return departments.find((department) => department.id === id)?.name ?? '未知部门'
}

const activeText = (active: boolean) => (active ? '启用' : '停用')

const SUCCESS_KEY = 'admin-command-success'

interface DrawerTarget {
  open: boolean
  id: string | null
  session: number
}

const CLOSED_DRAWER: DrawerTarget = { open: false, id: null, session: 0 }

function openDrawer(set: (update: (current: DrawerTarget) => DrawerTarget) => void, id: string | null) {
  set((current) => ({ open: true, id, session: current.session + 1 }))
}

interface ResetValues {
  user_id?: string
  temporary_password?: string
}

export function AdminPage() {
  const { message } = App.useApp()
  const { confirm, destroy: destroyConfirm } = useConfirm()
  const { state: sessionState } = useSession()
  const currentUserId = sessionState.status === 'authenticated' ? sessionState.user.id : null
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const requestSequence = useRef(0)
  const deniedRef = useRef(false)
  // 每次卸载换一个代次：卸载后仍在途的命令不再提示或刷新。
  const generationRef = useRef(0)
  const busyRef = useRef(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<CommandFailure | null>(null)
  // id 为 null 表示新建；session 每次打开递增，抽屉按它重挂载，保证每次打开都是新的编辑会话。
  const [departmentDrawer, setDepartmentDrawer] = useState<DrawerTarget>(CLOSED_DRAWER)
  const [userDrawer, setUserDrawer] = useState<DrawerTarget>(CLOSED_DRAWER)
  const dataRef = useRef<AdminData | null>(null)
  // 目标消失后的关闭动画期间沿用最后一次存在的对象，编辑不会退化成新建。
  const lastDepartment = useRef<DepartmentResponse | null>(null)
  const lastUser = useRef<UserResponse | null>(null)
  const [resetForm] = Form.useForm<ResetValues>()

  useEffect(
    () => () => {
      generationRef.current += 1
    },
    [],
  )

  useEffect(() => {
    if (deniedRef.current) return undefined
    const controller = new AbortController()
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setState((previous) =>
      previous.status === 'ready' ? { ...previous, refreshing: true } : previous.status === 'loading' ? previous : { status: 'loading' },
    )

    void Promise.all([
      getAdminOrganization(controller.signal),
      listAdminDepartments(controller.signal),
      listAdminUsers(controller.signal),
      getAdminScenarioStatus(controller.signal),
    ])
      .then(([organization, departments, users, scenarios]) => {
        if (controller.signal.aborted || requestSequence.current !== sequence || deniedRef.current) return
        setState({ status: 'ready', data: { organization, departments, users, scenarios: scenarios.items }, refreshing: false })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestSequence.current !== sequence || deniedRef.current) return
        if (isDenied(error)) {
          deniedRef.current = true
          message.destroy(SUCCESS_KEY)
          setNotice(null)
          setDepartmentDrawer((current) => ({ ...current, open: false }))
          setUserDrawer((current) => ({ ...current, open: false }))
          setState({ status: 'denied' })
          return
        }
        // 重新读取失败不用旧数据兜底；成功提示随旧内容一起消失，未确认结果的提示保留给管理员核对。
        message.destroy(SUCCESS_KEY)
        setNotice((current) => (current?.kind === 'unknown-result' ? current : null))
        setState({ status: 'error', message: adminErrorMessage(error, '管理员数据读取失败。') })
      })

    return () => controller.abort()
  }, [revision])

  const refresh = () => setRevision((value) => value + 1)

  dataRef.current = state.status === 'ready' ? state.data : null
  // 受保护内容被移除（读取失败、无权访问）时，已打开的确认框随之销毁。
  useEffect(() => {
    if (state.status !== 'ready') destroyConfirm()
  }, [state.status, destroyConfirm])

  // 写操作：不自动重放；冲突、权限变化或结果未知时只重新读取，由管理员核对后再决定是否重试。
  async function runCommand(
    label: string,
    command: () => Promise<unknown>,
    options: { successText: string; unknownHint?: string },
  ): Promise<CommandResult> {
    if (busyRef.current || deniedRef.current) return { ok: false, failure: BUSY_FAILURE }
    const generation = generationRef.current
    busyRef.current = true
    setBusy(true)
    let result: CommandResult
    try {
      await command()
      result = { ok: true }
    } catch (error) {
      result = { ok: false, failure: adminFailure(error, label, options.unknownHint ?? '') }
    }
    if (generationRef.current !== generation) return result
    busyRef.current = false
    setBusy(false)
    if (deniedRef.current) return result
    if (result.ok) {
      void message.success({ key: SUCCESS_KEY, content: options.successText })
      refresh()
    } else {
      // 结果未知的提示留在页面级：之后重新读取失败、抽屉被卸载时，管理员仍能看到要先核对。
      if (result.failure.kind === 'unknown-result') setNotice(result.failure)
      if (failureNeedsRefresh(result.failure)) refresh()
    }
    return result
  }

  const saveDepartment = (department: DepartmentResponse | null) => (input: DepartmentInput) => {
    setNotice(null)
    return department === null
      ? runCommand('创建部门', () => createAdminDepartment({ name: input.name, parent_id: input.parentId }), { successText: '部门已创建。' })
      : runCommand(
          '保存部门',
          () => updateAdminDepartment(department.id, { name: input.name, parent_id: input.parentId, is_active: input.isActive }),
          { successText: '部门已更新。' },
        )
  }

  function createUser(input: UserCreateInput) {
    setNotice(null)
    return runCommand(
      '创建用户',
      () =>
        createAdminUser({
          display_name: input.displayName,
          login_name: input.loginName,
          initial_password: input.initialPassword,
          platform_role: input.platformRole,
          primary_department_id: input.primaryDepartmentId,
          must_change_password: true,
        }),
      { successText: '用户已创建。', unknownHint: '初始密码已清空，重试需重新输入。' },
    )
  }

  function updateUser(user: UserResponse, input: UserUpdateInput) {
    setNotice(null)
    return runCommand(
      '保存用户',
      () =>
        updateAdminUser(user.id, {
          display_name: input.displayName,
          platform_role: input.platformRole,
          primary_department_id: input.primaryDepartmentId,
          is_active: input.isActive,
        }),
      { successText: '用户已更新。' },
    )
  }

  function requestReset(users: UserResponse[], values: ResetValues) {
    const target = users.find((user) => user.id === values.user_id)
    const temporaryPassword = values.temporary_password ?? ''
    if (target === undefined) return
    confirm({
      title: '重置凭据',
      content: `重置后，${target.display_name} 的现有密码立即失效，已登录的会话被注销；该用户下次登录必须使用临时密码并修改密码。`,
      okText: '确认重置',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        // 确认框打开期间内容被移除或目标用户已不存在：不发请求。
        if (deniedRef.current || dataRef.current?.users.some((user) => user.id === target.id) !== true) return
        // 临时密码在请求发出前就从表单清掉，不保留用于自动重试。
        resetForm.setFieldValue('temporary_password', '')
        setNotice(null)
        const result = await runCommand(
          '重置凭据',
          () => resetAdminUserCredential(target.id, { temporary_password: temporaryPassword }),
          { successText: '临时凭据已重置；目标用户下次登录必须修改密码。', unknownHint: '临时密码已清空，重试需重新输入。' },
        )
        if (!result.ok && result.failure.kind !== 'busy' && result.failure.kind !== 'session' && result.failure.message !== '') {
          setNotice(result.failure)
        }
      },
    })
  }

  const noticeAlert =
    notice === null ? null : (
      <Alert type={failureAlertType(notice)} showIcon title={notice.message} closable={{ onClose: () => setNotice(null) }} />
    )

  if (state.status === 'loading') {
    return (
      <Flex vertical gap={16} aria-busy="true">
        <PageHeader title="管理设置" titleId="admin-title" />
        <Card>
          <InitialLoading label="正在读取管理员数据" rows={6} />
        </Card>
      </Flex>
    )
  }

  if (state.status === 'denied') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="管理设置" titleId="admin-title" />
        <Card>
          <Result status="404" title={NOT_AVAILABLE_TEXT} />
        </Card>
      </Flex>
    )
  }

  if (state.status === 'error') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="管理设置" titleId="admin-title" />
        {noticeAlert}
        <Alert
          type="error"
          showIcon
          title={state.message}
          action={<Button size="small" onClick={() => { setNotice(null); refresh() }}>重新加载</Button>}
        />
      </Flex>
    )
  }

  const { organization, departments, users, scenarios } = state.data

  // 抽屉目标按 id 从最新数据派生；刷新后目标消失则抽屉关闭。
  const editingDepartment = departmentDrawer.id === null ? undefined : departments.find((item) => item.id === departmentDrawer.id)
  const editingUser = userDrawer.id === null ? undefined : users.find((item) => item.id === userDrawer.id)
  if (editingDepartment !== undefined) lastDepartment.current = editingDepartment
  if (editingUser !== undefined) lastUser.current = editingUser
  const departmentTarget = departmentDrawer.id === null ? null : (editingDepartment ?? lastDepartment.current)
  const userTarget = userDrawer.id === null ? null : (editingUser ?? lastUser.current)

  const departmentColumns: TableColumnsType<DepartmentResponse> = [
    { title: '部门名称', key: 'name', render: (_value: unknown, item) => <strong>{item.name}</strong> },
    { title: '上级部门', key: 'parent', render: (_value: unknown, item) => departmentName(departments, item.parent_id) },
    { title: '状态', key: 'status', render: (_value: unknown, item) => activeText(item.is_active) },
    {
      title: '操作',
      key: 'operations',
      fixed: 'right',
      width: 96,
      render: (_value: unknown, item) => (
        <Button
          size="small"
          icon={<EditOutlined aria-hidden />}
          aria-label={`编辑部门 ${item.name}`}
          disabled={busy}
          onClick={() => { setNotice(null); openDrawer(setDepartmentDrawer, item.id) }}
        >编辑</Button>
      ),
    },
  ]

  const userColumns: TableColumnsType<UserResponse> = [
    { title: '显示名称', key: 'name', render: (_value: unknown, item) => <strong>{item.display_name}</strong> },
    { title: '平台角色', key: 'role', render: (_value: unknown, item) => (item.platform_role === 'system_admin' ? '系统管理员' : '普通用户') },
    { title: '主要部门', key: 'department', render: (_value: unknown, item) => departmentName(departments, item.primary_department_id) },
    { title: '状态', key: 'status', render: (_value: unknown, item) => activeText(item.is_active) },
    {
      title: '操作',
      key: 'operations',
      fixed: 'right',
      width: 96,
      render: (_value: unknown, item) => (
        <Button
          size="small"
          icon={<EditOutlined aria-hidden />}
          aria-label={`编辑用户 ${item.display_name}`}
          disabled={busy}
          onClick={() => { setNotice(null); openDrawer(setUserDrawer, item.id) }}
        >编辑</Button>
      ),
    },
  ]

  return (
    <Flex vertical gap={16} component="article" aria-labelledby="admin-title">
      <PageHeader
        title="管理设置"
        titleId="admin-title"
        meta={<Typography.Text type="secondary">{`${organization.name} · ${activeText(organization.is_active)}`}</Typography.Text>}
      />

      {noticeAlert}

      <Spin spinning={state.refreshing} description="正在刷新">
        <Flex vertical gap={16}>
          <section aria-labelledby="admin-departments-title">
            <Card
              title={<h2 id="admin-departments-title">部门</h2>}
              extra={
                <Flex align="center" gap={12}>
                  <Typography.Text type="secondary">{`${departments.length} 个`}</Typography.Text>
                  <Button
                    icon={<PlusOutlined aria-hidden />}
                    disabled={busy}
                    onClick={() => { setNotice(null); openDrawer(setDepartmentDrawer, null) }}
                  >新建部门</Button>
                </Flex>
              }
            >
              <Table<DepartmentResponse>
                size="middle"
                rowKey="id"
                columns={departmentColumns}
                dataSource={departments}
                pagination={false}
                scroll={{ x: 'max-content' }}
              />
            </Card>
          </section>

          <section aria-labelledby="admin-users-title">
            <Card
              title={<h2 id="admin-users-title">用户</h2>}
              extra={
                <Flex align="center" gap={12}>
                  <Typography.Text type="secondary">{`${users.length} 个`}</Typography.Text>
                  <Button
                    icon={<PlusOutlined aria-hidden />}
                    disabled={busy}
                    onClick={() => { setNotice(null); openDrawer(setUserDrawer, null) }}
                  >新建用户</Button>
                </Flex>
              }
            >
              <Table<UserResponse>
                size="middle"
                rowKey="id"
                columns={userColumns}
                dataSource={users}
                pagination={false}
                scroll={{ x: 'max-content' }}
              />
            </Card>
          </section>

          <section aria-labelledby="admin-reset-title">
            <Card title={<h2 id="admin-reset-title">临时凭据重置</h2>}>
              <Typography.Paragraph type="secondary">临时密码只用于本次提交，服务器不会返回或显示它。</Typography.Paragraph>
              <Form<ResetValues>
                form={resetForm}
                name="reset"
                layout="vertical"
                requiredMark={false}
                disabled={busy}
                style={{ maxWidth: 480 }}
                onFinish={(values) => requestReset(users, values)}
              >
                <Form.Item
                  label="目标用户"
                  name="user_id"
                  rules={[{ validator: (_, value: string | undefined) => (value === undefined || value === '' ? Promise.reject(<FieldError>请选择目标用户。</FieldError>) : Promise.resolve()) }]}
                >
                  <Select placeholder="请选择" options={users.map((user) => ({ value: user.id, label: user.display_name }))} />
                </Form.Item>
                <Form.Item
                  label="临时密码"
                  name="temporary_password"
                  rules={[
                    {
                      validator: (_, value: string | undefined) =>
                        (value ?? '').length >= 12 && (value ?? '').length <= 1000
                          ? Promise.resolve()
                          : Promise.reject(<FieldError>临时密码需要 12 至 1000 个字符。</FieldError>),
                    },
                  ]}
                >
                  <Input.Password autoComplete="new-password" style={{ maxWidth: '100%' }} />
                </Form.Item>
                <Button type="primary" danger htmlType="submit" loading={busy}>重置凭据</Button>
              </Form>
            </Card>
          </section>

          <section aria-labelledby="admin-scenarios-title">
            <Card
              title={<h2 id="admin-scenarios-title">已安装场景状态</h2>}
              extra={<Typography.Text type="secondary">服务器精确版本</Typography.Text>}
            >
              <ItemList
                label="已安装场景"
                emptyText="当前组织没有已发布场景。"
                items={scenarios.map((scenario) => ({
                  key: scenario.scenario_key,
                  content: (
                    <Flex vertical gap={4}>
                      <Flex align="baseline" wrap gap={8}>
                        <strong>{scenario.display_name}</strong>
                        <Typography.Text type="secondary">{scenario.is_active ? '组织启用' : '组织停用'}</Typography.Text>
                      </Flex>
                      {scenario.versions.length === 0 ? (
                        <Typography.Text type="secondary">没有已发布版本</Typography.Text>
                      ) : (
                        scenario.versions.map((version) => (
                          <Typography.Text key={scenarioVersionLabel(scenario.scenario_key, version.scenario_version)}>
                            {`${scenarioVersionLabel(scenario.scenario_key, version.scenario_version)} · ${formatDateTime(version.published_at)} · ${version.registry_present ? '代码已注册' : '代码未注册'} · ${version.ready ? '可用' : '不可用'}`}
                          </Typography.Text>
                        ))
                      )}
                    </Flex>
                  ),
                }))}
              />
            </Card>
          </section>
        </Flex>
      </Spin>

      <DepartmentDrawer
        key={`department-${departmentDrawer.session}`}
        open={departmentDrawer.open && (departmentDrawer.id === null || editingDepartment !== undefined)}
        department={departmentTarget}
        departments={departments}
        onClose={() => setDepartmentDrawer((current) => ({ ...current, open: false }))}
        save={saveDepartment(departmentTarget)}
      />
      <UserDrawer
        key={`user-${userDrawer.session}`}
        open={userDrawer.open && (userDrawer.id === null || editingUser !== undefined)}
        user={userTarget}
        currentUserId={currentUserId}
        departments={departments}
        onClose={() => setUserDrawer((current) => ({ ...current, open: false }))}
        create={createUser}
        update={updateUser}
      />
    </Flex>
  )
}

