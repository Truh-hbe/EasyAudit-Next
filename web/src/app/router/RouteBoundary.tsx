import { Alert, Button } from 'antd'
import { Component, Suspense } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { useLocation } from 'react-router'

import { InitialLoading } from '../../ui/InitialLoading'

// 浏览器对动态 import 失败的报错文案各不相同（Chromium / Firefox / Safari）。
const chunkLoadFailure =
  /dynamically imported module|Importing a module script failed|Loading chunk|Unable to preload CSS/i

export function isChunkLoadError(error: unknown): boolean {
  return error instanceof Error && chunkLoadFailure.test(error.message)
}

type BoundaryState = { error: Error | null }

// 只接管 chunk 加载失败；其他渲染错误原样向上抛，保持原有行为。
// 不自动重试：React.lazy 会缓存被拒绝的 Promise，只有整页重载才会重新请求 chunk。
class ChunkErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('route chunk load failed', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (error === null) {
      return this.props.children
    }
    if (!isChunkLoadError(error)) {
      throw error
    }
    return (
      <Alert
        type="error"
        showIcon
        role="alert"
        message="页面加载失败"
        description="页面资源未能加载，可能是网络中断，或系统刚刚更新。请重新加载页面后再试。"
        action={
          <Button type="primary" onClick={() => window.location.reload()}>
            重新加载页面
          </Button>
        }
      />
    )
  }
}

export function RouteBoundary({ children }: { children: ReactNode }) {
  // 以路径为 key：导航到其他路径（含后退）时丢弃错误状态，不会卡在失败提示上。
  // 回到失败的路由时 React.lazy 仍缓存着被拒绝的 Promise，会立即再次显示失败提示，不会重新请求 chunk。
  const { pathname } = useLocation()
  return (
    <ChunkErrorBoundary key={pathname}>
      <Suspense
        fallback={
          <div aria-busy="true">
            <InitialLoading label="正在加载页面" rows={6} />
          </div>
        }
      >
        {children}
      </Suspense>
    </ChunkErrorBoundary>
  )
}
