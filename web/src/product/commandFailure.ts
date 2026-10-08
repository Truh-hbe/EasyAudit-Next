import { ApiError } from '../api/client'
import { fieldMessage, ruleMessage } from './ruleMessages'

// 对应 design.md「交互状态」：写请求失败按原因区分；409 与"写入结果未知"是两回事。
export type CommandFailureKind =
  | 'session'
  | 'busy'
  | 'forbidden'
  | 'gone'
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

// 409 的响应体目前没有结构化原因（后续单独加码），所以不按 detail 区分，也不显示 detail：
// 并发变化、重复关系、其他冲突都提示"可能已变化"，并由调用方重新读取最新状态。
export function conflictMessage(label: string): string {
  return `数据已变化，正在获取最新状态。${label}未完成，请确认当前状态后再操作；也可能是该操作与现有数据冲突。`
}

export const BUSY_FAILURE: CommandFailure = { kind: 'busy', message: '', fieldErrors: {} }

function waitText(error: ApiError): string {
  return error.retryAfter === null ? '稍后' : `${error.retryAfter} 秒后`
}

// 字段名 → 界面中文标签。只有出现在这里的字段，服务端字段错误才会挂到对应表单项。
export type FieldLabels = Readonly<Record<string, string>>

// 422：字段错误按 `errors[]` 的 field/code 生成中文挂到字段；页面级提示按 code 映射。
// 不读取、不显示 `detail`；未知 code 用通用中文。
function classifyRejection(error: ApiError, label: string, fields: FieldLabels): Pick<CommandFailure, 'message' | 'fieldErrors'> {
  const fieldErrors: Record<string, string> = {}
  let unmatched = false
  for (const item of error.errors) {
    const fieldLabel = Object.hasOwn(fields, item.field) ? fields[item.field] : undefined
    if (fieldLabel === undefined) {
      unmatched = true
    } else if (fieldErrors[item.field] === undefined) {
      fieldErrors[item.field] = fieldMessage(item.code, item.field, fieldLabel, item.params)
    }
  }
  const fieldsOnly = error.code === 'request.invalid' && Object.keys(fieldErrors).length > 0 && !unmatched
  return { fieldErrors, message: fieldsOnly ? '' : ruleMessage(error.code, error.params, label) }
}

export interface ClassifyOptions {
  // 操作名称，用于生成提示，如 "开始整改项"。
  label: string
  // 调用方能显示服务端字段提示的字段（字段名 → 中文标签）。
  fields?: FieldLabels
  // 上传请求：413/415 与连接中断的措辞不同，不会自动重传。
  upload?: boolean
}

export function classifyCommandFailure(error: unknown, options: ClassifyOptions): CommandFailure {
  const { label, fields = {}, upload = false } = options
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return { kind: 'session', message: '', fieldErrors: {} }
      case 403:
        // 不展示后端 detail（可能带出角色细节）。用户可能仍有读权限，所以只在操作区提示，并由页面重新校验主资源授权。
        return { kind: 'forbidden', message: FORBIDDEN_WRITE_TEXT, fieldErrors: {} }
      case 404:
        return { kind: 'gone', message: NOT_AVAILABLE_TEXT, fieldErrors: {} }
      case 409:
        return { kind: 'conflict', message: conflictMessage(label), fieldErrors: {} }
      case 413:
        return { kind: 'too-large', message: TOO_LARGE_TEXT, fieldErrors: {} }
      case 415:
        return { kind: 'type-not-allowed', message: TYPE_NOT_ALLOWED_TEXT, fieldErrors: {} }
      case 422:
        return { kind: 'rejected', ...classifyRejection(error, label, fields) }
      case 429:
      case 503:
        return {
          kind: 'retry-later',
          message: `服务暂时繁忙，${label}未完成。请${waitText(error)}手动重试。`,
          fieldErrors: {},
        }
      default:
        // 其余 4xx（400、405 等）用中性文案；任何状态码都不显示后端 detail。
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
    failure.kind === 'conflict' ||
    failure.kind === 'rejected' ||
    failure.kind === 'unknown-result'
  )
}

// 需要用户留意"可能已变化 / 未确认"的提示用警告色，明确拒绝用错误色。
export function failureAlertType(failure: CommandFailure): 'warning' | 'error' {
  return failure.kind === 'conflict' || failure.kind === 'unknown-result' || failure.kind === 'retry-later'
    ? 'warning'
    : 'error'
}
