import type { ScenarioCaseAdapter } from './registry'
import type { ScenarioCaseSectionProps } from './registry'

function scenarioText(value: unknown): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : '—'
}

export function ProcessReviewV1CaseSection({ reviewCase }: ScenarioCaseSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="process-review-v1-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">process_review@1</p>
          <h2 id="process-review-v1-title">过程审查信息</h2>
        </div>
      </div>
      <dl className="fact-grid">
        <div>
          <dt>区域代码</dt>
          <dd>{scenarioText(reviewCase.scenario_data.area_code)}</dd>
        </div>
        <div>
          <dt>审查类型</dt>
          <dd>{scenarioText(reviewCase.scenario_data.review_type)}</dd>
        </div>
      </dl>
    </section>
  )
}

export const PROCESS_REVIEW_V1_UI: ScenarioCaseAdapter = {
  CaseScenarioSection: ProcessReviewV1CaseSection,
}
