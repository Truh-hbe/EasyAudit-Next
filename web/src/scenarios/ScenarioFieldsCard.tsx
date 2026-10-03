import { Card, Descriptions } from 'antd'

import type { ScenarioDescriptionItem } from './registry'

interface ScenarioFieldsCardProps {
  id: string
  title: string
  items: readonly ScenarioDescriptionItem[]
}

// 审查活动详情中的场景信息区块。审查活动详情页仍在遗留容器内渲染它，所以放进 .ui-modern 边界。
export function ScenarioFieldsCard({ id, title, items }: ScenarioFieldsCardProps) {
  return (
    <div className="ui-modern">
      <section aria-labelledby={id}>
        <Card title={<h2 id={id}>{title}</h2>}>
          <Descriptions
            column={{ xs: 1, md: 2 }}
            items={items.map((item) => ({ key: item.key, label: item.label, children: item.value }))}
          />
        </Card>
      </section>
    </div>
  )
}
