import { ApiError } from '../api/client'

// 对应 design.md「交互状态」：写请求失败按原因区分；409 与"写入结果未知"是两回事。
export type CommandFailureKind =
  | 'session'
  | 'busy'
  | 'forbidden'
  | 'gone'
  | 'changed'
  | 'duplicate'
  | 'conflict'
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

export const FORBIDDEN_WRITE_TEXT = '当前账号没有执行此操作的权限。'
export const NOT_AVAILABLE_TEXT = '内容不存在或无权访问'
export const TOO_LARGE_TEXT = '文件超过大小上限，未上传。'
export const TYPE_NOT_ALLOWED_TEXT =
  '文件类型不被允许，或扩展名与类型不一致。允许：PDF、PNG、JPEG、DOCX、XLSX、PPTX、TXT、CSV。'

// 后端目前没有结构化的 409 原因字段，只能按 detail 文案分类（与 #83 的 classifyTeamFailure 同样存在文案耦合）：
// - 生命周期/并发：Concurrent Finding / ReviewCase / ActionItem transition（见 review_core/application）；
// - 重复关系：参与人、执行人已存在，后端以 IntegrityError 的文本返回（唯一约束冲突）；
// - 其余一律按无法分类的冲突处理。分类之外的 detail 不展示给用户（可能含数据库或角色细节）。
const CONCURRENT_TRANSITION = /^Concurrent (Finding|ReviewCase|ActionItem) transition$/
const DUPLICATE_RELATION = /duplicate key|unique ?constraint|UniqueViolation/i

export function classifyConflict(detail: string, label: string): Pick<CommandFailure, 'kind' | 'message'> {
  if (CONCURRENT_TRANSITION.test(detail)) {
    return { kind: 'changed', message: `数据已变化，正在获取最新状态。${label}未完成，请确认后重新操作。` }
  }
  if (DUPLICATE_RELATION.test(detail)) {
    return { kind: 'duplicate', message: `该成员已在列表中，或列表刚刚发生变化，${label}未完成。正在获取最新状态。` }
  }
  return { kind: 'conflict', message: `${label}与服务器当前状态冲突，未完成。正在获取最新状态，请确认后再试。` }
}

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
        // 不展示后端 detail（可能带出角色细节）。用户可能仍有读权限，所以只在操作区提示，并由页面重新校验主资源授权。
        return { kind: 'forbidden', message: FORBIDDEN_WRITE_TEXT, fieldErrors: {} }
      case 404:
        return { kind: 'gone', message: NOT_AVAILABLE_TEXT, fieldErrors: {} }
      case 409:
        return { ...classifyConflict(detail, label), fieldErrors: {} }
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
        // 只有 422 可以显示服务端 detail；其余 4xx（400、405 等）用中性文案，不泄露后端原文。
        if (error.status < 500) return { kind: 'rejected', message: `${label}未被服务器接受，请刷新后确认当前状态再试。`, fieldErrors: {} }
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
    failure.kind === 'duplicate' ||
    failure.kind === 'conflict' ||
    failure.kind === 'rejected' ||
    failure.kind === 'unknown-result'
  )
}

// 需要用户留意"可能已变化 / 未确认"的提示用警告色，明确拒绝用错误色。
export function failureAlertType(failure: CommandFailure): 'warning' | 'error' {
  return failure.kind === 'changed' || failure.kind === 'duplicate' || failure.kind === 'unknown-result' || failure.kind === 'retry-later'
    ? 'warning'
    : 'error'
}
