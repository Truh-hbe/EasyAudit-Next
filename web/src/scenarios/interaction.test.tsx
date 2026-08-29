import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { FindingResponse } from '../api/product'
import { resolveFindingScenarioAdapter } from './index'
import type { ScenarioFindingCommandPorts } from './registry'

const commands: ScenarioFindingCommandPorts = {
  transition: async () => undefined,
  submitRectification: async () => undefined,
  submitVerification: async () => undefined,
  reopen: async () => undefined,
}

async function execute(_label: string, command: () => Promise<unknown>): Promise<void> {
  await command()
}

function finding(
  findingType: string,
  lifecycle: FindingResponse['lifecycle'] = 'open',
): FindingResponse {
  return {
    id: 'finding-1',
    organization_id: 'org-1',
    case_id: 'case-1',
    title: 'Scenario interaction test',
    description: null,
    severity: 'medium',
    lifecycle,
    scenario_data: {
      criterion_reference: '8.5.1',
      finding_type: findingType,
      issue_type: 'control_gap',
      project_category: 'assembly',
    },
    raised_by: 'user-1',
    raised_at: '2026-08-29T00:00:00Z',
  }
}

function interactionMarkup(
  scenarioKey: string,
  currentFinding: FindingResponse,
): string {
  const adapter = resolveFindingScenarioAdapter(scenarioKey, 1)
  expect(adapter).toBeDefined()
  if (adapter === undefined) return ''
  const Interaction = adapter.FindingInteractionSection
  return renderToStaticMarkup(
    <Interaction
      finding={currentFinding}
      commands={commands}
      execute={execute}
    />,
  )
}

describe('exact Scenario Finding interaction adapters', () => {
  it('process_review@1 owns issue and never exposes accept_observation', () => {
    const markup = interactionMarkup('process_review', finding('observation'))

    expect(markup).toContain('data-scenario-action="issue"')
    expect(markup).not.toContain('data-scenario-action="accept_observation"')
  })

  it('compliance_review@1 observation owns accept_observation instead of issue', () => {
    const markup = interactionMarkup('compliance_review', finding('observation'))

    expect(markup).toContain('data-scenario-action="accept_observation"')
    expect(markup).not.toContain('data-scenario-action="issue"')
  })

  it('compliance_review@1 nonconformity owns issue instead of accept_observation', () => {
    const markup = interactionMarkup('compliance_review', finding('nonconformity'))

    expect(markup).toContain('data-scenario-action="issue"')
    expect(markup).not.toContain('data-scenario-action="accept_observation"')
  })

  it('unknown exact versions fail closed before rendering Scenario interactions', () => {
    expect(resolveFindingScenarioAdapter('process_review', 99)).toBeUndefined()
    expect(resolveFindingScenarioAdapter('compliance_review', 99)).toBeUndefined()
  })
})
