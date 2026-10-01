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
export type ActorKind = 'user' | 'department'
export type AssignmentRole = 'primary' | 'collaborator'
export type SubmissionPurpose = 'finding_report' | 'rectification' | 'verification' | 'closure'

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

export interface ReviewCatalogItemResponse {
  scenario_key: string
  scenario_version: number
  display_name: string
}

export interface ReviewPlanResponse {
  id: string
  organization_id: string
  title: string
  planned_start_at: string | null
  planned_end_at: string | null
  created_by: string
}

export interface ReviewPlanCreateInput {
  title: string
  planned_start_at?: string | null
  planned_end_at?: string | null
}

export interface ReviewCaseCreateInput {
  plan_id: string
  scenario_key: string
  scenario_version: number
  title: string
  scenario_data: Record<string, unknown>
}

export interface ReviewCaseCollectionResponse {
  items: ReviewCaseResponse[]
  total: number
  limit: number
  offset: number
}

export interface CaseMemberResponse {
  case_id: string
  user_id: string
  role_key: string
  joined_at: string
}

export interface CaseMemberViewResponse {
  case_id: string
  user_id: string
  role_key: string
  joined_at: string
  display_name: string
}

export interface CaseMemberCandidateResponse {
  user_id: string
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

export interface ActionItemResponse {
  id: string
  organization_id: string
  finding_id: string
  title: string
  lifecycle: ActionItemLifecycle
  due_at: string | null
  completed_at: string | null
}

export interface FindingParticipantViewResponse {
  finding_id: string
  actor_kind: ActorKind
  actor_id: string
  role_key: string
  assigned_at: string
  display_name: string
}

export interface ActionAssigneeViewResponse {
  action_item_id: string
  actor_kind: ActorKind
  actor_id: string
  role: AssignmentRole
  assigned_at: string
  display_name: string
}

export interface AssignmentCandidateResponse {
  actor_kind: ActorKind
  actor_id: string
  display_name: string
}

export interface SubmissionResponse {
  id: string
  organization_id: string
  case_id: string
  finding_id: string | null
  purpose: SubmissionPurpose
  submitted_by: string
  submitted_at: string
  payload: Record<string, unknown>
}

export interface RectificationSubmissionResponse {
  submission: SubmissionResponse
  finding: FindingResponse
}

export interface VerificationSubmissionResponse {
  submission: SubmissionResponse
  finding: FindingResponse
}

export interface EvidenceResponse {
  id: string
  organization_id: string
  action_item_id: string
  storage_key: string
  original_name: string
  content_type: string | null
  size_bytes: number
  sha256: string
  description: string | null
  uploaded_by: string
  created_at: string
}

export interface ReviewCaseActivityResponse {
  id: string
  subject_type: 'review_case'
  subject_id: string
  event_type: string
  actor_id: string | null
  occurred_at: string
}

export interface FindingActivityResponse {
  id: string
  subject_type: 'finding'
  subject_id: string
  event_type: string
  actor_id: string | null
  occurred_at: string
}

export interface ActionItemActivityResponse {
  id: string
  subject_type: 'action_item'
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

export interface FindingCreateInput {
  title: string
  description: string | null
  severity: FindingSeverity
  scenario_data: Record<string, unknown>
}

export interface ActionItemCreateInput {
  title: string
  due_at: string | null
}

export function getWorkbench(signal?: AbortSignal): Promise<WorkbenchResponse> {
  return sessionApiRequest<WorkbenchResponse>('/api/v1/me/workbench', { signal })
}

export function getReviewCatalog(signal?: AbortSignal): Promise<ReviewCatalogItemResponse[]> {
  return sessionApiRequest<ReviewCatalogItemResponse[]>('/api/v1/review-catalog', { signal })
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

export function createReviewPlan(
  input: ReviewPlanCreateInput,
  idempotencyKey: string,
): Promise<ReviewPlanResponse> {
  return sessionApiRequest<ReviewPlanResponse>('/api/v1/review-plans', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(input),
  })
}

export function listReviewPlans(signal?: AbortSignal): Promise<ReviewPlanResponse[]> {
  return sessionApiRequest<ReviewPlanResponse[]>('/api/v1/review-plans', { signal })
}

export function getReviewPlan(planId: string, signal?: AbortSignal): Promise<ReviewPlanResponse> {
  return sessionApiRequest<ReviewPlanResponse>(
    `/api/v1/review-plans/${encodeURIComponent(planId)}`,
    { signal },
  )
}

export function createReviewCase(
  input: ReviewCaseCreateInput,
  idempotencyKey: string,
): Promise<ReviewCaseResponse> {
  return sessionApiRequest<ReviewCaseResponse>('/api/v1/review-cases', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(input),
  })
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

export function searchReviewCaseMemberCandidates(
  caseId: string,
  roleKey: string,
  query: string,
  signal?: AbortSignal,
): Promise<CaseMemberCandidateResponse[]> {
  const params = new URLSearchParams({ role_key: roleKey, q: query, limit: '20' })
  return sessionApiRequest<CaseMemberCandidateResponse[]>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/member-candidates?${params.toString()}`,
    { signal },
  )
}

export function addReviewCaseMember(
  caseId: string,
  userId: string,
  roleKey: string,
): Promise<CaseMemberResponse> {
  return sessionApiRequest<CaseMemberResponse>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/members`,
    {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, role_key: roleKey }),
    },
  )
}

