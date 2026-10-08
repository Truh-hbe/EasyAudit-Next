import { Alert, Button, Checkbox, Drawer, Flex, Form, Grid, Input, Select } from 'antd'

import type { DepartmentResponse } from '../../api/admin'
import type { PlatformRole, UserResponse } from '../../api/contracts'
import { failureAlertType } from '../../product/commandFailure'
import type { CommandResult } from '../../product/commandFailure'
import { FieldError } from '../../ui/FieldError'
import { useConfirm } from '../../ui/useConfirm'
import { useDrawerCommand } from './useDrawerCommand'

export interface UserCreateInput {
  displayName: string
  loginName: string
  initialPassword: string
  platformRole: PlatformRole
  primaryDepartmentId: string | null
}

export interface UserUpdateInput {
  displayName: string
  platformRole: PlatformRole
  primaryDepartmentId: string | null
  isActive: boolean
}

interface UserDrawerProps {
  open: boolean
  // null 表示新建。
  user: UserResponse | null
  departments: DepartmentResponse[]
  onClose: () => void
  create: (input: UserCreateInput) => Promise<CommandResult>
  update: (user: UserResponse, input: UserUpdateInput) => Promise<CommandResult>
}

interface FormValues {
  display_name: string
  login_name: string
  initial_password: string
  platform_role: PlatformRole
  primary_department_id: string
  is_active: boolean
}

const required = (message: string) => ({
  validator: (_: unknown, value: string | undefined) =>
    (value ?? '').trim() === '' ? Promise.reject(<FieldError>{message}</FieldError>) : Promise.resolve(),
})

export function UserDrawer({ open, user, departments, onClose, create, update }: UserDrawerProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<FormValues>()
  const { confirm } = useConfirm()
  const { submitting, failure, submit, clearFieldErrors } = useDrawerCommand(open, onClose)
  const departmentOptions = [
    { value: '', label: '未分配' },
    ...departments.map((item) => ({ value: item.id, label: item.name })),
  ]

  function run(values: FormValues) {
    const displayName = values.display_name.trim()
    const primaryDepartmentId = values.primary_department_id === '' ? null : values.primary_department_id
    if (user === null) {
      const initialPassword = values.initial_password
      // 初始密码在请求发出前就从表单清掉，失败后需要重新输入。
      form.setFieldValue('initial_password', '')
      return submit(() =>
        create({
          displayName,
          loginName: values.login_name,
          initialPassword,
          platformRole: values.platform_role,
          primaryDepartmentId,
        }),
      )
    }
    return submit(() =>
      update(user, { displayName, platformRole: values.platform_role, primaryDepartmentId, isActive: values.is_active }),
    )
  }

  function onFinish(values: FormValues) {
    if (user !== null && user.is_active && !values.is_active) {
      confirm({
        title: '停用用户',
        content: `停用后，${user.display_name} 将无法登录，现有登录会话立即失效；之后可以重新启用。`,
        okText: '确认停用',
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: async () => {
          await run(values)
        },
      })
      return
    }
    void run(values)
  }

  return (
    <Drawer
      title={user === null ? '新建用户' : '编辑用户'}
      open={open}
      onClose={onClose}
      size={screens.sm ? 480 : '100%'}
      destroyOnHidden
      mask={{ closable: !submitting }}
      closable={!submitting}
      keyboard={!submitting}
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        preserve={false}
        disabled={submitting}
        initialValues={{
          display_name: user?.display_name ?? '',
          login_name: '',
          initial_password: '',
          platform_role: user?.platform_role ?? 'ordinary_user',
          primary_department_id: user?.primary_department_id ?? '',
          is_active: user?.is_active ?? true,
        }}
        onValuesChange={clearFieldErrors}
        onFinish={onFinish}
      >
        {failure === null || failure.message === '' ? null : (
          <Alert type={failureAlertType(failure)} showIcon title={failure.message} style={{ marginBottom: 16 }} />
        )}
        <Form.Item label="显示名称" name="display_name" rules={[required('请输入用户名称。')]}>
          <Input autoComplete="off" />
        </Form.Item>
        {user === null ? (
          <>
            <Form.Item label="登录名" name="login_name" rules={[required('请输入登录名。')]}>
              <Input autoComplete="off" />
            </Form.Item>
            <Form.Item
              label="初始密码"
              name="initial_password"
              extra="用户首次登录后必须修改密码。"
              rules={[
                {
                  validator: (_, value: string | undefined) =>
                    (value ?? '').length >= 12 && (value ?? '').length <= 1000
                      ? Promise.resolve()
                      : Promise.reject(<FieldError>初始密码需要 12 至 1000 个字符。</FieldError>),
                },
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
          </>
        ) : null}
        <Form.Item label="平台角色" name="platform_role">
          <Select
            options={[
              { value: 'ordinary_user', label: '普通用户' },
              { value: 'system_admin', label: '系统管理员' },
            ]}
          />
        </Form.Item>
        <Form.Item label="主要部门" name="primary_department_id">
          <Select options={departmentOptions} />
        </Form.Item>
        {user === null ? null : (
          <Form.Item name="is_active" valuePropName="checked">
            <Checkbox>用户启用</Checkbox>
          </Form.Item>
        )}
        <Flex justify="flex-end" gap={8}>
          <Button onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {user === null ? '创建用户' : '保存用户'}
          </Button>
        </Flex>
      </Form>
    </Drawer>
  )
}
