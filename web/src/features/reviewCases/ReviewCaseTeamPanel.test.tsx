import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import { roleLabelForCaseMember, teamMutationErrorMessage } from './ReviewCaseTeamPanel'

const roleOptions = [
  { roleKey: 'lead', label: '负责人' },
  { roleKey: 'observer', label: '观察员' },
]

describe('ReviewCaseTeamPanel', () => {
  it('uses only the exact adapter role display definition', () => {
    expect(roleLabelForCaseMember('lead', roleOptions)).toBe('负责人')
    expect(roleLabelForCaseMember('future_role', roleOptions)).toBe('future_role')
  })

  it('turns team conflicts into a safe recoverable message', () => {
    expect(teamMutationErrorMessage(new ApiError(409, 'raw conflict'), 'fallback')).toBe(
      '团队状态发生冲突，请刷新后重试。',
    )
    expect(teamMutationErrorMessage(new ApiError(403, 'raw permission'), 'fallback')).toBe(
      '当前用户没有管理 Case 团队的权限。',
    )
  })
})
