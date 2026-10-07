import type { SubmissionResponse } from '../api/product'
import { submissionPurposeName } from '../product/terms'
import type { ScenarioSubmissionField, ScenarioSubmissionView } from './registry'

const MAX_EXTRA_KEY_LENGTH = 40

function textOf(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value : null
}

// 未知字段只作为纯文本展示：标量转字符串，结构化值不展开，避免把技术载荷原样倒给用户。
function extraFields(payload: Record<string, unknown>, consumed: readonly string[]): ScenarioSubmissionField[] {
  const fields: ScenarioSubmissionField[] = []
  for (const [key, value] of Object.entries(payload)) {
    if (consumed.includes(key) || value === null || value === undefined) continue
    let text: string
    if (typeof value === 'string') {
      if (value.trim().length === 0) continue
      text = value
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      text = String(value)
    } else {
      text = '（结构化内容，此处不展示）'
    }
    const shownKey = key.length > MAX_EXTRA_KEY_LENGTH ? `${key.slice(0, MAX_EXTRA_KEY_LENGTH)}…` : key
    fields.push({ key: `extra:${key}`, label: `其他内容（${shownKey}）`, value: text })
  }
  return fields
}

function known(key: string, label: string, value: unknown): ScenarioSubmissionField[] {
  const text = textOf(value)
  return text === null ? [] : [{ key, label, value: text }]
}

// 整改计划/完成说明与验证通过/驳回的标准提交形态（两个已支持场景相同）：
// 整改 { stage: 'plan', root_cause } | { stage: 'completion', comment }；验证 { result: 'approved' | 'rejected', comment }。
export function standardDescribeSubmission(submission: SubmissionResponse): ScenarioSubmissionView {
  const payload = submission.payload ?? {}
  if (submission.purpose === 'rectification' && payload.stage === 'plan') {
    return {
      heading: '整改计划',
      outcome: null,
      fields: known('root_cause', '根本原因', payload.root_cause),
      extras: extraFields(payload, ['stage', 'root_cause']),
    }
  }
  if (submission.purpose === 'rectification' && payload.stage === 'completion') {
    return {
      heading: '整改完成说明',
      outcome: null,
      fields: known('comment', '整改完成说明', payload.comment),
      extras: extraFields(payload, ['stage', 'comment']),
    }
  }
  if (submission.purpose === 'verification' && payload.result === 'approved') {
    return {
      heading: '验证通过',
      outcome: 'approved',
      fields: known('comment', '验证意见', payload.comment),
      extras: extraFields(payload, ['result', 'comment']),
    }
  }
  if (submission.purpose === 'verification' && payload.result === 'rejected') {
    return {
      heading: '验证驳回',
      outcome: 'rejected',
      fields: known('comment', '驳回原因', payload.comment),
      extras: extraFields(payload, ['result', 'comment']),
    }
  }
  return {
    heading: submissionPurposeName(submission.purpose),
    outcome: null,
    fields: [],
    extras: extraFields(payload, ['stage', 'result']),
  }
}
