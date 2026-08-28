import { sessionApiRequest } from './client'

export interface NudgeResponse {
  activity_id: string
  recipient_count: number
}

export function nudgeFinding(findingId: string): Promise<NudgeResponse> {
  return sessionApiRequest<NudgeResponse>(
    `/api/v1/findings/${encodeURIComponent(findingId)}/nudge`,
    { method: 'POST' },
  )
}

export function nudgeActionItem(actionItemId: string): Promise<NudgeResponse> {
  return sessionApiRequest<NudgeResponse>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/nudge`,
    { method: 'POST' },
  )
}
