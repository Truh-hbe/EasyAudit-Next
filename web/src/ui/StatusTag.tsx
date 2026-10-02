import { Tag } from 'antd'

import type {
  ActionItemLifecycle,
  DeadlineBucket,
  FindingLifecycle,
  FindingSeverity,
  ReviewCaseLifecycle,
} from '../api/product'

type Tone =
  | 'neutral'
  | 'progress'
  | 'waiting'
  | 'done'
  | 'overdue'
  | 'severity-medium'
  | 'severity-high'
  | 'severity-critical'

interface StatusEntry {
  label: string
  tone: Tone
}

export type DeadlineStatus = Exclude<DeadlineBucket, 'later' | 'none'>

export function isDeadlineStatus(bucket: DeadlineBucket): bucket is DeadlineStatus {
  return bucket === 'overdue' || bucket === 'due_soon'
}

// 映射表以 Record<枚举类型, …> 声明：后端新增枚举值时这里会编译失败。
const reviewCaseStatus: Record<ReviewCaseLifecycle, StatusEntry> = {
  draft: { label: '草稿', tone: 'neutral' },
  scheduled: { label: '已排期', tone: 'neutral' },
  in_progress: { label: '审查中', tone: 'progress' },
  awaiting_closure: { label: '待关闭', tone: 'waiting' },
  closed: { label: '已关闭', tone: 'done' },
  cancelled: { label: '已取消', tone: 'neutral' },
}

const findingStatus: Record<FindingLifecycle, StatusEntry> = {
  open: { label: '待处理', tone: 'neutral' },
  rectifying: { label: '整改中', tone: 'progress' },
  verifying: { label: '待验证', tone: 'waiting' },
  closed: { label: '已关闭', tone: 'done' },
  voided: { label: '已作废', tone: 'neutral' },
}

const actionItemStatus: Record<ActionItemLifecycle, StatusEntry> = {
  todo: { label: '待开始', tone: 'neutral' },
  in_progress: { label: '执行中', tone: 'progress' },
  done: { label: '已完成', tone: 'done' },
  cancelled: { label: '已取消', tone: 'neutral' },
}

const deadlineStatus: Record<DeadlineStatus, StatusEntry> = {
  overdue: { label: '已逾期', tone: 'overdue' },
  due_soon: { label: '即将到期', tone: 'waiting' },
}

const severityStatus: Record<FindingSeverity, StatusEntry> = {
  low: { label: '低', tone: 'neutral' },
  medium: { label: '中', tone: 'severity-medium' },
  high: { label: '高', tone: 'severity-high' },
  critical: { label: '严重', tone: 'severity-critical' },
}

const tables = {
  reviewCase: reviewCaseStatus,
  finding: findingStatus,
  actionItem: actionItemStatus,
  deadline: deadlineStatus,
  severity: severityStatus,
} as const satisfies Record<string, Record<string, StatusEntry>>

export type StatusKind = keyof typeof tables

export interface StatusTagProps {
  kind: StatusKind
  // 运行时来自接口，可能是前端尚不认识的值。
  value: string
}

export function statusLabel(kind: StatusKind, value: string): string | null {
  const table: Record<string, StatusEntry> = tables[kind]
  return Object.hasOwn(table, value) ? (table[value]?.label ?? null) : null
}

export function StatusTag({ kind, value }: StatusTagProps) {
  const table: Record<string, StatusEntry> = tables[kind]
  const entry = Object.hasOwn(table, value) ? table[value] : undefined
  if (entry === undefined) {
    return (
      <>
        <Tag className="status-tag status-tag--neutral" variant="outlined">未知状态</Tag>
        <span className="status-tag-raw">{value}</span>
      </>
    )
  }
  return (
    <Tag className={`status-tag status-tag--${entry.tone}`} variant="outlined">
      {entry.label}
    </Tag>
  )
}
