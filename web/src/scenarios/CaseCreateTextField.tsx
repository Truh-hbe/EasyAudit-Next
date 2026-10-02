import { Form, Input } from 'antd'

import { FieldError } from '../ui/FieldError'

export interface CaseCreateTextFieldProps {
  name: string
  label: string
  value: string
  onChange: (name: string, value: string) => void
  disabled?: boolean
  error?: string
}

// 审查活动创建页的场景字段：值由页面持有（草稿随页面存活），id 供 422 后聚焦第一个错误字段。
export function caseCreateFieldId(name: string): string {
  return `case-create-${name}`
}

export function CaseCreateTextField({ name, label, value, onChange, disabled, error }: CaseCreateTextFieldProps) {
  const id = caseCreateFieldId(name)
  return (
    <Form.Item
      label={label}
      htmlFor={id}
      validateStatus={error === undefined ? undefined : 'error'}
      help={error === undefined ? undefined : <FieldError>{error}</FieldError>}
    >
      <Input id={id} value={value} onChange={(event) => onChange(name, event.target.value)} disabled={disabled} />
    </Form.Item>
  )
}
