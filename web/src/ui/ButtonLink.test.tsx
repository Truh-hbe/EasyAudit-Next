import type { ButtonProps } from 'antd'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { ButtonLink } from './ButtonLink'

// 单元测试环境没有 DOM：用替身 Button 捕获 ButtonLink 传下去的 props，直接驱动点击处理器。
const captured = vi.hoisted(() => ({ props: null as Record<string, unknown> | null }))

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>()
  return {
    ...actual,
    Button: (props: ButtonProps & { target?: string }) => {
      captured.props = props as Record<string, unknown>
      return createElement(actual.Button, props)
    },
  }
})

type ClickEvent = {
  button: number
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  altKey: boolean
  defaultPrevented: boolean
  preventDefault: () => void
  currentTarget: { target: string }
}

function render(props: Partial<React.ComponentProps<typeof ButtonLink>> = {}) {
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <ButtonLink to="/review-plans/new" {...props}>新建审查计划</ButtonLink>
    </MemoryRouter>,
  )
  return { html, onClick: captured.props?.onClick as (event: ClickEvent) => void }
}

function click(onClick: (event: ClickEvent) => void, overrides: Partial<ClickEvent> = {}) {
  const preventDefault = vi.fn()
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  onClick({
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    defaultPrevented: false,
    currentTarget: { target: '' },
    preventDefault,
    ...overrides,
  })
  warn.mockRestore()
  return preventDefault
}

describe('ButtonLink', () => {
  it('渲染为带 href 的链接而不是 button', () => {
    const { html } = render({ type: 'primary' })
    expect(html).toMatch(/^<a /)
    expect(html).toContain('href="/review-plans/new"')
    expect(html).toContain('ant-btn-primary')
    expect(html).not.toContain('<button')
  })

  it('无 target 时普通左键点击做站内导航（拦截默认行为）', () => {
    const { onClick } = render()
    expect(click(onClick)).toHaveBeenCalledTimes(1)
  })

  it('带修饰键或非左键点击不拦截，交给浏览器处理', () => {
    const { onClick } = render()
    for (const overrides of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { button: 1 }]) {
      expect(click(onClick, overrides)).not.toHaveBeenCalled()
    }
  })

  it('target="_blank" 时渲染 target 且普通点击不拦截', () => {
    const { html, onClick } = render({ target: '_blank' })
    expect(html).toContain('target="_blank"')
    expect(click(onClick)).not.toHaveBeenCalled()
  })
})