export function removeReviewCaseMember(
  caseId: string,
  userId: string,
  roleKey: string,
): Promise<CaseMemberResponse> {
  const params = new URLSearchParams({ role_key: roleKey })
  return sessionApiRequest<CaseMemberResponse>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/members/${encodeURIComponent(userId)}?${params.toString()}`,
    { method: 'DELETE' },
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

export function createFinding(
  caseId: string,
  input: FindingCreateInput,
): Promise<FindingResponse> {
  return sessionApiRequest<FindingResponse>(
    `/api/v1/review-cases/${encodeURIComponent(caseId)}/findings`,
    { method: 'POST', body: JSON.stringify(input) },
  )
}

export function getFinding(findingId: string, signal?: AbortSignal): Promise<FindingResponse> {
  return sessionApiRequest<FindingResponse>(`/api/v1/findings/${encodeURIComponent(findingId)}`, {
    signal,
  })
}

export function transitionFinding(
  findingId: string,
  action: string,
  reason: string | null = null,
): Promise<FindingResponse> {
  return sessionApiRequest<FindingResponse>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/transitions`,
    { method: 'POST', body: JSON.stringify({ action, reason }) },
  )
}

export function getFindingParticipantViews(
  findingId: string,
  signal?: AbortSignal,
): Promise<FindingParticipantViewResponse[]> {
  return sessionApiRequest<FindingParticipantViewResponse[]>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/participant-views`,
    { signal },
  )
}

export function searchFindingParticipantCandidates(
  findingId: string,
  roleKey: string,
  actorKind: ActorKind,
  query: string,
  signal?: AbortSignal,
): Promise<AssignmentCandidateResponse[]> {
  const params = new URLSearchParams({
    role_key: roleKey,
    actor_kind: actorKind,
    q: query,
    limit: '20',
  })
  return sessionApiRequest<AssignmentCandidateResponse[]>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/participant-candidates?${params.toString()}`,
    { signal },
  )
}

export function addFindingParticipant(
  findingId: string,
  actorKind: ActorKind,
  actorId: string,
  roleKey: string,
): Promise<unknown> {
  return sessionApiRequest<unknown>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/participants`,
    {
      method: 'POST',
      body: JSON.stringify({ actor_kind: actorKind, actor_id: actorId, role_key: roleKey }),
    },
  )
}

export function getFindingActions(
  findingId: string,
  signal?: AbortSignal,
): Promise<ActionItemResponse[]> {
  return sessionApiRequest<ActionItemResponse[]>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/actions`,
    { signal },
  )
}

