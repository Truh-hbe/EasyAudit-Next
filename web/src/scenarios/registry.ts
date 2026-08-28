import type { ComponentType } from 'react'

import type { ReviewCaseResponse } from '../api/product'

export interface ScenarioCaseSectionProps {
  reviewCase: ReviewCaseResponse
}

export interface ScenarioCaseAdapter {
  CaseScenarioSection: ComponentType<ScenarioCaseSectionProps>
}

export class ScenarioUiRegistry<T> {
  private readonly entries = new Map<string, T>()

  register(key: string, version: number, adapter: T): void {
    const identity = this.identity(key, version)
    if (this.entries.has(identity)) {
      throw new Error(`Scenario UI adapter already registered: ${identity}`)
    }
    this.entries.set(identity, adapter)
  }

  resolve(key: string, version: number): T | undefined {
    return this.entries.get(this.identity(key, version))
  }

  private identity(key: string, version: number): string {
    return `${key}\u0000${version}`
  }
}
