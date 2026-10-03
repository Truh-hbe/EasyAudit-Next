import { Alert, Button, Card, Descriptions, Flex, Form, Input, Radio, Select, Steps, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router'

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
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import { caseCreateFieldId } from '../../scenarios/CaseCreateTextField'
import type { ScenarioCaseAdapter, ScenarioFormValues } from '../../scenarios/registry'
import { ButtonLink } from '../../ui/ButtonLink'
import { FieldError } from '../../ui/FieldError'
import { InitialLoading } from '../../ui/InitialLoading'
import { PageHeader } from '../../ui/PageHeader'
import {
  describeRejection,
  isDefinitiveCreationRejection,
  serverError,
  unknownOutcomeMessage,
} from './creation'
import { WIZARD_STEPS } from './wizardSteps'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; plan: ReviewPlanResponse; catalog: ReviewCatalogItemResponse[] }

export type CaseSubmitState =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'rejected'; message: string; fieldErrors?: Record<string, string> }
  | { status: 'unknown'; message: string }

interface CaseFormValues {
  title: string
}

// 选项不超过 4 个用 Radio.Group，否则用 Select（docs/design.md「组件选用」）。
const RADIO_MAX_OPTIONS = 4

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function identity(item: ReviewCatalogItemResponse): string {
  return scenarioVersionText(item.scenario_key, item.scenario_version)
}

