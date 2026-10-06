import { Form, Input, Radio } from 'antd'

import { FieldError } from '../ui/FieldError'

interface FieldProps {
  name: string
  label: string
  value: string
  onChange: (name: string, value: string) => void
  disabled?: boolean
  error?: string
}

// 发现项创建表单的场景字段：值由面板持有；id 供 422 后聚焦第一个错误字段。
export function findingCreateFieldId(name: string): string {
  return `finding-create-${name}`
}

function errorProps(id: string, error: string | undefined) {
  return error === undefined
    ? {}
    : {
        validateStatus: 'error' as const,
        help: <FieldError id={`${id}-error`}>{error}</FieldError>,
      }
}

export function FindingCreateTextField({
  name,
  label,
  value,
  onChange,
  disabled,
  error,
  placeholder,
}: FieldProps & { placeholder?: string }) {
  const id = findingCreateFieldId(name)
  return (
    <Form.Item label={label} htmlFor={id} {...errorProps(id, error)}>
      <Input
        id={id}
        aria-invalid={error === undefined ? undefined : true}
        aria-describedby={error === undefined ? undefined : `${id}-error`}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(name, event.target.value)}
        disabled={disabled}
      />
    </Form.Item>
  )
}

// 选项 ≤ 4 用 Radio.Group（design.md）。
export function FindingCreateRadioField({
  name,
  label,
  value,
  onChange,
  disabled,
  error,
  options,
}: FieldProps & { options: readonly { value: string; label: string }[] }) {
  const id = findingCreateFieldId(name)
  return (
    <Form.Item label={label} htmlFor={id} {...errorProps(id, error)}>
      <Radio.Group
        id={id}
        aria-label={label}
        aria-invalid={error === undefined ? undefined : true}
        aria-describedby={error === undefined ? undefined : `${id}-error`}
        value={value === '' ? undefined : value}
        onChange={(event) => onChange(name, event.target.value as string)}
        disabled={disabled}
        options={options.map((option) => ({ value: option.value, label: option.label }))}
      />
    </Form.Item>
  )
}
