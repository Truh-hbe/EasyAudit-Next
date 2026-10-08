import { ApiError, type FieldRuleError } from './client'

// 测试用：构造带结构化错误码的 ApiError，`detail` 固定为会被断言"不得出现"的英文。
export const ENGLISH_DETAIL = 'Backend English detail that must never reach the UI'

export function ruleError(
  status: number,
  code: string | null,
  params: Record<string, unknown> = {},
  errors: FieldRuleError[] = [],
  detail: string = ENGLISH_DETAIL,
): ApiError {
  return new ApiError(status, detail, null, { code, params, errors })
}
