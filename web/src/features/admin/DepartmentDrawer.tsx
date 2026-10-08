import { Alert, Button, Checkbox, Drawer, Flex, Form, Grid, Input, Select } from 'antd'

import type { DepartmentResponse } from '../../api/admin'
import { failureAlertType } from '../../product/commandFailure'
import type { CommandResult } from '../../product/commandFailure'
import { FieldError } from '../../ui/FieldError'
import { useDrawerCommand } from './useDrawerCommand'

export interface DepartmentInput {
  name: string
  parentId: string | null
  isActive: boolean
}

interface DepartmentDrawerProps {
  open: boolean
  // null 表示新建。
  department: DepartmentResponse | null
  departments: DepartmentResponse[]
  onClose: () => void
  save: (input: DepartmentInput) => Promise<CommandResult>
}

interface FormValues {
  name: string
  parent_id: string
  is_active: boolean
}

export function DepartmentDrawer({ open, department, departments, onClose, save }: DepartmentDrawerProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<FormValues>()
  const { submitting, failure, submit, clearFieldErrors } = useDrawerCommand(open, onClose)
  const parentOptions = [
    { value: '', label: '无' },
    ...departments.filter((item) => item.id !== department?.id).map((item) => ({ value: item.id, label: item.name })),
  ]

  return (
    <Drawer
      title={department === null ? '新建部门' : '编辑部门'}
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
        initialValues={{ name: department?.name ?? '', parent_id: department?.parent_id ?? '', is_active: department?.is_active ?? true }}
        onValuesChange={clearFieldErrors}
        onFinish={(values) =>
          void submit(() =>
            save({ name: values.name.trim(), parentId: values.parent_id === '' ? null : values.parent_id, isActive: values.is_active }),
          )
        }
      >
        {failure === null || failure.message === '' ? null : (
          <Alert type={failureAlertType(failure)} showIcon title={failure.message} style={{ marginBottom: 16 }} />
        )}
        <Form.Item
          label="部门名称"
          name="name"
          rules={[
            {
              validator: (_, value: string | undefined) =>
                (value ?? '').trim() === '' ? Promise.reject(<FieldError>请输入部门名称。</FieldError>) : Promise.resolve(),
            },
          ]}
        >
          <Input autoComplete="off" />
        </Form.Item>
        <Form.Item label="上级部门" name="parent_id">
          <Select options={parentOptions} />
        </Form.Item>
        {department === null ? null : (
          <Form.Item name="is_active" valuePropName="checked">
            <Checkbox>部门启用</Checkbox>
          </Form.Item>
        )}
        <Flex justify="flex-end" gap={8}>
          <Button onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {department === null ? '创建部门' : '保存部门'}
          </Button>
        </Flex>
      </Form>
    </Drawer>
  )
}
