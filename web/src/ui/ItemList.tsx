import { Empty } from 'antd'
import type { ReactNode } from 'react'

export interface ItemListEntry {
  key: string
  content: ReactNode
}

export interface ItemListProps {
  items: readonly ItemListEntry[]
  // 无条目时显示的 Empty 描述；children 放在 Empty 内（如"清除筛选"按钮）。
  emptyText: string
  emptyAction?: ReactNode
  label?: string
}

// 简单条目的语义列表（ul/li）。antd Listy 输出的是无列表语义的 div（包内没有 role/aria），所以用语义化的 ul/li。
export function ItemList({ items, emptyText, emptyAction, label }: ItemListProps) {
  if (items.length === 0) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText}>
        {emptyAction}
      </Empty>
    )
  }
  return (
    <ul className="item-list" aria-label={label}>
      {items.map((item) => (
        <li key={item.key}>{item.content}</li>
      ))}
    </ul>
  )
}