export function createActionItem(
  findingId: string,
  input: ActionItemCreateInput,
): Promise<ActionItemResponse> {
  return sessionApiRequest<ActionItemResponse>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/actions`,
    { method: 'POST', body: JSON.stringify(input) },
  )
}

export function getActionItem(
  actionItemId: string,
  signal?: AbortSignal,
): Promise<ActionItemResponse> {
  return sessionApiRequest<ActionItemResponse>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}`,
    { signal },
  )
}

export function getActionAssigneeViews(
  actionItemId: string,
  signal?: AbortSignal,
): Promise<ActionAssigneeViewResponse[]> {
  return sessionApiRequest<ActionAssigneeViewResponse[]>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/assignee-views`,
    { signal },
  )
}

export function searchActionAssigneeCandidates(
  actionItemId: string,
  role: AssignmentRole,
  actorKind: ActorKind,
  query: string,
  signal?: AbortSignal,
): Promise<AssignmentCandidateResponse[]> {
  const params = new URLSearchParams({ role, actor_kind: actorKind, q: query, limit: '20' })
  return sessionApiRequest<AssignmentCandidateResponse[]>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/assignee-candidates?${params.toString()}`,
    { signal },
  )
}

export function addActionAssignee(
  actionItemId: string,
  actorKind: ActorKind,
  actorId: string,
  role: AssignmentRole,
): Promise<unknown> {
  return sessionApiRequest<unknown>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/assignees`,
    {
      method: 'POST',
      body: JSON.stringify({ actor_kind: actorKind, actor_id: actorId, role }),
    },
  )
}

export function transitionActionItem(
  actionItemId: string,
  action: string,
  reason: string | null = null,
): Promise<ActionItemResponse> {
  return sessionApiRequest<ActionItemResponse>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/transitions`,
    { method: 'POST', body: JSON.stringify({ action, reason }) },
  )
}

export function getActionEvidences(
  actionItemId: string,
  signal?: AbortSignal,
): Promise<EvidenceResponse[]> {
  return sessionApiRequest<EvidenceResponse[]>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/evidences`,
    { signal },
  )
}

export function getFindingSubmissions(
  findingId: string,
  signal?: AbortSignal,
): Promise<SubmissionResponse[]> {
  return sessionApiRequest<SubmissionResponse[]>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/submissions`,
    { signal },
  )
}

export function submitRectification(
  findingId: string,
  action: string,
  payload: Record<string, unknown>,
): Promise<RectificationSubmissionResponse> {
  return sessionApiRequest<RectificationSubmissionResponse>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/rectification-submissions`,
    { method: 'POST', body: JSON.stringify({ action, payload }) },
  )
}

export function submitFindingVerification(
  findingId: string,
  action: string,
  payload: Record<string, unknown>,
): Promise<VerificationSubmissionResponse> {
  return sessionApiRequest<VerificationSubmissionResponse>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/verification-submissions`,
    { method: 'POST', body: JSON.stringify({ action, payload }) },
  )
}

export function reopenFinding(findingId: string, reason: string): Promise<FindingResponse> {
  return sessionApiRequest<FindingResponse>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/reopen`,
    { method: 'POST', body: JSON.stringify({ reason }) },
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

export function getFindingActivities(
  findingId: string,
  signal?: AbortSignal,
): Promise<FindingActivityResponse[]> {
  return sessionApiRequest<FindingActivityResponse[]>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/activities`,
    { signal },
  )
}

export function getActionItemActivities(
  actionItemId: string,
  signal?: AbortSignal,
): Promise<ActionItemActivityResponse[]> {
  return sessionApiRequest<ActionItemActivityResponse[]>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/activities`,
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
