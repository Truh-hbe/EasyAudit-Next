import { sessionApiRequest } from './client'

export type ReviewCaseLifecycle =
  | 'draft'
  | 'scheduled'
  | 'in_progress'
  | 'awaiting_closure'
  | 'closed'
  | 'cancelled'
export type FindingLifecycle = 'open' | 'rectifying' | 'verifying' | 'closed' | 'voided'
export type FindingSeverity = 'low' | 'medium' | 'high' | 'critical'
export type ActionItemLifecycle = 'todo' | 'in_progress' | 'done' | 'cancelled'

export interface WorkbenchRelationship {
  role_key: string
  actor_kind: string
  source: string
}

export interface WorkbenchCaseResponsibility {
  id: string
  title: string
  lifecycle: ReviewCaseLifecycle
  role_keys: string[]
  planned_end_at: string | null
}

export interface WorkbenchFindingResponsibility {
  id: string
  case_id: string
  title: string
  severity: FindingSeverity
  lifecycle: FindingLifecycle
  relationships: WorkbenchRelationship[]
  raised_at: string
}

export interface WorkbenchActionResponsibility {
  id: string
  finding_id: string
  case_id: string
  title: string
  lifecycle: ActionItemLifecycle
  due_at: string | null
  relationships: WorkbenchRelationship[]
}

export interface WorkbenchVerificationItem {
  id: string
  case_id: string
  title: string
  severity: FindingSeverity
  raised_at: string
}

export interface WorkbenchCaseDeadline {
  id: string
  title: string
  lifecycle: ReviewCaseLifecycle
  deadline: string
}

export interface WorkbenchActionDeadline {
  id: string
  finding_id: string
  case_id: string
  title: string
  lifecycle: ActionItemLifecycle
  deadline: string
}

export interface WorkbenchDeadlineBucket {
  cases: WorkbenchCaseDeadline[]
  actions: WorkbenchActionDeadline[]
}

export interface WorkbenchResponse {
  as_of: string
  case_responsibilities: WorkbenchCaseResponsibility[]
  finding_responsibilities: WorkbenchFindingResponsibility[]
  action_responsibilities: WorkbenchActionResponsibility[]
  verification_queue: WorkbenchVerificationItem[]
  due_soon: WorkbenchDeadlineBucket
  overdue: WorkbenchDeadlineBucket
}

export interface ReviewCaseResponse {
  id: string
  organization_id: string
  plan_id: string | null
  scenario_key: string
  scenario_version: number
  title: string
  lifecycle: ReviewCaseLifecycle
  planned_start_at: string | null
  planned_end_at: string | null
  started_at: string | null
  fieldwork_completed_at: string | null
  closed_at: string | null
  scenario_data: Record<string, unknown>
  created_by: string
  created_at: string
}

export interface ReviewCaseCollectionResponse {
  items: ReviewCaseResponse[]
  total: number
  limit: number
  offset: number
}

export interface CaseMemberViewResponse {
  case_id: string
  user_id: string
  role_key: string
  joined_at: string
  display_name: string
}

export interface FindingResponse {
  id: string
  organization_id: string
  case_id: string
  title: string
  description: string | null
  severity: FindingSeverity
  lifecycle: FindingLifecycle
  scenario_data: Record<string, unknown>
  raised_by: string
  raised_at: string
}

export interface ReviewCaseActivityResponse {
  id: string
  subject_type: 'review_case'
  subject_id: string
  event_type: string
  actor_id: string | null
  occurred_at: string
}

export interface FindingLifecycleCounts {
  total: number
  open: number
  rectifying: number
  verifying: number
  closed: number
  voided: number
}

export interface ActionLifecycleCounts {
  total: number
  todo: number
  in_progress: number
  done: number
  cancelled: number
  overdue: number
  due_soon: number
}

export interface ManagementCaseSummary {
  id: string
  review_plan_id: string | null
  title: string
  scenario_key: string
  scenario_version: number
  lifecycle: ReviewCaseLifecycle
  planned_start_at: string | null
  planned_end_at: string | null
  deadline_bucket: 'overdue' | 'due_soon' | 'later' | 'none'
  findings: FindingLifecycleCounts
  actions: ActionLifecycleCounts
}

export interface ManagementFindingProgress {
  id: string
  title: string
  severity: FindingSeverity
  lifecycle: FindingLifecycle
  raised_at: string
  actions: ActionLifecycleCounts
}

export interface ManagementActionDeadlineItem {
  id: string
  title: string
  lifecycle: ActionItemLifecycle
  due_at: string
}

export interface ManagementCaseProgressResponse {
  as_of: string
  case: ManagementCaseSummary
  findings: ManagementFindingProgress[]
  overdue_actions: ManagementActionDeadlineItem[]
  due_soon_actions: ManagementActionDeadlineItem[]
}

export function getWorkbench(signal?: AbortSignal): Promise<WorkbenchResponse> {
  return sessionApiRequest<WorkbenchResponse>('/api/v1/me/workbench', { signal })
}

export function listReviewCases(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<ReviewCaseCollectionResponse> {
  return sessionApiRequest<ReviewCaseCollectionResponse>(
    `/api/v1/review-cases?limit=${limit}&offset=${offset}`,
    { signal },
  )
}

export function getReviewCase(caseId: string, signal?: AbortSignal): Promise<ReviewCaseResponse> {
  return sessionApiRequest<ReviewCaseResponse>(`/api/v1/review-cases/${encodeURIComponent(caseId)}`, {
    signal,
  })
}

export function getReviewCaseMembers(
  caseId: string,
  signal?: AbortSignal,
): Promise<CaseMemberViewResponse[]> {
  return sessionApiRequest<CaseMemberViewResponse[]>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/members`,
    { signal },
  )
}

export function getReviewCaseFindings(
  caseId: string,
  signal?: AbortSignal,
): Promise<FindingResponse[]> {
  return sessionApiRequest<FindingResponse[]>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/findings`,
    { signal },
  )
}

export function getReviewCaseActivities(
  caseId: string,
  signal?: AbortSignal,
): Promise<ReviewCaseActivityResponse[]> {
  return sessionApiRequest<ReviewCaseActivityResponse[]>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/activities`,
    { signal },
  )
}

export function getManagementCaseProgress(
  caseId: string,
  signal?: AbortSignal,
): Promise<ManagementCaseProgressResponse> {
  return sessionApiRequest<ManagementCaseProgressResponse>(
    `/api/v1/management/review-cases/${encodeURIComponent(caseId)}/progress`,
    { signal },
  )
}
