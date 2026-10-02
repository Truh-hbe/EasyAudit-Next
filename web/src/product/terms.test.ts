import { describe, expect, it } from 'vitest'

import {
  assignmentRoleName,
  participantRoleName,
  scenarioName,
  submissionPurposeName,
} from './terms'

describe('product terms', () => {
  it('names scenarios and does not leak unknown keys', () => {
    expect(scenarioName('process_review')).toBe('过程审查')
    expect(scenarioName('compliance_review')).toBe('合规审查')
    expect(scenarioName('toString')).toBe('未知场景')
    expect(scenarioName('future_review')).toBe('未知场景')
  })

  it('names participant, assignment roles and submission purposes', () => {
    expect(participantRoleName('owner')).toBe('整改负责人')
    expect(participantRoleName('responsible_department')).toBe('责任部门')
    expect(participantRoleName('constructor')).toBe('未知角色')
    expect(assignmentRoleName('primary')).toBe('主要执行人')
    expect(assignmentRoleName('collaborator')).toBe('协作者')
    expect(assignmentRoleName('other')).toBe('未知角色')
    expect(submissionPurposeName('verification')).toBe('验证结论')
    expect(submissionPurposeName('other')).toBe('未知类型')
  })
})
