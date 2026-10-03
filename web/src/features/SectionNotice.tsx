import { Alert, Typography } from 'antd'

import { InitialLoading } from '../ui/InitialLoading'
import type { ResourceState } from './useScopedResource'

interface SectionNoticeProps {
  state: ResourceState<unknown>
  loadingLabel: string
  unavailableText: string
}

// 区块级的非 ready 状态：首次加载、不可用、读取失败；ready 时只在后台刷新失败时给出警告。
export function SectionNotice({ state, loadingLabel, unavailableText }: SectionNoticeProps) {
  if (state.status === 'loading') return <InitialLoading label={loadingLabel} rows={2} />
  if (state.status === 'unavailable') return <Typography.Text type="secondary">{unavailableText}</Typography.Text>
  if (state.status === 'error') return <Alert type="error" showIcon title={state.message} />
  if (state.refreshError !== null) {
    return <Alert type="warning" showIcon title={`重新读取失败，当前显示的可能不是最新内容：${state.refreshError}`} />
  }
  return null
}
