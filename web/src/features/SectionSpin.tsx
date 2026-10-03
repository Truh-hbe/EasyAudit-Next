import { Spin } from 'antd'
import type { ReactNode } from 'react'

import type { ResourceState } from './useScopedResource'

// 区块自己的刷新反馈：刷新期间保留旧内容，区块上加 Spin 并标出“正在刷新”。
export function SectionSpin({ state, children }: { state: ResourceState<unknown>; children: ReactNode }) {
  const refreshing = state.status === 'ready' && state.refreshing
  return (
    <Spin spinning={refreshing} description="正在刷新">
      {children}
    </Spin>
  )
}
