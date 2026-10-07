import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Empty, Flex, Form, Input, Radio, Result, Select, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { cloneElement, useEffect, useRef, useState } from 'react'
import type { ReactElement } from 'react'
import { Link } from 'react-router'

import {
  exportManagedReviewCases,
  listManagedReviewCases,
} from '../../api/management'
import type {
  ManagementCaseCollectionResponse,
  ManagementDeadlineFilter,
  ManagementExportFormat,
} from '../../api/management'
import type { DeadlineBucket, ManagementCaseSummary, ReviewCaseLifecycle } from '../../api/product'
import { formatDateTime } from '../../product/format'
import { NOT_AVAILABLE_TEXT } from '../../product/commandFailure'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { InitialLoading } from '../../ui/InitialLoading'
import { PageHeader } from '../../ui/PageHeader'
import { isDeadlineStatus, StatusTag, statusLabel } from '../../ui/StatusTag'
import { isUnavailable } from '../useScopedResource'

interface ManagementState {
  // 仅保留最近一次成功的结果；请求失败时清空，不用旧数据兜底。
  data: ManagementCaseCollectionResponse | null
  loading: boolean
  error: string | null
}

const PAGE_SIZE = 20

const LIFECYCLES: ReviewCaseLifecycle[] = [
  'draft',
  'scheduled',
  'in_progress',
  'awaiting_closure',
  'closed',
  'cancelled',
]

const lifecycleOptions = [
  { value: '', label: '全部' },
  ...LIFECYCLES.map((value) => ({ value, label: statusLabel('reviewCase', value) })),
]

