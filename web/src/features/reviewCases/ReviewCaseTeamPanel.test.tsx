import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { vi } from 'vitest'

import { ENGLISH_DETAIL, ruleError } from '../../api/ruleErrorFixture'
import { ApiError } from '../../api/client'
import { searchReviewCaseMemberCandidates } from '../../api/product'
import {
  ReviewCaseTeamPanel,
  classifyTeamFailure,
  roleLabelForCaseMember,
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

  it('treats every 409 as a team change without reading or showing the detail', () => {
    for (const detail of ['Cannot remove the final effective Case manager', 'CaseMember changed concurrently']) {
      const removed = classifyTeamFailure(new ApiError(409, detail), 'remove')
      expect(removed.kind).toBe('changed')
      expect('message' in removed && removed.message).toContain('不能移除最后一名管理者')
      expect('message' in removed && removed.message).not.toContain(detail)
    }
    // 添加时的 409 不展示服务端原文（可能是数据库唯一约束信息）。
    const add = classifyTeamFailure(new ApiError(409, 'duplicate key value violates unique constraint'), 'add')
    expect(add.kind).toBe('changed')
    expect('message' in add && add.message).not.toContain('duplicate')
    const rejected = classifyTeamFailure(ruleError(422, 'role.not_allowed_for_actor'), 'add')
    expect(rejected).toEqual({ kind: 'rejected', message: '所选对象不能担任该角色，请重新选择。' })
    expect(classifyTeamFailure(new ApiError(400, ENGLISH_DETAIL), 'add')).toMatchObject({ kind: 'rejected' })
    expect(JSON.stringify(classifyTeamFailure(new ApiError(400, ENGLISH_DETAIL), 'add'))).not.toContain(ENGLISH_DETAIL)
    expect(classifyTeamFailure(new ApiError(403, 'raw permission'), 'search')).toEqual({
      kind: 'forbidden',
      message: '当前用户没有管理审查团队的权限。',
    })
    expect(classifyTeamFailure(new ApiError(404, 'ReviewCase not found'), 'add')).toMatchObject({
      kind: 'gone',
      message: '内容不存在或无权访问',
    })
    expect(classifyTeamFailure(new ApiError(401, 'x'), 'add')).toEqual({ kind: 'session' })
    expect(classifyTeamFailure(new ApiError(429, 'slow', 7), 'add')).toMatchObject({
      kind: 'retry-later',
      message: '服务繁忙，请7 秒后手动重试。',
    })
  })

  it('tells the user how long to wait on 429/503 only when Retry-After is usable', () => {
    for (const status of [429, 503]) {
      for (const action of ['add', 'remove'] as const) {
        expect(classifyTeamFailure(new ApiError(status, 'busy', 30), action)).toEqual({
          kind: 'retry-later',
          message: '服务繁忙，请30 秒后手动重试。',
        })
        expect(
          classifyTeamFailure(new ApiError(status, 'busy', new Headers({ 'Retry-After': '12' })), action),
        ).toMatchObject({ kind: 'retry-later', message: '服务繁忙，请12 秒后手动重试。' })
        for (const unusable of [undefined, null, new Headers(), new Headers({ 'Retry-After': 'soon' })]) {
          expect(classifyTeamFailure(new ApiError(status, 'busy', unusable), action)).toEqual({
            kind: 'retry-later',
            message: '服务繁忙，请稍后手动重试。',
          })
        }
      }
    }
  })

  it('treats network failures and 5xx on writes as unknown results, not conflicts', () => {
    for (const error of [new ApiError(500, 'boom'), new TypeError('Failed to fetch')]) {
      const failure = classifyTeamFailure(error, 'remove')
      expect(failure.kind).toBe('unknown-result')
      expect('message' in failure && failure.message).toContain('未确认是否已移除成员')
    }
    expect(classifyTeamFailure(new TypeError('Failed to fetch'), 'add')).toMatchObject({ kind: 'unknown-result' })
  })

  it('keeps the current member visible with the exact adapter role label', () => {
    const markup = renderToStaticMarkup(
      <ReviewCaseTeamPanel
        reviewCase={reviewCase}
        roleOptions={roleOptions}
        members={[member]}
        membersLoading={false}
        membersUnavailable={false}
        membersError={null}
        onTeamChanged={vi.fn()}
        onAccessLost={vi.fn()}
      />,
    )

    expect(markup).toContain('Team Lead')
    expect(markup).toContain('审查组长')
    expect(markup).toContain('添加成员')
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
