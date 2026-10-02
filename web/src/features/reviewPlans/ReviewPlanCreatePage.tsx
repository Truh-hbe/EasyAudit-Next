import { Alert, Button, Card, Flex, Form, Input, Steps, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { createReviewPlan, getReviewCatalog, newIdempotencyKey } from '../../api/product'
import type { ReviewCatalogItemResponse, ReviewPlanResponse } from '../../api/product'
import {
  DISPLAY_TIME_ZONE_HINT,
  invalidDisplayZoneInputMessage,
  parseOptionalDisplayZoneText,
} from '../../product/format'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import { FieldError } from '../../ui/FieldError'
import { ItemList } from '../../ui/ItemList'
import { PageHeader } from '../../ui/PageHeader'
import { ShanghaiDateTimePicker } from '../../ui/ShanghaiDateTimePicker'
import {
  clearedErrors,
  describeRejection,
  isDefinitiveCreationRejection,
  serverError,
  unknownOutcomeMessage,
} from './creation'
import { WIZARD_STEPS } from './wizardSteps'

type CatalogState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: ReviewCatalogItemResponse[] }

export type PlanSubmitState =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'rejected'; message: string; fieldErrors?: Record<string, string> }
  | { status: 'unknown'; message: string }

interface PlanFormValues {
  title: string
  planned_start_at: string | undefined
  planned_end_at: string | undefined
}

const PLAN_FIELDS = ['title', 'planned_start_at', 'planned_end_at'] as const
const TIME_ZONE_HINT_ID = 'plan-time-zone-hint'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function isDefinitivePlanRejection(error: unknown): boolean {
  return isDefinitiveCreationRejection(error)
}

// An unknown outcome may be retried by hand: the retry reuses the form's Idempotency-Key, so the
// server either creates the plan once or replays the first result. It is never retried automatically.
export function canSubmitPlan(state: PlanSubmitState): boolean {
  return state.status !== 'submitting'
}

export async function executePlanSubmission(
  request: () => Promise<ReviewPlanResponse>,
): Promise<{ state: PlanSubmitState; plan?: ReviewPlanResponse }> {
  try {
    return { state: { status: 'idle' }, plan: await request() }
  } catch (error: unknown) {
    if (!isDefinitivePlanRejection(error)) {
      return { state: { status: 'unknown', message: unknownOutcomeMessage('审查计划', '重试保存计划', error) } }
    }
    const view = describeRejection(error, '审查计划创建被服务器拒绝，请修正后重试。', PLAN_FIELDS)
    return { state: { status: 'rejected', message: view.message, fieldErrors: view.fieldErrors } }
  }
}

// 校验失败以 FieldError 元素作为提示（达标配色）；rc-field-form 会原样渲染 ReactNode 提示。
function timeRules(label: string) {
  return [
    {
      validator: (_: unknown, value: string | undefined): Promise<void> =>
        parseOptionalDisplayZoneText(value ?? '').valid
          ? Promise.resolve()
          : Promise.reject(<FieldError>{invalidDisplayZoneInputMessage(label)}</FieldError>),
    },
  ]
}

