import type { AssignmentRole, SubmissionPurpose } from '../api/product'
// 领域概念的界面用语（docs/design.md「文案与术语」）。接口类型、枚举值和路由保持原名。
const SCENARIO_NAMES: Record<string, string> = {
  process_review: '过程审查',
  compliance_review: '合规审查',
}

export function scenarioName(scenarioKey: string): string {
  return Object.hasOwn(SCENARIO_NAMES, scenarioKey)
    ? (SCENARIO_NAMES[scenarioKey] ?? '未知场景')
    : '未知场景'
}

// 次级信息：精确场景版本，供排障使用。
export function scenarioVersionText(scenarioKey: string, scenarioVersion: number): string {
  return `${scenarioKey}@${scenarioVersion}`
}

const CASE_ROLE_NAMES: Record<string, string> = {
  lead: '审查组长',
  auditor: '审查员',
  reviewer: '复核员',
  observer: '观察员',
}

// 审查活动成员的角色名；未知角色键不直接展示。
export function caseRoleName(roleKey: string): string {
  return Object.hasOwn(CASE_ROLE_NAMES, roleKey)
    ? (CASE_ROLE_NAMES[roleKey] ?? '未知角色')
    : '未知角色'
}

const PARTICIPANT_ROLE_NAMES: Record<string, string> = {
  owner: '整改负责人',
  collaborator: '协作者',
  responsible_department: '责任部门',
}

// 发现项参与方的角色名；未知角色键不直接展示。
export function participantRoleName(roleKey: string): string {
  return Object.hasOwn(PARTICIPANT_ROLE_NAMES, roleKey)
    ? (PARTICIPANT_ROLE_NAMES[roleKey] ?? '未知角色')
    : '未知角色'
}

const ASSIGNMENT_ROLE_NAMES: Record<AssignmentRole, string> = {
  primary: '主要执行人',
  collaborator: '协作者',
}

export function assignmentRoleName(role: string): string {
  return Object.hasOwn(ASSIGNMENT_ROLE_NAMES, role)
    ? (ASSIGNMENT_ROLE_NAMES[role as AssignmentRole] ?? '未知角色')
    : '未知角色'
}

const SUBMISSION_PURPOSE_NAMES: Record<SubmissionPurpose, string> = {
  finding_report: '发现项提报',
  rectification: '整改提交',
  verification: '验证结论',
  closure: '关闭确认',
}

export function submissionPurposeName(purpose: string): string {
  return Object.hasOwn(SUBMISSION_PURPOSE_NAMES, purpose)
    ? (SUBMISSION_PURPOSE_NAMES[purpose as SubmissionPurpose] ?? '未知类型')
    : '未知类型'
}

// 操作记录事件名。后端事件类型是自由字符串（没有集中枚举，也不在 OpenAPI 中），
// 清单来源见 PR 描述；新增事件在这里补齐前显示为“未知操作”。
export const ACTIVITY_EVENT_NAMES = {
  'review_case.created': '创建审查活动',
  'review_case.transitioned': '审查活动状态变更',
  'review_case.member_added': '添加审查成员',
  'review_case.member_removed': '移除审查成员',
  'finding.created': '创建发现项',
  'finding.transitioned': '发现项状态变更',
  'finding.reopened': '重新打开发现项',
  'finding.participant_added': '添加发现项参与方',
  'finding.rectification_plan_submitted': '提交整改计划',
  'finding.submitted_for_verification': '提交验证',
  'finding.approved': '通过验证',
  'finding.rejected': '驳回验证',
  'finding.nudged': '催办发现项',
  'action_item.created': '创建整改项',
  'action_item.transitioned': '整改项状态变更',
  'action_item.assignee_added': '添加整改项执行人',
  'action_item.transferred_and_reopened': '转交并重新打开整改项',
  'action_item.evidence_registered': '登记证据',
  'action_item.nudged': '催办整改项',
} as const satisfies Record<string, string>

export function isKnownActivityEvent(eventType: string): boolean {
  return Object.hasOwn(ACTIVITY_EVENT_NAMES, eventType)
}

export function activityEventName(eventType: string): string {
  return isKnownActivityEvent(eventType)
    ? ((ACTIVITY_EVENT_NAMES as Record<string, string>)[eventType] ?? '未知操作')
    : '未知操作'
}
