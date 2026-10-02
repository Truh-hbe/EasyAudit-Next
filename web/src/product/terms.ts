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