const deadlineOptions: Array<{ value: ManagementDeadlineFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'due_soon', label: '即将到期' },
  { value: 'overdue', label: '已逾期' },
]

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function saveFile(file: { blob: Blob; filename: string }): void {
  const url = URL.createObjectURL(file.blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = file.filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function DeadlineBucketText({ bucket }: { bucket: DeadlineBucket }) {
  if (isDeadlineStatus(bucket)) return <StatusTag kind="deadline" value={bucket} />
  return <Typography.Text type="secondary">{bucket === 'later' ? '稍后到期' : '无当前期限'}</Typography.Text>
}

const columns: TableColumnsType<ManagementCaseSummary> = [
  {
    title: '审查活动',
    key: 'title',
    render: (_value: unknown, item) => (
      <Flex vertical>
        <strong>{item.title}</strong>
        <Typography.Text type="secondary">
          {scenarioName(item.scenario_key)} · {scenarioVersionText(item.scenario_key, item.scenario_version)}
        </Typography.Text>
      </Flex>
    ),
  },
  {
    title: '状态',
    key: 'status',
    render: (_value: unknown, item) => (
      <Flex wrap gap={4}>
        <StatusTag kind="reviewCase" value={item.lifecycle} />
        <DeadlineBucketText bucket={item.deadline_bucket} />
      </Flex>
    ),
  },
  {
    title: '计划结束',
    key: 'planned_end_at',
    render: (_value: unknown, item) => formatDateTime(item.planned_end_at),
  },
  {
    title: '发现项',
    key: 'findings',
    width: 200,
    render: (_value: unknown, item) =>
      `共 ${item.findings.total} / 待处理 ${item.findings.open} / 整改中 ${item.findings.rectifying} / 待验证 ${item.findings.verifying} / 已关闭 ${item.findings.closed} / 已作废 ${item.findings.voided}`,
  },
  {
    title: '整改项',
    key: 'actions',
    width: 200,
    render: (_value: unknown, item) =>
      `共 ${item.actions.total} / 待开始 ${item.actions.todo} / 执行中 ${item.actions.in_progress} / 已完成 ${item.actions.done} / 已取消 ${item.actions.cancelled} / 已逾期 ${item.actions.overdue} / 即将到期 ${item.actions.due_soon}`,
  },
  {
    title: '操作',
    key: 'operations',
    render: (_value: unknown, item) => (
      <Flex vertical>
        <Link to={`/management/review-cases/${item.id}`}>查看管理进度</Link>
        <Link to={`/review-cases/${item.id}`}>打开审查活动</Link>
      </Flex>
    ),
  },
]

export function ManagementPage() {
  const [lifecycle, setLifecycle] = useState<ReviewCaseLifecycle | ''>('')
  const [deadlineStatus, setDeadlineStatus] = useState<ManagementDeadlineFilter>('all')
  const [reviewPlanInput, setReviewPlanInput] = useState('')
  const [reviewPlanId, setReviewPlanId] = useState('')
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const requestSequenceRef = useRef(0)
  const [exporting, setExporting] = useState<ManagementExportFormat | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  // 403 之后保护内容整体移除；后端撤销授权不会因换筛选条件而恢复。
  const [denied, setDenied] = useState(false)
  const [state, setState] = useState<ManagementState>({ data: null, loading: true, error: null })

  useEffect(() => {
    if (denied) return undefined
    const controller = new AbortController()
    const sequence = requestSequenceRef.current + 1
    requestSequenceRef.current = sequence
    setState((previous) => ({ ...previous, loading: true, error: null }))

    void listManagedReviewCases(
      {
        reviewPlanId: reviewPlanId.length === 0 ? undefined : reviewPlanId,
        lifecycle: lifecycle === '' ? undefined : lifecycle,
        deadlineStatus,
        limit: PAGE_SIZE,
        offset,
      },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({ data, loading: false, error: null })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        if (isUnavailable(error)) {
          setDenied(true)
          return
        }
        setState({ data: null, loading: false, error: errorMessage(error, '管理视图请求失败') })
      })

    return () => controller.abort()
  }, [denied, deadlineStatus, lifecycle, offset, reviewPlanId, revision])

  function exportCases(format: ManagementExportFormat) {
    setExporting(format)
    setExportError(null)
    // The export is a server snapshot of the same filters, not of the page being shown.
    void exportManagedReviewCases(format, {
      reviewPlanId: reviewPlanId.length === 0 ? undefined : reviewPlanId,
      lifecycle: lifecycle === '' ? undefined : lifecycle,
      deadlineStatus,
    })
      .then(saveFile)
      .catch((error: unknown) => {
        if (isUnavailable(error)) {
          setDenied(true)
          return
        }
        setExportError(errorMessage(error, '导出失败'))
      })
      .finally(() => setExporting(null))
  }

  if (denied) {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="管理视图" titleId="management-title" />
        <Card>
          <Result status="404" title={NOT_AVAILABLE_TEXT} />
        </Card>
      </Flex>
    )
  }

  const { data } = state
  const initialLoading = state.loading && data === null

  return (
    <Flex vertical gap={16} aria-busy={initialLoading}>
      <PageHeader
        title="管理视图"
        titleId="management-title"
        meta={
          data === null ? undefined : (
            <Typography.Text type="secondary">{`数据时间 ${formatDateTime(data.as_of)}`}</Typography.Text>
          )
        }
        extra={
          <>
            <Button
              icon={<DownloadOutlined aria-hidden />}
              disabled={exporting !== null}
              loading={exporting === 'csv'}
              onClick={() => exportCases('csv')}
            >导出 CSV</Button>
            <Button
              icon={<DownloadOutlined aria-hidden />}
              disabled={exporting !== null}
              loading={exporting === 'xlsx'}
              onClick={() => exportCases('xlsx')}
            >导出 XLSX</Button>
          </>
        }
      />

      {exportError === null ? null : <Alert type="error" showIcon title={exportError} />}

      <Card>
        <Form
          layout="inline"
          aria-label="筛选条件"
          onFinish={() => {
            setReviewPlanId(reviewPlanInput.trim())
            setOffset(0)
          }}
        >
          <Form.Item label="审查活动状态" htmlFor="management-lifecycle">
            <Select
              id="management-lifecycle"
              style={{ width: 160 }}
              value={lifecycle}
              options={lifecycleOptions}
              onChange={(value: ReviewCaseLifecycle | '') => {
                setLifecycle(value)
                setOffset(0)
              }}
            />
          </Form.Item>
          <Form.Item label="截止情况" style={{ maxWidth: '100%' }}>
            <Radio.Group
              aria-label="截止情况"
              style={{ display: 'flex', flexWrap: 'wrap' }}
              value={deadlineStatus}
              options={deadlineOptions}
              onChange={(event) => {
                setDeadlineStatus(event.target.value as ManagementDeadlineFilter)
                setOffset(0)
              }}
            />
          </Form.Item>
          <Form.Item label="审查计划 ID" htmlFor="management-plan-id">
            <Input
              id="management-plan-id"
              value={reviewPlanInput}
              onChange={(event) => setReviewPlanInput(event.target.value)}
              placeholder="可选，填写审查计划 ID"
            />
          </Form.Item>
          <Form.Item>
            <Flex gap={8}>
              <Button htmlType="submit" icon={<SearchOutlined aria-hidden />}>按审查计划筛选</Button>
              <Button
                onClick={() => {
                  setReviewPlanInput('')
                  setReviewPlanId('')
                  setLifecycle('')
                  setDeadlineStatus('all')
                  setOffset(0)
                }}
              >清除筛选</Button>
            </Flex>
          </Form.Item>
        </Form>
        <Typography.Text type="secondary">筛选、授权、截止分组、汇总与分页均以服务器结果为准。</Typography.Text>
      </Card>

      {state.error === null ? null : (
        <Alert
          type="error"
          showIcon
          title={state.error}
          action={<Button size="small" onClick={() => setRevision((value) => value + 1)}>重新加载</Button>}
        />
      )}

      {initialLoading ? <Card><InitialLoading label="正在读取管理视图" rows={6} /></Card> : null}

      {data === null ? null : (
        <Card
          title={<h2>我可管理的审查活动</h2>}
          extra={<Typography.Text type="secondary">{`共 ${data.total} 项`}</Typography.Text>}
        >
          <Table<ManagementCaseSummary>
            size="middle"
            rowKey="id"
            columns={columns}
            dataSource={data.items}
            loading={state.loading}
            scroll={{ x: 'max-content' }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={data.total > 0 ? '当前页没有审查活动。' : '当前筛选下没有可管理的审查活动。'}
                />
              ),
            }}
            pagination={{
              current: Math.floor(data.offset / PAGE_SIZE) + 1,
              pageSize: PAGE_SIZE,
              total: data.total,
              showSizeChanger: false,
              hideOnSinglePage: true,
              showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}`,
              onChange: (page) => setOffset((page - 1) * PAGE_SIZE),
              // 翻页按钮内只有英文名的图标（"left"/"right"），补上中文可访问名称。
              itemRender: (_page, type, element) =>
                type === 'prev' || type === 'next'
                  ? cloneElement(element as ReactElement<{ 'aria-label'?: string }>, {
                      'aria-label': type === 'prev' ? '上一页' : '下一页',
                    })
                  : element,
            }}
          />
        </Card>
      )}
    </Flex>
  )
}
