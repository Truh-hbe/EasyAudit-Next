import { Flex } from 'antd'
import type { ReactNode } from 'react'

export interface PageHeaderProps {
  title: ReactNode
  titleId?: string
  // 标题旁的副信息：状态 Tag、数据时间、所属计划等。
  meta?: ReactNode
  // 右侧主操作。
  extra?: ReactNode
}

export function PageHeader({ title, titleId, meta, extra }: PageHeaderProps) {
  return (
    <Flex component="header" justify="space-between" align="flex-start" wrap gap={16}>
      <Flex vertical gap={8}>
        <h1 id={titleId}>{title}</h1>
        {meta === undefined ? null : <Flex align="center" wrap gap={8}>{meta}</Flex>}
      </Flex>
      {extra === undefined ? null : <Flex align="center" wrap gap={8}>{extra}</Flex>}
    </Flex>
  )
}
