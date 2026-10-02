import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError, isIdempotencyKeyReuse } from '../../api/client'
import {
  createReviewCase,
  getReviewCatalog,
  getReviewPlan,
  newIdempotencyKey,
} from '../../api/product'
import type {
  ReviewCaseCreateInput,
  ReviewCaseResponse,
  ReviewCatalogItemResponse,
  ReviewPlanResponse,
} from '../../api/product'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import type { ScenarioCaseAdapter, ScenarioFormValues } from '../../scenarios/registry'
import { ButtonLink } from '../../ui/ButtonLink'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; plan: ReviewPlanResponse; catalog: ReviewCatalogItemResponse[] }

export type CaseSubmitState =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'rejected'; message: string }
  | { status: 'unknown'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function identity(item: ReviewCatalogItemResponse): string {
  return `${item.scenario_key}@${item.scenario_version}`
}

export function isDefinitiveRejection(error: unknown): boolean {
  return error instanceof ApiError
}

// An unknown outcome may be retried by hand: the retry reuses the form's Idempotency-Key, so the
// server either creates the case once or replays the first result. It is never retried automatically.
export function canSubmitCase(state: CaseSubmitState): boolean {
  return state.status !== 'submitting'
}

export function canCreateCase(
  adapter: ScenarioCaseAdapter | undefined,
  state: CaseSubmitState,
): boolean {
  return adapter !== undefined && canSubmitCase(state)
}

function caseRejectionMessage(error: unknown): string {
  if (isIdempotencyKeyReuse(error)) {
    return '提交的内容与此前使用同一幂等键的请求不一致。请刷新页面后重试。'
  }
  return errorMessage(error, '审查活动创建被服务器拒绝，请修正后重试。')
}

export async function executeCaseSubmission(
  request: () => Promise<ReviewCaseResponse>,
): Promise<{ state: CaseSubmitState; reviewCase?: ReviewCaseResponse }> {
  try {
    return { state: { status: 'idle' }, reviewCase: await request() }
  } catch (error: unknown) {
    return {
      state: isDefinitiveRejection(error)
        ? { status: 'rejected', message: caseRejectionMessage(error) }
        : {
            status: 'unknown',
            message: '审查活动创建结果未知。可以重试创建：同一次提交使用相同的幂等键，不会重复创建；系统不会自动再次提交。',
          },
    }
  }
}

export function buildCaseCreateInput(
  planId: string,
  item: ReviewCatalogItemResponse,
  title: string,
  adapter: ScenarioCaseAdapter,
  values: ScenarioFormValues,
): ReviewCaseCreateInput {
  return {
    plan_id: planId,
    scenario_key: item.scenario_key,
    scenario_version: item.scenario_version,
    title,
    scenario_data: adapter.buildCaseScenarioData(values),
  }
}

export function ReviewCaseCreatePage() {
  const { planId } = useParams()
  const navigate = useNavigate()
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [selectedIdentity, setSelectedIdentity] = useState('')
  const [caseTitle, setCaseTitle] = useState('')
  const [scenarioValues, setScenarioValues] = useState<ScenarioFormValues>({})
  const [submitState, setSubmitState] = useState<CaseSubmitState>({ status: 'idle' })
  // One key per form lifetime: retries, double clicks and resubmits after a network failure share it.
  const idempotencyKey = useRef(newIdempotencyKey())

  useEffect(() => {
    if (planId === undefined || planId.trim() === '') {
      setLoadState({ status: 'error', message: '缺少审查计划编号，无法继续创建审查活动。' })
      return
    }
    const controller = new AbortController()
    setLoadState({ status: 'loading' })
    setSubmitState({ status: 'idle' })
    idempotencyKey.current = newIdempotencyKey()
    void Promise.all([
      getReviewPlan(planId, controller.signal),
      getReviewCatalog(controller.signal),
    ])
      .then(([plan, catalog]) => {
        if (!controller.signal.aborted) setLoadState({ status: 'ready', plan, catalog })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setLoadState({ status: 'error', message: errorMessage(error, '审查计划或场景目录读取失败') })
      })
    return () => controller.abort()
  }, [planId])

  const selectedItem = useMemo(() => {
    if (loadState.status !== 'ready') return undefined
    return loadState.catalog.find((item) => identity(item) === selectedIdentity)
  }, [loadState, selectedIdentity])
  const scenarioAdapter =
    selectedItem === undefined
      ? undefined
      : resolveCaseScenarioAdapter(selectedItem.scenario_key, selectedItem.scenario_version)

  useEffect(() => {
    if (loadState.status !== 'ready') return
    if (loadState.catalog.some((item) => identity(item) === selectedIdentity)) return
    setSelectedIdentity(loadState.catalog[0] === undefined ? '' : identity(loadState.catalog[0]))
    setScenarioValues({})
  }, [loadState, selectedIdentity])

  function onScenarioChange(name: string, value: string): void {
    setScenarioValues((current) => ({ ...current, [name]: value }))
  }

  async function submitCase(): Promise<void> {
    if (
      planId === undefined ||
      loadState.status !== 'ready' ||
      selectedItem === undefined ||
      scenarioAdapter === undefined ||
      !canCreateCase(scenarioAdapter, submitState)
    ) return
    if (caseTitle.trim() === '') {
      setSubmitState({ status: 'rejected', message: '请输入审查活动名称。' })
      return
    }
    if (caseTitle !== caseTitle.trim()) {
      setSubmitState({ status: 'rejected', message: '审查活动名称前后不能有空格。' })
      return
    }

    setSubmitState({ status: 'submitting' })
    const result = await executeCaseSubmission(() => createReviewCase(
        buildCaseCreateInput(planId, selectedItem, caseTitle, scenarioAdapter, scenarioValues),
        idempotencyKey.current,
      ))
    if (result.reviewCase !== undefined) {
      idempotencyKey.current = newIdempotencyKey()
      await navigate(`/review-cases/${encodeURIComponent(result.reviewCase.id)}`)
    } else {
      setSubmitState(result.state)
    }
  }

  if (loadState.status === 'loading') {
    return <section className="surface-page"><p className="eyebrow">第 2 步，共 2 步</p><h1>新建审查活动</h1><p role="status">正在恢复计划并读取当前可用场景…</p></section>
  }

  if (loadState.status === 'error') {
    return (
      <section className="surface-page">
        <p className="eyebrow">第 2 步，共 2 步</p>
        <h1>无法继续创建审查活动</h1>
        <div className="surface-card" role="alert">
          <p>{loadState.message}</p>
          <Link to="/review-cases">返回审查活动</Link>
        </div>
      </section>
    )
  }

  const unsupportedSelection = selectedItem !== undefined && scenarioAdapter === undefined
  const CaseCreateFields = scenarioAdapter?.CaseCreateFields
  return (
    <section className="surface-page" aria-labelledby="review-case-create-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">第 2 步，共 2 步</p>
          <h1 id="review-case-create-title">新建审查活动</h1>
        </div>
        <span className="wizard-step">计划已保存</span>
      </div>

      <div className="surface-card">
        <h2>已恢复的审查计划</h2>
        <dl className="fact-grid compact-facts">
          <div><dt>计划名称</dt><dd>{loadState.plan.title}</dd></div>
          <div><dt>计划编号</dt><dd>{loadState.plan.id}</dd></div>
        </dl>
      </div>

      <div className="surface-card">
        <h2>审查活动信息</h2>
        <p className="field-help">审查活动名称必须单独填写；计划名称和计划日期不会自动复制到审查活动。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void submitCase()
          }}
        >
          <label>
            审查活动名称
            <input
              value={caseTitle}
              onChange={(event) => setCaseTitle(event.target.value)}
              required
              maxLength={300}
              disabled={!canSubmitCase(submitState)}
              autoComplete="off"
            />
          </label>
          <label>
            审查场景
            <select
              value={selectedIdentity}
              onChange={(event) => {
                setSelectedIdentity(event.target.value)
                setScenarioValues({})
                setSubmitState({ status: 'idle' })
              }}
              disabled={!canSubmitCase(submitState)}
            >
              <option value="" disabled>请选择审查场景</option>
              {loadState.catalog.map((item) => (
                <option
                  key={identity(item)}
                  value={identity(item)}
                  disabled={resolveCaseScenarioAdapter(item.scenario_key, item.scenario_version) === undefined}
                >
                  {item.display_name} · {identity(item)}
                </option>
              ))}
            </select>
          </label>
          {unsupportedSelection ? (
            <p role="alert">当前版本的审查场景界面暂不支持，创建已关闭。</p>
          ) : null}
          {CaseCreateFields === undefined ? null : (
            <CaseCreateFields
              values={scenarioValues}
              onChange={onScenarioChange}
              disabled={submitState.status === 'submitting'}
            />
          )}
          {submitState.status === 'rejected' ? <p role="alert">{submitState.message}</p> : null}
          {submitState.status === 'unknown' ? <p role="alert">{submitState.message}</p> : null}
          <div className="wizard-actions">
            <ButtonLink to="/review-cases">取消</ButtonLink>
            <button
              type="submit"
              disabled={!canCreateCase(scenarioAdapter, submitState)}
            >
              {submitState.status === 'submitting'
                ? '正在创建审查活动…'
                : submitState.status === 'unknown'
                  ? '重试创建审查活动'
                  : '创建审查活动'}
            </button>
          </div>
          {submitState.status === 'unknown' ? (
            <Link to="/review-cases">返回审查活动，查看是否已创建</Link>
          ) : null}
        </form>
      </div>
    </section>
  )
}
