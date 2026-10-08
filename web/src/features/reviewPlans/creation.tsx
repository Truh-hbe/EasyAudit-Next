import { ApiError, isIdempotencyKeyReuse } from '../../api/client'
import { classifyCommandFailure, type FieldLabels } from '../../product/commandFailure'
import { FieldError } from '../../ui/FieldError'

export interface RejectionView {
  // 能对应到表单字段的服务端提示，按字段名索引。
  fieldErrors: Record<string, string>
  // 无法对应字段的提示；为空串表示全部已映射到字段。
  message: string
}

// 5xx 无法确认服务器是否已提交，按"结果未知"处理；其余 ApiError 是服务器明确拒绝。
export function isDefinitiveCreationRejection(error: unknown): boolean {
  return error instanceof ApiError && error.status < 500
}

export const IDEMPOTENCY_KEY_REUSE_MESSAGE =
  '当前内容与之前提交的创建请求不一致。请刷新页面，确认内容后再试。'

function waitHint(error: ApiError): string {
  if ((error.status !== 429 && error.status !== 503) || error.retryAfter === null || error.retryAfter <= 0) {
    return ''
  }
  return `请约 ${error.retryAfter} 秒后手动重试。`
}

// 服务器明确拒绝创建请求：422 按错误码映射中文并挂到字段；任何状态码都不显示后端 detail。
// `label` 是操作名（如 "创建审查计划"），`fields` 是字段名 → 中文标签。
export function describeRejection(error: unknown, label: string, fields: FieldLabels): RejectionView {
  if (isIdempotencyKeyReuse(error)) return { fieldErrors: {}, message: IDEMPOTENCY_KEY_REUSE_MESSAGE }
  if (!(error instanceof ApiError)) return { fieldErrors: {}, message: `${label}被服务器拒绝，请修正后重试。` }
  if (error.status === 409) {
    return { fieldErrors: {}, message: `${label}与服务器当前状态冲突，未完成。请刷新页面确认后再试。` }
  }
  const failure = classifyCommandFailure(error, { label, fields })
  return { fieldErrors: failure.fieldErrors, message: failure.message }
}

// 网络中断、响应丢失或 5xx：不知道服务器是否已创建。重试沿用原幂等键，不自动重放。
export function unknownOutcomeMessage(subject: string, retryLabel: string, error: unknown): string {
  const wait = error instanceof ApiError ? waitHint(error) : ''
  return [
    `${subject}创建结果未知：未确认是否成功。`,
    `可以点“${retryLabel}”：重新提交会沿用这次创建请求，不会重复创建；也可以在新标签页中打开审查活动列表核对，本页的内容和这次创建请求会保留。系统不会自动再次提交。`,
    wait,
  ].filter((part) => part !== '').join('')
}
// 服务端 422 对应到字段的提示：覆盖该 Form.Item 的校验状态，用户修改字段后由页面清除。
export function serverError(errors: Record<string, string | undefined>, name: string) {
  const text = errors[name]
  return text === undefined
    ? {}
    : { validateStatus: 'error' as const, help: <FieldError>{text}</FieldError> }
}

export function clearedErrors(
  errors: Record<string, string>,
  changed: Record<string, unknown>,
): Record<string, string> {
  return Object.fromEntries(Object.entries(errors).filter(([name]) => !(name in changed)))
}