export function isDefinitiveRejection(error: unknown): boolean {
  return isDefinitiveCreationRejection(error)
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

export async function executeCaseSubmission(
  request: () => Promise<ReviewCaseResponse>,
  fields: readonly string[] = [],
): Promise<{ state: CaseSubmitState; reviewCase?: ReviewCaseResponse }> {
  try {
    return { state: { status: 'idle' }, reviewCase: await request() }
  } catch (error: unknown) {
    if (!isDefinitiveRejection(error)) {
      return { state: { status: 'unknown', message: unknownOutcomeMessage('审查活动', '重试创建审查活动', error) } }
    }
    const view = describeRejection(error, '审查活动创建被服务器拒绝，请修正后重试。', fields)
    return { state: { status: 'rejected', message: view.message, fieldErrors: view.fieldErrors } }
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

function WizardHeader({ title, titleId }: { title: string; titleId?: string }) {
  return (
    <>
      <PageHeader title={title} titleId={titleId} />
      <Steps current={1} items={WIZARD_STEPS} />
    </>
  )
}

export function ReviewCaseCreatePage() {
  const { planId } = useParams()
  const navigate = useNavigate()
  const [form] = Form.useForm<CaseFormValues>()
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [selectedIdentity, setSelectedIdentity] = useState('')
  const [scenarioValues, setScenarioValues] = useState<ScenarioFormValues>({})
  const [titleError, setTitleError] = useState<string | undefined>()
  const [scenarioErrors, setScenarioErrors] = useState<Record<string, string>>({})
  const [submitState, setSubmitState] = useState<CaseSubmitState>({ status: 'idle' })
  // 校验是异步的：双击或连按 Enter 时第二次提交可能先于重新渲染，用 ref 同步拦截。
  const inFlight = useRef(false)
  // One key per form lifetime: retries, double clicks and resubmits after a network failure share it.
  // 键和草稿由页面持有；Steps、Card 等展示组件卸载不会重建它，只有明确成功才换新键。
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
    setScenarioErrors(({ [name]: _cleared, ...rest }) => rest)
  }

  function onScenarioSelect(next: string): void {
    setSelectedIdentity(next)
    setScenarioValues({})
    setScenarioErrors({})
    setSubmitState({ status: 'idle' })
  }

  async function submitCase(values: CaseFormValues): Promise<void> {
    if (
      inFlight.current ||
      planId === undefined ||
      loadState.status !== 'ready' ||
      selectedItem === undefined ||
      scenarioAdapter === undefined ||
      !canCreateCase(scenarioAdapter, submitState)
    ) return

    inFlight.current = true
    setTitleError(undefined)
    setScenarioErrors({})
    setSubmitState({ status: 'submitting' })
    const scenarioFields = Object.keys(scenarioAdapter.buildCaseScenarioData({}))
    const result = await executeCaseSubmission(() => createReviewCase(
      buildCaseCreateInput(planId, selectedItem, values.title, scenarioAdapter, scenarioValues),
      idempotencyKey.current,
    ), ['title', ...scenarioFields])
    if (result.reviewCase !== undefined) {
      idempotencyKey.current = newIdempotencyKey()
      await navigate(`/review-cases/${encodeURIComponent(result.reviewCase.id)}`)
      return
    }
    inFlight.current = false
    const fieldErrors = result.state.status === 'rejected' ? (result.state.fieldErrors ?? {}) : {}
    // 提交期间表单是禁用的：先同步渲染出可编辑状态，才能聚焦到出错的字段。
    flushSync(() => {
      setSubmitState(result.state)
      setTitleError(fieldErrors.title)
      setScenarioErrors(Object.fromEntries(scenarioFields.flatMap((name) => {
        const text = fieldErrors[name]
        return text === undefined ? [] : [[name, text]]
      })))
    })
    if (result.state.status !== 'rejected') return
    // 聚焦第一个有错误的字段：先标题，再场景字段（按适配器的字段顺序）。
    if (fieldErrors.title !== undefined) {
      form.scrollToField('title', { focus: true })
    } else {
      const first = scenarioFields.find((name) => fieldErrors[name] !== undefined)
      if (first !== undefined) document.getElementById(caseCreateFieldId(first))?.focus()
    }
  }

  if (loadState.status === 'loading') {
    return (
      <Flex vertical gap={16} className="wizard-page" aria-busy>
        <WizardHeader title="新建审查活动" />
        <Card><InitialLoading label="正在恢复计划并读取当前可用场景…" rows={4} /></Card>
      </Flex>
    )
  }

  if (loadState.status === 'error') {
    return (
      <Flex vertical gap={16} className="wizard-page">
        <WizardHeader title="无法继续创建审查活动" />
        <Alert
          type="error"
          showIcon
          title={loadState.message}
          action={<Link to="/review-cases">返回审查活动</Link>}
        />
      </Flex>
    )
  }

  const unsupportedSelection = selectedItem !== undefined && scenarioAdapter === undefined
  const CaseCreateFields = scenarioAdapter?.CaseCreateFields
  const submitting = submitState.status === 'submitting'
  const scenarioOptions = loadState.catalog.map((item) => ({
    value: identity(item),
    disabled: resolveCaseScenarioAdapter(item.scenario_key, item.scenario_version) === undefined,
    name: scenarioName(item.scenario_key),
    version: identity(item),
  }))
  return (
    <Flex vertical gap={16} className="wizard-page">
      <WizardHeader title="新建审查活动" titleId="review-case-create-title" />

      <Card>
        <Flex vertical gap={16}>
          <h2>已恢复的审查计划</h2>
          <Descriptions
            column={{ xs: 1, md: 2 }}
            items={[
              { key: 'title', label: '计划名称', children: loadState.plan.title },
              { key: 'id', label: '计划编号', children: loadState.plan.id },
            ]}
          />
        </Flex>
      </Card>

      <Card>
        <Flex vertical gap={16}>
          <h2>审查活动信息</h2>
          <Typography.Text type="secondary">
            审查活动名称必须单独填写；计划名称和计划日期不会自动复制到审查活动。
          </Typography.Text>
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            disabled={submitting}
            scrollToFirstError={{ focus: true }}
            onValuesChange={(changed) => {
              if ('title' in changed) setTitleError(undefined)
            }}
            onFinish={(values) => void submitCase(values)}
          >
            <Form.Item
              label="审查活动名称"
              name="title"
              {...serverError({ title: titleError }, 'title')}
              rules={[
                {
                  validator: (_, value: string | undefined) => {
                    const title = value ?? ''
                    if (title.trim() === '') return Promise.reject(<FieldError>请输入审查活动名称。</FieldError>)
                    if (title !== title.trim()) return Promise.reject(<FieldError>审查活动名称前后不能有空格。</FieldError>)
                    return Promise.resolve()
                  },
                },
              ]}
            >
              <Input maxLength={300} autoComplete="off" />
            </Form.Item>
            <Form.Item label="审查场景" htmlFor="case-create-scenario">
              {scenarioOptions.length <= RADIO_MAX_OPTIONS ? (
                <Radio.Group
                  id="case-create-scenario"
                  aria-label="审查场景"
                  vertical
                  value={selectedIdentity}
                  onChange={(event) => onScenarioSelect(event.target.value as string)}
                  options={scenarioOptions.map((option) => ({
                    value: option.value,
                    disabled: option.disabled,
                    label: (
                      <>
                        {option.name} <Typography.Text type="secondary">{option.version}</Typography.Text>
                      </>
                    ),
                  }))}
                />
              ) : (
                <Select
                  id="case-create-scenario"
                  value={selectedIdentity}
                  onChange={onScenarioSelect}
                  options={scenarioOptions.map((option) => ({
                    value: option.value,
                    disabled: option.disabled,
                    label: `${option.name} · ${option.version}`,
                  }))}
                />
              )}
            </Form.Item>
            {unsupportedSelection ? (
              <Alert type="warning" showIcon title="当前版本的审查场景界面暂不支持，创建已关闭。" className="wizard-alert" />
            ) : null}
            {CaseCreateFields === undefined ? null : (
              <CaseCreateFields
                values={scenarioValues}
                onChange={onScenarioChange}
                disabled={submitting}
                fieldErrors={scenarioErrors}
              />
            )}
            {submitState.status === 'rejected' && submitState.message !== '' ? (
              <Alert type="error" showIcon title={submitState.message} className="wizard-alert" />
            ) : null}
            {submitState.status === 'unknown' ? (
              <Alert
                type="warning"
                showIcon
                title={submitState.message}
                action={<Link to="/review-cases" target="_blank" rel="noopener noreferrer">在新标签页核对是否已创建</Link>}
                className="wizard-alert"
              />
            ) : null}
            <Flex justify="flex-end" gap={8} wrap>
              <ButtonLink to="/review-cases" autoInsertSpace={false}>取消</ButtonLink>
              <Button
                type="primary"
                htmlType="submit"
                loading={submitting}
                disabled={!canCreateCase(scenarioAdapter, submitState)}
              >
                {submitting
                  ? '正在创建审查活动…'
                  : submitState.status === 'unknown'
                    ? '重试创建审查活动'
                    : '创建审查活动'}
              </Button>
            </Flex>
          </Form>
        </Flex>
      </Card>
    </Flex>
  )
}
