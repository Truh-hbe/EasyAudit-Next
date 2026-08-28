import { sessionApiRequest } from './client'

export type NotificationKind =
  | 'case_membership_added'
  | 'finding_participant_added'
  | 'action_assignee_added'
  | 'finding_submitted_for_verification'
  | 'manual_finding_nudge'
  | 'manual_action_nudge'
  | 'automatic_case_reminder'
  | 'automatic_action_reminder'

export type NotificationOriginKind = 'activity' | 'automatic_reminder'
export type NotificationSubjectKind = 'review_case' | 'finding' | 'action_item'

export interface NotificationSubjectResponse {
  kind: NotificationSubjectKind
  id: string
}

export interface NotificationResponse {
  id: string
  kind: NotificationKind
  origin_kind: NotificationOriginKind
  origin_activity_id: string | null
  automatic_origin_key: string | null
  subject: NotificationSubjectResponse
  title: string
  body: string
  created_at: string
  read_at: string | null
}

export interface NotificationInboxResponse {
  items: NotificationResponse[]
  unread_count: number
  limit: number
  offset: number
}

export function listNotifications(
  unreadOnly: boolean,
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<NotificationInboxResponse> {
  const params = new URLSearchParams({
    unread_only: unreadOnly ? 'true' : 'false',
    limit: String(limit),
    offset: String(offset),
  })
  return sessionApiRequest<NotificationInboxResponse>(
    `/api/v1/me/notifications?${params.toString()}`,
    { signal },
  )
}

export function markNotificationRead(notificationId: string): Promise<NotificationResponse> {
  return sessionApiRequest<NotificationResponse>(
    `/api/v1/me/notifications/${encodeURIComponent(notificationId)}/read`,
    { method: 'POST' },
  )
}
