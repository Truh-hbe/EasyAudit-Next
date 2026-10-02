import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Empty, Flex, Row, Skeleton, Spin, Table, Typography } from 'antd'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { getWorkbench } from '../../api/product'
import type { WorkbenchResponse } from '../../api/product'
import { formatDateTime } from '../../product/format'
import { PageHeader } from '../../ui/PageHeader'
import { StatusTag } from '../../ui/StatusTag'

type WorkbenchState =
  | { status: 'loading'; data: WorkbenchResponse | null }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: WorkbenchResponse }

interface WorkRow {
  key: string
  to: string
  title: string
  meta: ReactNode
}

function WorkList({ rows, emptyText }: { rows: WorkRow[]; emptyText: string }) {
  return (
    <Table<WorkRow>
      size="middle"
      showHeader={false}
      pagination={false}
      rowKey="key"
      dataSource={rows}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} /> }}
      columns={[
        {
          key: 'item',
          render: (_, row) => (
            <Flex vertical gap={4}>
              <Link to={row.to}>{row.title}</Link>
              <Flex align="center" wrap gap={8}>{row.meta}</Flex>
            </Flex>
          ),
        },
      ]}
    />
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Col xs={24} lg={12}>
      <Card>
        <Flex vertical gap={12}>
          <h2>{title}</h2>
          {children}
        </Flex>
      </Card>
    </Col>
  )
}

function secondary(text: string) {
  return <Typography.Text type="secondary">{text}</Typography.Text>
}

function sections(data: WorkbenchResponse) {
  const verification: WorkRow[] = data.verification_queue.map((item) => ({
    key: item.id,
    to: `/findings/${item.id}`,
    title: item.title,
    meta: (
      <>
        <StatusTag kind="severity" value={item.severity} />
        {secondary(`提出于 ${formatDateTime(item.raised_at)}`)}
      </>
    ),
  }))
  const findings: WorkRow[] = data.finding_responsibilities.map((item) => ({
    key: item.id,
    to: `/findings/${item.id}`,
    title: item.title,
    meta: (
      <>
        <StatusTag kind="severity" value={item.severity} />
        <StatusTag kind="finding" value={item.lifecycle} />
        {secondary(`提出于 ${formatDateTime(item.raised_at)}`)}
      </>
    ),
  }))
  const actions: WorkRow[] = data.action_responsibilities.map((item) => ({
    key: item.id,
    to: `/action-items/${item.id}`,
    title: item.title,
    meta: (
      <>
        <StatusTag kind="actionItem" value={item.lifecycle} />
        {secondary(`到期 ${formatDateTime(item.due_at)}`)}
      </>
    ),
  }))
  const deadlines = (group: WorkbenchResponse['overdue']): WorkRow[] => [
    ...group.cases.map((item) => ({
      key: `case-${item.id}`,
      to: `/review-cases/${item.id}`,
      title: item.title,
      meta: (
        <>
          {secondary('审查活动')}
          <StatusTag kind="reviewCase" value={item.lifecycle} />
          {secondary(formatDateTime(item.deadline))}
        </>
      ),
    })),
    ...group.actions.map((item) => ({
      key: `action-${item.id}`,
      to: `/action-items/${item.id}`,
      title: item.title,
      meta: (
        <>
          {secondary('整改项')}
          <StatusTag kind="actionItem" value={item.lifecycle} />
          {secondary(formatDateTime(item.deadline))}
        </>
      ),
    })),
  ]
  const cases: WorkRow[] = data.case_responsibilities.map((item) => ({
    key: item.id,
    to: `/review-cases/${item.id}`,
    title: item.title,
    meta: (
      <>
        <StatusTag kind="reviewCase" value={item.lifecycle} />
        {secondary(`计划结束 ${formatDateTime(item.planned_end_at)}`)}
        {secondary(`关系 ${item.role_keys.join(' / ') || '—'}`)}
      </>
    ),
  }))

  return [
    { title: '待我验证', rows: verification, emptyText: '暂无待验证发现项。' },
    { title: '发现项责任', rows: findings, emptyText: '暂无发现项责任。' },
    { title: '整改项责任', rows: actions, emptyText: '暂无整改项责任。' },
    { title: '已逾期', rows: deadlines(data.overdue), emptyText: '暂无已逾期事项。' },
    { title: '即将到期', rows: deadlines(data.due_soon), emptyText: '暂无即将到期事项。' },
    { title: '我参与的审查', rows: cases, emptyText: '暂无我参与的审查。' },
  ]
}

export function WorkbenchPage() {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<WorkbenchState>({ status: 'loading', data: null })

  useEffect(() => {
    const controller = new AbortController()
    // 刷新时保留旧内容；请求失败则移除，不用旧数据兜底。
    setState((previous) => ({
      status: 'loading',
      data: previous.status === 'error' ? null : previous.data,
    }))
    void getWorkbench(controller.signal)
      .then((data) => setState({ status: 'ready', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : '我的工作请求失败',
        })
      })
    return () => controller.abort()
  }, [revision])

  const data = state.status === 'error' ? null : state.data
  const refreshing = state.status === 'loading' && state.data !== null

  return (
    <Spin spinning={refreshing}>
      <Flex vertical gap={16}>
        <PageHeader
          title="我的工作"
          titleId="workbench-title"
          meta={data === null ? undefined : secondary(`数据时间 ${formatDateTime(data.as_of)}`)}
          extra={
            <Button
              icon={<ReloadOutlined aria-hidden />}
              loading={refreshing}
              disabled={state.status === 'loading'}
              onClick={() => setRevision((value) => value + 1)}
            >
              刷新
            </Button>
          }
        />
        {state.status === 'error' ? (
          <Alert
            type="error"
            showIcon
            title={state.message}
            action={
              <Button size="small" onClick={() => setRevision((value) => value + 1)}>
                重新加载
              </Button>
            }
          />
        ) : null}
        {state.status === 'loading' && data === null ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
        {data === null ? null : (
          <Row gutter={[16, 16]}>
            {sections(data).map((section) => (
              <Section key={section.title} title={section.title}>
                <WorkList rows={section.rows} emptyText={section.emptyText} />
              </Section>
            ))}
          </Row>
        )}
      </Flex>
    </Spin>
  )
}
