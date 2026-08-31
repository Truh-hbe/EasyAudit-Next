import { Component, type ErrorInfo, type ReactNode } from 'react'

interface BoundaryProps {
  children: ReactNode
  scope: 'root' | 'route'
  resetKey?: string
}

interface BoundaryState {
  failed: boolean
}

export class ErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false }

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // Production telemetry is intentionally handled by the bounded request/runtime
    // logging contract. Never serialize an arbitrary Error.message or stack here.
  }

  componentDidUpdate(previous: BoundaryProps): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false })
    }
  }

  private retry = (): void => {
    this.setState({ failed: false })
  }

  private reload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    if (!this.state.failed) {
      return this.props.children
    }

    if (this.props.scope === 'root') {
      return (
        <main className="foundation" aria-labelledby="root-error-title">
          <p className="eyebrow">EasyAudit Next</p>
          <h1 id="root-error-title">页面暂时不可用</h1>
          <p>应用遇到意外问题。错误详情未显示，以避免暴露敏感信息。</p>
          <button type="button" onClick={this.reload}>重新加载</button>
        </main>
      )
    }

    return (
      <section className="surface-page" aria-labelledby="route-error-title">
        <p className="eyebrow">EasyAudit Next</p>
        <h1 id="route-error-title">当前页面暂时不可用</h1>
        <p>此页面遇到意外问题，其他导航仍可继续使用。</p>
        <button type="button" onClick={this.retry}>重试当前页面</button>
      </section>
    )
  }
}

export function RootErrorBoundary({ children }: { children: ReactNode }) {
  return <ErrorBoundary scope="root">{children}</ErrorBoundary>
}

export function RouteErrorBoundary({
  children,
  resetKey,
}: {
  children: ReactNode
  resetKey: string
}) {
  return <ErrorBoundary scope="route" resetKey={resetKey}>{children}</ErrorBoundary>
}
