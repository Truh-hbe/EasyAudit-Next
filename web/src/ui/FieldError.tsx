import type { ReactNode } from 'react'

// 表单校验提示文字：antd 默认错误色（#ff4d4f）白底仅 3.3:1，这里改用达标的色板档位。
export function FieldError({ children }: { children: ReactNode }) {
  return <span className="field-error-text">{children}</span>
}
