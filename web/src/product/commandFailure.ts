import { ApiError } from '../api/client'

// 对应 design.md「交互状态」：写请求失败按原因区分；409 与"写入结果未知"是两回事。
export type CommandFailureKind =
  | 'session'
  | 'busy'
  | 'forbidden'
  | 'gone'
  | 'changed'
  | 'retry-later'
  | 'too-large'
  | 'type-not-allowed'
  | 'rejected'
  | 'unknown-result'

export interface CommandFailure {
  kind: CommandFailureKind
  // 页面级提示；为空串表示没有需要展示的文字（Session 失效、已全部对应到字段）。
  message: string
  // 能对应到表单字段的 422 提示，按字段名索引。
  fieldErrors: Record<string, string>
}

export type CommandResult = { ok: true } | { ok: false; failure: CommandFailure }

export const NOT_AVAILABLE_TEXT = '内容不存在或无权访问'
export const TOO_LARGE_TEXT = '文件超过大小上限，未上传。'
export const TYPE_NOT_ALLOWED_TEXT =
  '文件类型不被允许，或扩展名与类型不一致。允许：PDF、PNG、JPEG、DOCX、XLSX、PPTX、TXT、CSV。'

export const BUSY_FAILURE: CommandFailure = { kind: 'busy', message: '', fieldErrors: {} }

function waitText(error: ApiError): string {
  return error.retryAfter === null ? '稍后' : `${error.retryAfter} 秒后`
}

// 422 的服务端提示是以 "; " 连接的英文片段，片段以字段名开头（如 `root_cause is required`）。
// 能对应字段的挂到字段上，其余合并为页面级提示；原样保留服务端文本，不做改写。
function splitFieldErrors(detail: string, fields: readonly string[]): Pick<CommandFailure, 'message' | 'fieldErrors'> {
  const fieldErrors: Record<string, string> = {}
  const rest: string[] = []
  for (const segment of detail.split('; ')) {
    const field = fields.find((name) => new RegExp(`(^|[^a-z0-9_])${name}([^a-z0-9_]|$)`).test(segment))
    if (field === undefined) {
      rest.push(segment)
    } else {
      fieldErrors[field] = fieldErrors[field] === undefined ? segment : `${fieldErrors[field]}; ${segment}`
    }
  }
  return { fieldErrors, message: rest.join('; ') }
}

export interface ClassifyOptions {
  // 操作名称，用于生成提示，如 "开始整改项"。
  label: string
  // 调用方能显示服务端字段提示的字段名。
  fields?: readonly string[]
  // 上传请求：413/415 与连接中断的措辞不同，不会自动重传。
  upload?: boolean
}

export function classifyCommandFailure(error: unknown, options: ClassifyOptions): CommandFailure {
  const { label, fields = [], upload = false } = options
  if (error instanceof ApiError) {
    const detail = error.detail
    switch (error.status) {
      case 401:
        return { kind: 'session', message: '', fieldErrors: {} }
      case 403:
        return { kind: 'forbidden', message: `当前用户没有权限${label}：${detail}`, fieldErrors: {} }
      case 404:
        return { kind: 'gone', message: NOT_AVAILABLE_TEXT, fieldErrors: {} }
      case 409:
        return {
          kind: 'changed',
          message: `数据已变化，正在获取最新状态。${label}未完成，请确认后重新操作。（${detail}）`,
          fieldErrors: {},
        }
      case 413:
        return { kind: 'too-large', message: TOO_LARGE_TEXT, fieldErrors: {} }
      case 415:
        return { kind: 'type-not-allowed', message: TYPE_NOT_ALLOWED_TEXT, fieldErrors: {} }
      case 422: {
        const split = splitFieldErrors(detail, fields)
        return {
          kind: 'rejected',
          message: upload && split.message !== '' ? `无法登记证据：${split.message}` : split.message,
          fieldErrors: split.fieldErrors,
        }
      }
      case 429:
      case 503:
        return {
          kind: 'retry-later',
          message: `服务暂时繁忙，${label}未完成。请${waitText(error)}手动重试。`,
          fieldErrors: {},
        }
      default:
        if (error.status < 500) return { kind: 'rejected', message: detail, fieldErrors: {} }
    }
  }
  return {
    kind: 'unknown-result',
    message: upload
      ? `${label}中断，服务器未确认是否成功。文件可能超过大小上限，或网络中断；请核对已上传的证据后手动重试。`
      : `未确认${label}是否成功，已重新读取最新状态供核对；如未生效可再次操作。`,
    fieldErrors: {},
  }
}

// 写失败后需要重新读取：权限或状态可能已变化，或者结果未知需要核对。
export function failureNeedsRefresh(failure: CommandFailure): boolean {
  return (
    failure.kind === 'forbidden' ||
    failure.kind === 'gone' ||
    failure.kind === 'changed' ||
    failure.kind === 'rejected' ||
    failure.kind === 'unknown-result'
  )
}

// 需要用户留意"可能已变化 / 未确认"的提示用警告色，明确拒绝用错误色。
export function failureAlertType(failure: CommandFailure): 'warning' | 'error' {
  return failure.kind === 'changed' || failure.kind === 'unknown-result' || failure.kind === 'retry-later'
    ? 'warning'
    : 'error'
}
