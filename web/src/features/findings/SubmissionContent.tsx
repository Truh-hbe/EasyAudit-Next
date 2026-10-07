import { Alert, Descriptions, Typography } from 'antd'

import type { ScenarioSubmissionView } from '../../scenarios/registry'

// 用户填写的正文一律按纯文本渲染（保留换行），超过三行折叠。
export function LongText({ text }: { text: string }) {
  return (
    <Typography.Paragraph
      className="submission-text"
      ellipsis={{ rows: 3, expandable: 'collapsible', symbol: (expanded: boolean) => (expanded ? '收起' : '展开') }}
    >
      {text}
    </Typography.Paragraph>
  )
}

export function SubmissionContent({ view }: { view: ScenarioSubmissionView }) {
  const items = [...view.fields, ...view.extras]
  if (items.length === 0) {
    return <Typography.Text type="secondary">该提交没有可显示的内容。</Typography.Text>
  }
  return (
    <Descriptions
      size="small"
      column={1}
      items={items.map((item) => ({ key: item.key, label: item.label, children: <LongText text={item.value} /> }))}
    />
  )
}

interface RejectionNoticeProps {
  view: ScenarioSubmissionView
  meta: string
}

// 发现项回到整改中时，最近一次驳回原因显示在页面上方，整改负责人无需翻提交记录。
export function RejectionNotice({ view, meta }: RejectionNoticeProps) {
  const reason = view.fields[0]
  return (
    <Alert
      type="warning"
      showIcon
      role="status"
      title="最近一次验证被驳回，请按驳回原因补做整改"
      description={
        <>
          {reason === undefined ? <Typography.Text>验证人未填写驳回原因。</Typography.Text> : <LongText text={reason.value} />}
          <Typography.Text type="secondary">{meta}</Typography.Text>
        </>
      }
    />
  )
}
