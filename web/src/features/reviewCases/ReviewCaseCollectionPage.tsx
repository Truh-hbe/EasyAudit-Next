import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Empty, Flex, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { cloneElement, useEffect, useMemo, useState } from 'react'
import type { ReactElement } from 'react'
import { Link, useSearchParams } from 'react-router'

import { listReviewCases } from '../../api/product'
import type { ReviewCaseCollectionResponse, ReviewCaseResponse } from '../../api/product'
import { formatDateTime } from '../../product/format'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { ButtonLink } from '../../ui/ButtonLink'
import { InitialLoading } from '../../ui/InitialLoading'
import { PageHeader } from '../../ui/PageHeader'
import { StatusTag } from '../../ui/StatusTag'

interface CollectionState {
  // 仅保留最近一次成功的结果；请求失败时清空，不用旧数据兜底。
  data: ReviewCaseCollectionResponse | null
  loading: boolean
  error: string | null
}

function boundedInteger(raw: string | null, fallback: number, minimum: number, maximum: number): number {
  if (raw === null || raw.trim() === '') return fallback
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isInteger(parsed)) return fallback
  return Math.min(maximum, Math.max(minimum, parsed))
}

function nonNegativeInteger(raw: string | null): number {
  if (raw === null || raw.trim() === '') return 0
  const parsed = Number.parseInt(raw, 10)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0
}

const columns: TableColumnsType<ReviewCaseResponse> = [
  {
    title: '状态',
    dataIndex: 'lifecycle',
    key: 'lifecycle',
    render: (_lifecycle: unknown, reviewCase) => <StatusTag kind="reviewCase" value={reviewCase.lifecycle} />,
  },
  {
    title: '审查活动',
    dataIndex: 'title',
    key: 'title',
    render: (_title: string, reviewCase) => <Link to={`/review-cases/${reviewCase.id}`}>{reviewCase.title}</Link>,
  },
  {
    title: '审查场景',
    key: 'scenario',
    render: (_value: unknown, reviewCase) => (
      <Flex vertical>
        <span>{scenarioName(reviewCase.scenario_key)}</span>
        <Typography.Text type="secondary">
          {scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}
        </Typography.Text>
      </Flex>
    ),
  },
  {
    title: '计划开始',
    dataIndex: 'planned_start_at',
    key: 'planned_start_at',
    render: (_value: unknown, reviewCase) => formatDateTime(reviewCase.planned_start_at),
  },
  {
    title: '计划结束',
    dataIndex: 'planned_end_at',
    key: 'planned_end_at',
    render: (_value: unknown, reviewCase) => formatDateTime(reviewCase.planned_end_at),
  },
]

export function ReviewCaseCollectionPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedLimit = useMemo(() => boundedInteger(searchParams.get('limit'), 50, 1, 100), [searchParams])
  const requestedOffset = useMemo(() => nonNegativeInteger(searchParams.get('offset')), [searchParams])
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<CollectionState>({ data: null, loading: true, error: null })

  useEffect(() => {
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true, error: null }))
    void listReviewCases(requestedLimit, requestedOffset, controller.signal)
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          data: null,
          loading: false,
          error: error instanceof Error ? error.message : '审查活动列表请求失败',
        })
      })
    return () => controller.abort()
  }, [requestedLimit, requestedOffset, revision])

  function moveTo(offset: number, limit: number): void {
    setSearchParams({ limit: String(limit), offset: String(Math.max(0, offset)) })
  }

  const { data } = state
  const initialLoading = state.loading && data === null

  const emptyText =
    data !== null && data.total > 0 ? (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前页没有审查活动。">
        <Button onClick={() => moveTo(0, requestedLimit)}>回到第一页</Button>
      </Empty>
    ) : (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无可见的审查活动。" />
    )

  return (
    <Flex vertical gap={16} aria-busy={initialLoading}>
      <PageHeader
        title="审查活动"
        titleId="review-case-list-title"
        meta={data === null ? undefined : <Typography.Text type="secondary">已授权 {data.total} 项</Typography.Text>}
        extra={
          <ButtonLink type="primary" to="/review-plans/new" icon={<PlusOutlined aria-hidden />}>
            新建审查计划
          </ButtonLink>
        }
      />

      {state.error === null ? null : (
        <Alert
          type="error"
          showIcon
          title={state.error}
          action={<Button size="small" onClick={() => setRevision((value) => value + 1)}>重新加载</Button>}
        />
      )}

      {initialLoading ? <Card><InitialLoading label="正在读取审查活动" rows={6} /></Card> : null}

      {data === null ? null : (
        <Card>
          <Table<ReviewCaseResponse>
            size="middle"
            rowKey="id"
            columns={columns}
            dataSource={data.items}
            loading={state.loading}
            scroll={{ x: 'max-content' }}
            locale={{ emptyText }}
            pagination={{
              current: Math.floor(data.offset / data.limit) + 1,
              pageSize: data.limit,
              total: data.total,
              showSizeChanger: false,
              hideOnSinglePage: true,
              showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}`,
              onChange: (page, pageSize) => moveTo((page - 1) * pageSize, pageSize),
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
