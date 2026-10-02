import { describe, expect, it } from 'vitest'

import {
  ACTIVITY_EVENT_NAMES,
  activityEventName,
  assignmentRoleName,
  caseRoleName,
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

  it('names Case roles and does not leak unknown keys', () => {
    expect(caseRoleName('lead')).toBe('审查组长')
    expect(caseRoleName('auditor')).toBe('审查员')
    expect(caseRoleName('reviewer')).toBe('复核员')
    expect(caseRoleName('observer')).toBe('观察员')
    expect(caseRoleName('superuser')).toBe('未知角色')
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

  it('names every known activity event and degrades unknown ones', () => {
    const known = Object.keys(ACTIVITY_EVENT_NAMES).sort()
    expect(known).toEqual([
      'action_item.assignee_added',
      'action_item.created',
      'action_item.evidence_registered',
      'action_item.nudged',
      'action_item.transitioned',
      'finding.approved',
      'finding.created',
      'finding.nudged',
      'finding.participant_added',
      'finding.rectification_plan_submitted',
      'finding.rejected',
      'finding.reopened',
      'finding.submitted_for_verification',
      'finding.transitioned',
      'review_case.created',
      'review_case.member_added',
      'review_case.member_removed',
      'review_case.transitioned',
    ])
    for (const eventType of known) {
      const name = activityEventName(eventType)
      expect(name).not.toBe('未知操作')
      expect(name).not.toContain('.')
    }
    expect(activityEventName('review_case.created')).toBe('创建审查活动')
    expect(activityEventName('finding.future_event')).toBe('未知操作')
    expect(activityEventName('')).toBe('未知操作')
  })

  it('does not resolve prototype keys as activity events', () => {
    for (const key of ['toString', 'constructor', '__proto__', 'hasOwnProperty']) {
      expect(activityEventName(key)).toBe('未知操作')
    }
  })
})
