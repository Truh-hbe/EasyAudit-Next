import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { ButtonLink } from './ButtonLink'
import { PageHeader } from './PageHeader'
import { StatusTag, statusLabel } from './StatusTag'
import type { StatusKind } from './StatusTag'

const expected: Record<StatusKind, Record<string, string>> = {
  reviewCase: {
    draft: '草稿',
    scheduled: '已排期',
    in_progress: '审查中',
    awaiting_closure: '待关闭',
    closed: '已关闭',
    cancelled: '已取消',
  },
  finding: {
    open: '待处理',
    rectifying: '整改中',
    verifying: '待验证',
    closed: '已关闭',
    voided: '已作废',
  },
  actionItem: { todo: '待开始', in_progress: '执行中', done: '已完成', cancelled: '已取消' },
  deadline: { overdue: '已逾期', due_soon: '即将到期' },
  severity: { low: '低', medium: '中', high: '高', critical: '严重' },
}

describe('StatusTag', () => {
  for (const [kind, values] of Object.entries(expected) as [StatusKind, Record<string, string>][]) {
    it(`${kind}: 穷举映射为中文且不泄漏原始值`, () => {
      for (const [value, label] of Object.entries(values)) {
        expect(statusLabel(kind, value)).toBe(label)
        const html = renderToStaticMarkup(<StatusTag kind={kind} value={value} />)
        expect(html).toContain(`>${label}<`)
        expect(html).not.toContain(`>${value}<`)
      }
    })
  }

  it('同一原始值按对象类型取不同文案', () => {
    expect(statusLabel('reviewCase', 'in_progress')).toBe('审查中')
    expect(statusLabel('finding', 'in_progress')).toBeNull()
    expect(statusLabel('actionItem', 'in_progress')).toBe('执行中')
    expect(statusLabel('reviewCase', 'open')).toBeNull()
    expect(statusLabel('finding', 'open')).toBe('待处理')
  })

  it('未知状态显示“未知状态”，原始值放次级信息', () => {
    for (const value of ['archived', '', 'constructor', '__proto__', 'toString']) {
      const html = renderToStaticMarkup(<StatusTag kind="finding" value={value} />)
      expect(html).toContain('未知状态')
      expect(html).toContain(`<span class="status-tag-raw">${value}</span>`)
    }
  })
})

describe('ButtonLink', () => {
  it('渲染为带 href 的链接而不是 button', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ButtonLink to="/review-plans/new" type="primary">新建审查计划</ButtonLink>
      </MemoryRouter>,
    )
    expect(html).toMatch(/^<a /)
    expect(html).toContain('href="/review-plans/new"')
    expect(html).toContain('ant-btn-primary')
    expect(html).toContain('新建审查计划')
    expect(html).not.toContain('<button')
  })
})

describe('PageHeader', () => {
  it('h1 标题、副信息和右侧操作各自呈现', () => {
    const html = renderToStaticMarkup(
      <PageHeader title="审查活动" titleId="t" meta={<span>副信息</span>} extra={<span>操作</span>} />,
    )
    expect(html).toContain('<header')
    expect(html).toContain('<h1 id="t">审查活动</h1>')
    expect(html.indexOf('副信息')).toBeLessThan(html.indexOf('操作'))
  })

  it('没有副信息和操作时不渲染空容器', () => {
    const html = renderToStaticMarkup(<PageHeader title="审查活动" />)
    expect(html).not.toContain('副信息')
    expect(html.match(/<div/g)?.length).toBe(1)
  })
})