export function ReviewPlanCreatePage() {
  const navigate = useNavigate()
  const [form] = Form.useForm<PlanFormValues>()
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'loading' })
  const [submitState, setSubmitState] = useState<PlanSubmitState>({ status: 'idle' })
  // 服务端 422 对应到字段的提示；用户修改该字段后清除。
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})
  const submitting = submitState.status === 'submitting'
  // 校验是异步的：双击或连按 Enter 时第二次提交可能先于重新渲染，用 ref 同步拦截。
  const inFlight = useRef(false)
  // One key per form lifetime: retries, double clicks and resubmits after a network failure share it.
  // 键和草稿都由页面持有；Steps、Card 等展示组件卸载不会重建它，只有明确成功才换新键。
  const idempotencyKey = useRef(newIdempotencyKey())

  useEffect(() => {
    const controller = new AbortController()
    void getReviewCatalog(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setCatalog({ status: 'ready', items })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setCatalog({ status: 'error', message: errorMessage(error, '审查场景目录读取失败') })
      })
    return () => controller.abort()
  }, [])

  async function submitPlan(values: PlanFormValues): Promise<void> {
    if (inFlight.current) return
    // 无效时间不能当作"未填写"提交；保留输入和幂等键，由用户修改后重试。
    const startAt = parseOptionalDisplayZoneText(values.planned_start_at ?? '')
    const endAt = parseOptionalDisplayZoneText(values.planned_end_at ?? '')
    if (!startAt.valid || !endAt.valid) return

    inFlight.current = true
    setServerErrors({})
    setSubmitState({ status: 'submitting' })
    const result = await executePlanSubmission(() => createReviewPlan({
      title: values.title,
      planned_start_at: startAt.iso,
      planned_end_at: endAt.iso,
    }, idempotencyKey.current))
    if (result.plan !== undefined) {
      idempotencyKey.current = newIdempotencyKey()
      await navigate(`/review-plans/${encodeURIComponent(result.plan.id)}/review-cases/new`)
      return
    }
    inFlight.current = false
    setSubmitState(result.state)
    if (result.state.status === 'rejected') {
      const fieldErrors = result.state.fieldErrors ?? {}
      setServerErrors(fieldErrors)
      const first = PLAN_FIELDS.find((name) => fieldErrors[name] !== undefined)
      if (first !== undefined) form.scrollToField(first, { focus: true })
    }
  }

  const unavailable = catalog.status !== 'ready' || catalog.items.length === 0
  const retrying = submitState.status === 'rejected' || submitState.status === 'unknown'

  return (
    <Flex vertical gap={16} className="wizard-page">
      <PageHeader title="新建审查计划" titleId="review-plan-create-title" />
      <Steps current={0} items={WIZARD_STEPS} />

      {catalog.status === 'error' ? <Alert type="error" showIcon title={catalog.message} /> : null}
      {catalog.status === 'ready' && catalog.items.length === 0 ? (
        <Alert type="warning" showIcon title="当前没有可创建的已发布审查场景。" />
      ) : null}

      <Card>
        <Flex vertical gap={16}>
          <h2>计划信息</h2>
          <Typography.Text type="secondary">计划保存成功后，下一步会使用地址中的计划编号继续。</Typography.Text>
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            disabled={submitting}
            scrollToFirstError={{ focus: true }}
            onValuesChange={(changed) => setServerErrors(clearedErrors(serverErrors, changed))}
            onFinish={(values) => void submitPlan(values)}
          >
            <Form.Item
              label="计划名称"
              name="title"
              {...serverError(serverErrors, 'title')}
              rules={[
                {
                  validator: (_, value: string | undefined) => {
                    const title = value ?? ''
                    if (title.trim() === '') return Promise.reject(<FieldError>请输入审查计划名称。</FieldError>)
                    if (title !== title.trim()) return Promise.reject(<FieldError>审查计划名称前后不能有空格。</FieldError>)
                    return Promise.resolve()
                  },
                },
              ]}
            >
              <Input maxLength={300} autoComplete="off" />
            </Form.Item>
            <Typography.Paragraph id={TIME_ZONE_HINT_ID} type="secondary">{DISPLAY_TIME_ZONE_HINT}</Typography.Paragraph>
              <Form.Item label="计划开始时间（可选）" name="planned_start_at" {...serverError(serverErrors, 'planned_start_at')} rules={timeRules('计划开始时间')}>
                <ShanghaiDateTimePicker aria-describedby={TIME_ZONE_HINT_ID} />
              </Form.Item>
              <Form.Item label="计划结束时间（可选）" name="planned_end_at" {...serverError(serverErrors, 'planned_end_at')} rules={timeRules('计划结束时间')}>
                <ShanghaiDateTimePicker aria-describedby={TIME_ZONE_HINT_ID} />
              </Form.Item>
            {submitState.status === 'rejected' && submitState.message !== '' ? (
              <Alert type="error" showIcon title={submitState.message} className="wizard-alert" />
            ) : null}
            {submitState.status === 'unknown' ? (
              <Alert
                type="warning"
                showIcon
                title={submitState.message}
                action={<Link to="/review-cases">返回审查活动，查看服务器结果</Link>}
                className="wizard-alert"
              />
            ) : null}
            <Flex justify="flex-end">
              <Button type="primary" htmlType="submit" loading={submitting} disabled={unavailable}>
                {submitting ? '正在保存计划…' : retrying ? '重试保存计划' : '保存计划并继续'}
              </Button>
            </Flex>
          </Form>
        </Flex>
      </Card>

      {catalog.status === 'ready' ? (
        <Card>
          <Flex vertical gap={12}>
            <h2>本次可创建的场景</h2>
            <ItemList
              label="可用审查场景"
              emptyText="当前没有可创建的已发布审查场景。"
              items={catalog.items.map((item) => {
                const supported = resolveCaseScenarioAdapter(item.scenario_key, item.scenario_version) !== undefined
                const identity = scenarioVersionText(item.scenario_key, item.scenario_version)
                return {
                  key: identity,
                  content: (
                    <Flex align="center" wrap gap={8}>
                      <Typography.Text strong>{scenarioName(item.scenario_key)}</Typography.Text>
                      <Typography.Text type="secondary">{identity}</Typography.Text>
                      <Typography.Text type="secondary">
                        {supported ? '可在下一步选择' : '当前页面暂不支持'}
                      </Typography.Text>
                    </Flex>
                  ),
                }
              })}
            />
          </Flex>
        </Card>
      ) : null}
    </Flex>
  )
}
