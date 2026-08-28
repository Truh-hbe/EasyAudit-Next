import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { SessionProvider } from './app/auth/session'
import { App } from './App'

describe('App session bootstrap', () => {
  it('renders resolving first instead of assuming anonymous', () => {
    const html = renderToStaticMarkup(
      <SessionProvider>
        <App />
      </SessionProvider>,
    )

    expect(html).toContain('正在确认服务器会话')
    expect(html).not.toContain('当前没有有效会话')
  })
})
