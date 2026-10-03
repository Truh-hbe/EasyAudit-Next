import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Flex, Form, Input, Radio, Typography } from 'antd'
import type { InputRef } from 'antd'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { createFinding } from '../../api/product'
import type { FindingSeverity, ReviewCaseResponse } from '../../api/product'
import { classifyCommandFailure, failureAlertType } from '../../product/commandFailure'
import type { CommandFailure } from '../../product/commandFailure'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { resolveFindingScenarioAdapter } from '../../scenarios'
import { findingCreateFieldId } from '../../scenarios/FindingCreateFields'
import type { ScenarioFormValues } from '../../scenarios/registry'
import { FieldError } from '../../ui/FieldError'
import { statusLabel } from '../../ui/StatusTag'

interface FindingCreatePanelProps {
  reviewCase: ReviewCaseResponse
}

const SEVERITIES: readonly FindingSeverity[] = ['low', 'medium', 'high', 'critical']
const BASE_FIELDS = ['title', 'description', 'severity'] as const

function fieldError(errors: Record<string, string>, name: string) {
  const text = errors[name]
  return text === undefined
    ? {}
    : { validateStatus: 'error' as const, help: <FieldError>{text}</FieldError> }
}

// 审查活动详情页仍是遗留容器，所以整个面板放在 .ui-modern 边界内，避免遗留元素样式作用到 antd 控件。
export function FindingCreatePanel({ reviewCase }: FindingCreatePanelProps) {
  const navigate = useNavigate()
  const adapter = resolveFindingScenarioAdapter(reviewCase.scenario_key, reviewCase.scenario_version)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<FindingSeverity>('medium')
  const [scenarioValues, setScenarioValues] = useState<ScenarioFormValues>({})
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<CommandFailure | null>(null)
  const submittingRef = useRef(false)
  const titleRef = useRef<InputRef>(null)

  if (adapter === undefined) {
    return (
      <div className="ui-modern">
        <section aria-labelledby="create-finding-title">
          <Card title={<h2 id="create-finding-title">新建发现项</h2>}>
            <Alert
              type="warning"
              showIcon
              title={`当前审查场景的界面暂不支持创建发现项（${scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}）。`}
            />
          </Card>
        </section>
      </div>
    )
  }

  const scenarioAdapter = adapter
  const ScenarioFields = scenarioAdapter.FindingCreateFields
  const scenarioFieldNames = Object.keys(scenarioAdapter.buildFindingScenarioData({}))
  const fieldErrors = failure?.fieldErrors ?? {}

  function clearFieldError(name: string) {
    setFailure((current) => {
      if (current === null || !(name in current.fieldErrors)) return current
      return {
        ...current,
        fieldErrors: Object.fromEntries(Object.entries(current.fieldErrors).filter(([field]) => field !== name)),
      }
    })
  }

  function focusFirstError(errors: Record<string, string>) {
    const first = [...BASE_FIELDS, ...scenarioFieldNames].find((name) => name in errors)
    if (first === undefined) return
    if (first === 'title') titleRef.current?.focus()
    else document.getElementById(findingCreateFieldId(first))?.focus()
  }

  async function submit() {
    if (submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    setFailure(null)
    try {
      const finding = await createFinding(reviewCase.id, {
        title,
        description: description.length > 0 ? description : null,
        severity,
        scenario_data: scenarioAdapter.buildFindingScenarioData(scenarioValues),
      })
      navigate(`/findings/${finding.id}`)
    } catch (error) {
      const classified = classifyCommandFailure(error, {
        label: '创建发现项',
        fields: [...BASE_FIELDS, ...scenarioFieldNames],
      })
      // 创建请求没有幂等键：结果未知时不能直接重试，先核对列表以免重复创建。
      const next =
        classified.kind === 'unknown-result'
          ? { ...classified, message: '未确认发现项是否已创建。请先刷新页面，在发现项列表中核对后再决定是否重新创建；本页内容已保留。' }
          : classified
      setFailure(next)
      window.setTimeout(() => focusFirstError(next.fieldErrors), 0)
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <div className="ui-modern">
      <section aria-labelledby="create-finding-title">
        <Card
          title={<h2 id="create-finding-title">新建发现项</h2>}
          extra={<Typography.Text type="secondary">{scenarioName(reviewCase.scenario_key)}</Typography.Text>}
        >
          <Form layout="vertical" requiredMark={false} disabled={submitting} onFinish={() => void submit()}>
            {failure === null || failure.message === '' || failure.kind === 'session' ? null : (
              <Alert type={failureAlertType(failure)} showIcon title={failure.message} style={{ marginBottom: 16 }} />
            )}
            <Form.Item label="标题" htmlFor={findingCreateFieldId('title')} {...fieldError(fieldErrors, 'title')}>
              <Input
                id={findingCreateFieldId('title')}
                ref={titleRef}
                value={title}
                onChange={(event) => {
                  setTitle(event.target.value)
                  clearFieldError('title')
                }}
                autoComplete="off"
              />
            </Form.Item>
            <Form.Item label="严重度" {...fieldError(fieldErrors, 'severity')}>
              <Radio.Group
                aria-label="严重度"
                value={severity}
                onChange={(event) => {
                  setSeverity(event.target.value as FindingSeverity)
                  clearFieldError('severity')
                }}
                options={SEVERITIES.map((value) => ({ value, label: statusLabel('severity', value) ?? value }))}
              />
            </Form.Item>
            <Form.Item label="描述" htmlFor={findingCreateFieldId('description')} {...fieldError(fieldErrors, 'description')}>
              <Input.TextArea
                id={findingCreateFieldId('description')}
                value={description}
                onChange={(event) => {
                  setDescription(event.target.value)
                  clearFieldError('description')
                }}
                rows={3}
              />
            </Form.Item>
            <ScenarioFields
              values={scenarioValues}
              onChange={(name, value) => {
                setScenarioValues((current) => ({ ...current, [name]: value }))
                clearFieldError(name)
              }}
              disabled={submitting}
              fieldErrors={fieldErrors}
            />
            <Flex justify="flex-end" align="center" wrap gap={12}>
              <Typography.Text type="secondary">服务器校验通过后才会保存发现项。</Typography.Text>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined aria-hidden />} loading={submitting}>
                新建发现项
              </Button>
            </Flex>
          </Form>
        </Card>
      </section>
    </div>
  )
}
