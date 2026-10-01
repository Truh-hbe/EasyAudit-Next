import { sessionApiDownload, sessionApiRequest } from './client'
import type { DownloadedFile } from './client'
import type {
  ManagementCaseProgressResponse,
  ManagementCaseSummary,
  ReviewCaseLifecycle,
} from './product'

export type ManagementDeadlineFilter = 'all' | 'due_soon' | 'overdue'

export interface ManagementCaseCollectionResponse {
  as_of: string
  items: ManagementCaseSummary[]
  total: number
  limit: number
  offset: number
}

export interface ManagementCaseQuery {
  reviewPlanId?: string
  lifecycle?: ReviewCaseLifecycle
  deadlineStatus: ManagementDeadlineFilter
  limit: number
  offset: number
}

export function listManagedReviewCases(
  query: ManagementCaseQuery,
  signal?: AbortSignal,
): Promise<ManagementCaseCollectionResponse> {
  const params = new URLSearchParams({
    deadline_status: query.deadlineStatus,
    limit: String(query.limit),
    offset: String(query.offset),
  })
  if (query.reviewPlanId !== undefined && query.reviewPlanId.length > 0) {
    params.set('review_plan_id', query.reviewPlanId)
  }
  if (query.lifecycle !== undefined) {
    params.set('lifecycle', query.lifecycle)
  }
  return sessionApiRequest<ManagementCaseCollectionResponse>(
    `/api/v1/management/review-cases?${params.toString()}`,
    { signal },
  )
}

export type ManagementExportFormat = 'csv' | 'xlsx'

export type ManagementExportQuery = Omit<ManagementCaseQuery, 'limit' | 'offset'>

export function exportManagedReviewCases(
  format: ManagementExportFormat,
  query: ManagementExportQuery,
  signal?: AbortSignal,
): Promise<DownloadedFile> {
  const params = new URLSearchParams({
    format,
    deadline_status: query.deadlineStatus,
  })
  if (query.reviewPlanId !== undefined && query.reviewPlanId.length > 0) {
    params.set('review_plan_id', query.reviewPlanId)
  }
  if (query.lifecycle !== undefined) {
    params.set('lifecycle', query.lifecycle)
  }
  return sessionApiDownload(
    `/api/v1/management/review-cases/export?${params.toString()}`,
    `review-cases.${format}`,
    { signal },
  )
}

export function getManagedReviewCaseProgress(
  caseId: string,
  signal?: AbortSignal,
): Promise<ManagementCaseProgressResponse> {
  return sessionApiRequest<ManagementCaseProgressResponse>(
    `/api/v1/management/review-cases/${encodeURIComponent(caseId)}/progress`,
    { signal },
  )
}
