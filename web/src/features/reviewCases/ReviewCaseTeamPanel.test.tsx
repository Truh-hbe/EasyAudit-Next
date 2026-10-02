import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { vi } from 'vitest'

import { ApiError } from '../../api/client'
import { searchReviewCaseMemberCandidates } from '../../api/product'
import {
  ReviewCaseTeamPanel,
  roleLabelForCaseMember,
  teamMutationErrorMessage,
} from './ReviewCaseTeamPanel'

const roleOptions = [
  { roleKey: 'lead', label: '审查组长' },
  { roleKey: 'auditor', label: '审查员' },
  { roleKey: 'reviewer', label: '复核员' },
  { roleKey: 'observer', label: '观察员' },
]

const reviewCase = {
  id: 'case-1',
  organization_id: 'org-1',
  plan_id: null,
  scenario_key: 'process_review',
  scenario_version: 1,
  title: 'Team test case',
  lifecycle: 'in_progress' as const,
  planned_start_at: null,
  planned_end_at: null,
  started_at: null,
  fieldwork_completed_at: null,
  closed_at: null,
  scenario_data: {},
  created_by: 'user-1',
  created_at: '2026-08-30T00:00:00Z',
}

const member = {
  case_id: 'case-1',
  user_id: 'user-1',
  role_key: 'lead',
  joined_at: '2026-08-30T00:00:00Z',
  display_name: 'Team Lead',
}

describe('ReviewCaseTeamPanel', () => {
  it('uses only the exact adapter role display definition', () => {
    expect(roleLabelForCaseMember('lead', roleOptions)).toBe('审查组长')
    expect(roleLabelForCaseMember('future_role', roleOptions)).toBe('future_role')
  })

  it('turns team conflicts into a safe recoverable message', () => {
    expect(teamMutationErrorMessage(new ApiError(409, 'raw conflict'), 'fallback')).toBe(
      '团队状态发生冲突，请刷新后重试。',
    )
    expect(teamMutationErrorMessage(new ApiError(403, 'raw permission'), 'fallback')).toBe(
      '当前用户没有管理审查团队的权限。',
    )
  })

  it('renders every role from the exact adapter and keeps the current member visible', () => {
    const markup = renderToStaticMarkup(
      <ReviewCaseTeamPanel
        reviewCase={reviewCase}
        roleOptions={roleOptions}
        members={[member]}
        membersLoading={false}
        membersUnavailable={false}
        membersError={null}
        onTeamChanged={vi.fn()}
      />,
    )

    expect(markup).toContain('value="lead"')
    expect(markup).toContain('value="auditor"')
    expect(markup).toContain('value="reviewer"')
    expect(markup).toContain('value="observer"')
    expect(markup).toContain('Team Lead')
    expect(markup).toContain('审查组长')
  })

  it('shapes candidate searches with the selected exact role and bounded query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await searchReviewCaseMemberCandidates('case/1', 'reviewer', ' Candidate ')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [path] = fetchMock.mock.calls[0] as [string]
    expect(path).toBe(
      '/api/v1/review-cases/case%2F1/member-candidates?role_key=reviewer&q=+Candidate+&limit=20',
    )
    vi.unstubAllGlobals()
  })
})
