import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { SessionProvider } from './app/auth/session'
import { App } from './App'

describe('App session bootstrap', () => {
  it('renders resolving first instead of assuming anonymous', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/review-cases']}>
        <SessionProvider>
          <App />
        </SessionProvider>
      </MemoryRouter>,
    )

    expect(html).toContain('正在确认服务器会话')
    expect(html).not.toContain('登录名')
  })
})
