import { describe, expect, it } from 'vitest'

import { resolveCaseScenarioAdapter, resolveFindingScenarioAdapter } from './index'
import { ScenarioUiRegistry } from './registry'

describe('ScenarioUiRegistry exact version lookup', () => {
  it('never falls back to another version', () => {
    const registry = new ScenarioUiRegistry<string>()
    registry.register('process_review', 1, 'AdapterV1')
    registry.register('process_review', 2, 'AdapterV2')

    expect(registry.resolve('process_review', 1)).toBe('AdapterV1')
    expect(registry.resolve('process_review', 2)).toBe('AdapterV2')
    expect(registry.resolve('process_review', 99)).toBeUndefined()
    expect(registry.resolve('other', 1)).toBeUndefined()
  })

  it('rejects duplicate exact identities instead of silently replacing them', () => {
    const registry = new ScenarioUiRegistry<string>()
    registry.register('process_review', 1, 'AdapterV1')

    expect(() => registry.register('process_review', 1, 'Replacement')).toThrow(
      'Scenario UI adapter already registered: process_review',
    )
    expect(registry.resolve('process_review', 1)).toBe('AdapterV1')
  })

  it('production registry exposes both exact v1 adapters and never falls back', () => {
    expect(resolveCaseScenarioAdapter('process_review', 1)).toBeDefined()
    expect(resolveFindingScenarioAdapter('process_review', 1)).toBeDefined()
    expect(resolveCaseScenarioAdapter('compliance_review', 1)).toBeDefined()
    expect(resolveFindingScenarioAdapter('compliance_review', 1)).toBeDefined()

    expect(resolveCaseScenarioAdapter('process_review', 99)).toBeUndefined()
    expect(resolveFindingScenarioAdapter('process_review', 99)).toBeUndefined()
    expect(resolveCaseScenarioAdapter('compliance_review', 99)).toBeUndefined()
    expect(resolveFindingScenarioAdapter('compliance_review', 99)).toBeUndefined()
  })

  it('process_review@1 keeps relationship semantics and Finding input in its adapter', () => {
    const adapter = resolveFindingScenarioAdapter('process_review', 1)
    expect(adapter).toBeDefined()
    if (adapter === undefined) return

    expect(adapter.participantOptions).toEqual([
      { roleKey: 'responsible_department', actorKind: 'department', label: '责任部门' },
      { roleKey: 'owner', actorKind: 'user', label: '负责人' },
      { roleKey: 'collaborator', actorKind: 'user', label: '协作者' },
    ])
    expect(adapter.assigneeOptions.every((option) => option.actorKind === 'user')).toBe(true)
    expect(
      adapter.buildFindingScenarioData({
        issue_type: 'control_gap',
        project_category: 'assembly',
      }),
    ).toEqual({
      issue_type: 'control_gap',
      project_category: 'assembly',
    })
    expect(adapter.FindingInteractionSection).toBeDefined()

    const caseAdapter = resolveCaseScenarioAdapter('process_review', 1)
    expect(caseAdapter?.CaseCreateFields).toBeDefined()
    expect(caseAdapter?.caseMemberRoleOptions.map((option) => option.roleKey)).toEqual([
      'lead',
      'auditor',
      'reviewer',
      'observer',
    ])
    expect(
      caseAdapter?.buildCaseScenarioData({ area_code: 'area-a', review_type: 'standard' }),
    ).toEqual({ area_code: 'area-a', review_type: 'standard' })
  })

  it('compliance_review@1 keeps classification and relationships in its exact adapter', () => {
    const adapter = resolveFindingScenarioAdapter('compliance_review', 1)
    expect(adapter).toBeDefined()
    if (adapter === undefined) return

    expect(adapter.participantOptions).toEqual([
      { roleKey: 'responsible_department', actorKind: 'department', label: '责任部门' },
      { roleKey: 'owner', actorKind: 'user', label: '负责人' },
      { roleKey: 'collaborator', actorKind: 'user', label: '协作者' },
    ])
    expect(adapter.assigneeOptions.every((option) => option.actorKind === 'user')).toBe(true)
    expect(
      adapter.buildFindingScenarioData({
        criterion_reference: '8.5.1',
        finding_type: 'observation',
      }),
    ).toEqual({
      criterion_reference: '8.5.1',
      finding_type: 'observation',
    })
    expect(adapter.FindingInteractionSection).toBeDefined()

    const caseAdapter = resolveCaseScenarioAdapter('compliance_review', 1)
    expect(caseAdapter?.CaseCreateFields).toBeDefined()
    expect(caseAdapter?.caseMemberRoleOptions.map((option) => option.roleKey)).toEqual([
      'lead',
      'auditor',
      'reviewer',
      'observer',
    ])
    expect(
      caseAdapter?.buildCaseScenarioData({
        standard_reference: 'standard-a',
        scope_summary: 'pilot scope',
      }),
    ).toEqual({ standard_reference: 'standard-a', scope_summary: 'pilot scope' })
  })
})
