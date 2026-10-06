import { Card, Descriptions } from 'antd'

import type { ScenarioDescriptionItem } from './registry'

interface ScenarioFieldsCardProps {
  id: string
  title: string
  items: readonly ScenarioDescriptionItem[]
}

// 审查活动详情中的场景信息区块。
export function ScenarioFieldsCard({ id, title, items }: ScenarioFieldsCardProps) {
  return (
    <section aria-labelledby={id}>
      <Card title={<h2 id={id}>{title}</h2>}>
        <Descriptions
          column={{ xs: 1, md: 2 }}
          items={items.map((item) => ({ key: item.key, label: item.label, children: item.value }))}
        />
      </Card>
    </section>
  )
}
