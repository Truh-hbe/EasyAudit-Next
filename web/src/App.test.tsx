import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { App } from './App'

describe('App foundation', () => {
  it('renders the M3.5.1 frontend foundation without business content', () => {
    const html = renderToStaticMarkup(<App />)

    expect(html).toContain('EasyAudit Next Product Surface')
    expect(html).toContain('Frontend engineering foundation is active')
  })
})
