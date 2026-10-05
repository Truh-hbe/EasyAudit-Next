import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import { resetAdminUserCredential, updateAdminDepartment } from '../../api/admin'
import { AdminPage, adminErrorMessage, scenarioVersionLabel } from './AdminPage'

function setupDomMock() {
  let doc: any
  class Element {
    tagName: string
    nodeType = 1
    children: any[] = []
    childNodes: any[] = []
    style = {}
    ownerDocument: any
    _value = ''
    checked = false

    constructor(tag: string) {
      this.tagName = (tag || 'DIV').toUpperCase()
      this.ownerDocument = doc
    }
    get value() { return this._value }
    set value(v: any) { this._value = String(v) }
    get options() {
      return this.children.filter((c: any) => c.tagName === 'OPTION')
    }
    _textContent = ''
    get textContent() {
      if (this._textContent) return this._textContent
      return this.children.map((c: any) => c.textContent || '').join('')
    }
    set textContent(v: any) {
      this._textContent = String(v)
      this.children = []
    }
    setAttribute(k: string, v: any) { (this as any)[k] = v }
    removeAttribute(k: string) { delete (this as any)[k] }
    appendChild(c: any) { this.children.push(c); this.childNodes.push(c); c.parentNode = this; return c }
    removeChild(c: any) {
      const i = this.children.indexOf(c)
      if (i !== -1) { this.children.splice(i, 1); this.childNodes.splice(i, 1) }
      return c
    }
    insertBefore(c: any) { this.children.push(c); this.childNodes.push(c); return c }
    addEventListener() {}
    removeEventListener() {}
    contains(node: any) {
      if (node === this) return true
      for (const child of this.children) {
        if (child.contains && child.contains(node)) return true
      }
      return false
    }
  }
  class HTMLIFrameElement extends Element {}
  doc = {
    createElement: (tag: string) => new Element(tag),
    createComment: () => ({ nodeType: 8, ownerDocument: doc }),
    createTextNode: (text: string) => ({ nodeType: 3, nodeValue: text, textContent: text, ownerDocument: doc }),
    createDocumentFragment: () => ({ nodeType: 11, children: [], appendChild: () => {}, ownerDocument: doc }),
    addEventListener: () => {},
    removeEventListener: () => {},
    nodeType: 9,
  }
  doc.body = new Element('BODY')
  doc.defaultView = globalThis
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  ;(globalThis as any).Element = Element
  ;(globalThis as any).HTMLElement = Element
  ;(globalThis as any).HTMLIFrameElement = HTMLIFrameElement
  ;(globalThis as any).document = doc
  ;(globalThis as any).window = globalThis

  return { doc }
}

function getReactProps(node: any): any {
  const key = Object.keys(node).find((k) => k.startsWith('__reactProps'))
  return key ? node[key] : null
}

function findNodesByTag(node: any, tag: string): any[] {
  const results: any[] = []
  if (node.tagName === tag) results.push(node)
  for (const child of node.children || []) {
    results.push(...findNodesByTag(child, tag))
  }
  return results
}

function findStatusText(node: any): string | null {
  if (node.getAttribute?.('role') === 'status' || node.role === 'status') {
    return node.textContent
  }
  for (const child of node.children || []) {
    const found = findStatusText(child)
    if (found !== null) return found
  }
  return null
}

function findAlertText(node: any): string | null {
  if (node.getAttribute?.('role') === 'alert' || node.role === 'alert') return node.textContent
  for (const child of node.children || []) {
    const found = findAlertText(child)
    if (found !== null) return found
  }
  return null
}

describe('M5.4 administrator contracts', () => {
  it('uses exact resource IDs and explicit null clears', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'department-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await updateAdminDepartment('department/1', {
      name: 'Updated department',
      parent_id: null,
      is_active: true,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/departments/department%2F1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          name: 'Updated department',
          parent_id: null,
          is_active: true,
        }),
      }),
    )
    vi.unstubAllGlobals()
  })

  it('keeps the temporary password only in the reset POST body', async () => {
    const temporaryPassword = 'secret-temporary-password-000'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'user-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await resetAdminUserCredential('user/1', { temporary_password: temporaryPassword })

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/v1/admin/users/user%2F1/credential-reset')
    expect(path).not.toContain(temporaryPassword)
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ temporary_password: temporaryPassword }))
    vi.unstubAllGlobals()
  })

  it('renders status-derived safe reset errors and exact scenario labels', () => {
    const secret = 'secret-that-must-not-be-rendered'
    expect(adminErrorMessage(new ApiError(422, secret), 'fallback')).toBe(
      '提交内容不符合当前规则，请检查后重试。',
    )
    expect(adminErrorMessage(new ApiError(403, secret), 'fallback')).toBe(
      '当前账号没有管理员权限。',
    )
    expect(scenarioVersionLabel('process_review', 1)).toBe('process_review@1')
  })
})


const RESET_SUCCESS = '临时凭据已重置；目标用户下次登录必须修改密码。'
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

type RefreshMode = 'ok' | { status: number }

// 第一轮 GET 立即返回；第二轮（写操作后的刷新）按 refresh 模式返回，并先等待 gate 放行。
function createAdminHarness(options: { refresh?: RefreshMode } = {}) {
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let organizationGets = 0
  const refresh = options.refresh ?? 'ok'
  const user = (name: string) => ({
    id: 'user-1', display_name: name, platform_role: 'ordinary_user', is_active: true, primary_department_id: null,
  })

  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method === 'POST' && url.includes('/credential-reset')) return jsonResponse({ id: 'user-1' })
    if (method === 'POST' && url.includes('/api/v1/admin/departments')) {
      return jsonResponse({ id: 'dept-1', name: 'New Dept', parent_id: null, is_active: true }, 201)
    }
    if (method !== 'GET') return new Response('Not Found', { status: 404 })

    const isRefresh = url.includes('/api/v1/admin/organization') ? ++organizationGets > 1 : organizationGets > 1
    if (isRefresh) {
      await gate
      if (refresh !== 'ok') return jsonResponse({ detail: 'refresh failed' }, refresh.status)
    }
    const org = isRefresh ? 'Refreshed User' : 'Test Org'
    if (url.includes('/api/v1/admin/organization')) return jsonResponse({ id: 'org-1', name: org, is_active: true })
    if (url.includes('/api/v1/admin/departments')) return jsonResponse([])
    if (url.includes('/api/v1/admin/users')) return jsonResponse([user(isRefresh ? 'Refreshed User' : 'User 1')])
    if (url.includes('/api/v1/admin/scenario-status')) return jsonResponse({ items: [] })
    return new Response('Not Found', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)

  return {
    fetchMock,
    release,
    organizationGets: () => organizationGets,
  }
}

async function waitInAct(assertion: () => void) {
  await act(async () => {
    await vi.waitFor(assertion)
  })
}

async function mountAdmin() {
  const { doc } = setupDomMock()
  const rootEl = doc.createElement('div')
  const root = createRoot(rootEl)
  await act(async () => {
    root.render(<AdminPage />)
  })
  await waitInAct(() => expect(rootEl.textContent).toContain('Test Org'))
  return { rootEl, forms: findNodesByTag(rootEl, 'FORM') }
}

async function submitCredentialReset(rootEl: any) {
  const resetForm = findNodesByTag(rootEl, 'FORM')[2]
  const select = findNodesByTag(resetForm, 'SELECT')[0]
  const input = findNodesByTag(resetForm, 'INPUT')[0]
  await act(async () => {
    getReactProps(select).onChange({ target: { value: 'user-1' } })
  })
  await act(async () => {
    getReactProps(input).onChange({ target: { value: 'temporary-password-123' } })
  })
  await act(async () => {
    await getReactProps(resetForm).onSubmit({ preventDefault: () => {} })
  })
  return { input }
}

async function submitDepartmentCreate(rootEl: any) {
  const deptForm = findNodesByTag(rootEl, 'FORM')[0]
  const deptInput = findNodesByTag(deptForm, 'INPUT')[0]
  await act(async () => {
    getReactProps(deptInput).onChange({ target: { value: 'New Dept' } })
  })
  await act(async () => {
    await getReactProps(deptForm).onSubmit({ preventDefault: () => {} })
  })
}

async function releaseRefresh(harness: ReturnType<typeof createAdminHarness>) {
  await act(async () => {
    harness.release()
  })
}

describe('admin action feedback across background refresh', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps credential reset feedback while refresh is pending and alongside refreshed data', async () => {
    const harness = createAdminHarness()
    const { rootEl } = await mountAdmin()
    expect(harness.organizationGets()).toBe(1)

    const { input } = await submitCredentialReset(rootEl)

    // 刷新请求已发出但被拦住：提示已在，旧数据仍在
    await waitInAct(() => expect(harness.organizationGets()).toBe(2))
    expect(findStatusText(rootEl)).toBe(RESET_SUCCESS)
    expect(rootEl.textContent).not.toContain('Refreshed User')
    expect(input.value).toBe('')

    await releaseRefresh(harness)
    await waitInAct(() => expect(rootEl.textContent).toContain('Refreshed User'))
    expect(rootEl.textContent).toContain('Refreshed User')
    expect(findStatusText(rootEl)).toBe(RESET_SUCCESS)
    expect(harness.organizationGets()).toBe(2)
  })

  it('keeps department creation feedback while refresh is pending and alongside refreshed data', async () => {
    const harness = createAdminHarness()
    const { rootEl } = await mountAdmin()

    await submitDepartmentCreate(rootEl)

    await waitInAct(() => expect(harness.organizationGets()).toBe(2))
    expect(findStatusText(rootEl)).toBe('部门已由服务器创建。')

    await releaseRefresh(harness)
    await waitInAct(() => expect(rootEl.textContent).toContain('Refreshed User'))
    expect(findStatusText(rootEl)).toBe('部门已由服务器创建。')
  })

  it('clears or replaces feedback when a new operation or edit begins', async () => {
    const harness = createAdminHarness()
    const { rootEl } = await mountAdmin()

    await submitCredentialReset(rootEl)
    await releaseRefresh(harness)
    await waitInAct(() => expect(rootEl.textContent).toContain('Refreshed User'))
    expect(findStatusText(rootEl)).toBe(RESET_SUCCESS)

    // Submitting department form with empty name replaces feedback with new validation error
    const departmentForm = findNodesByTag(rootEl, 'FORM')[0]
    await act(async () => {
      await getReactProps(departmentForm).onSubmit({ preventDefault: () => {} })
    })
    expect(findStatusText(rootEl)).toBe('请输入部门名称。')

    // Clicking edit on a user clears the feedback
    const editUserButton = findNodesByTag(rootEl, 'BUTTON').find((b: any) => b.textContent === '编辑')
    expect(editUserButton).toBeDefined()
    await act(async () => {
      getReactProps(editUserButton).onClick()
    })
    expect(findStatusText(rootEl)).toBeNull()
  })

  it('drops the success message when the refresh fails with 500', async () => {
    const status = 500
    const harness = createAdminHarness({ refresh: { status } })
    const { rootEl } = await mountAdmin()

    await submitCredentialReset(rootEl)
    await waitInAct(() => expect(harness.organizationGets()).toBe(2))
    expect(findStatusText(rootEl)).toBe(RESET_SUCCESS)

    await releaseRefresh(harness)
    await waitInAct(() => expect(rootEl.textContent).not.toContain('Test Org'))
    expect(findStatusText(rootEl)).toBeNull()
    expect(rootEl.textContent).not.toContain(RESET_SUCCESS)
    const alert = findAlertText(rootEl)
    expect(alert).not.toBeNull()
    expect(alert).toContain(adminErrorMessage(new ApiError(status, 'x'), '管理员数据读取失败。'))
  })

  it.each([401, 403])('removes protected content immediately when the refresh returns %s', async (status) => {
    const harness = createAdminHarness({ refresh: { status } })
    const { rootEl } = await mountAdmin()

    await submitCredentialReset(rootEl)
    await waitInAct(() => expect(harness.organizationGets()).toBe(2))
    expect(rootEl.textContent).toContain('Test Org')

    await releaseRefresh(harness)
    await waitInAct(() => expect(rootEl.textContent).not.toContain('Test Org'))
    expect(rootEl.textContent).not.toContain('User 1')
    expect(rootEl.textContent).not.toContain(RESET_SUCCESS)
    expect(findStatusText(rootEl)).toBeNull()
    expect(findAlertText(rootEl)).toContain(adminErrorMessage(new ApiError(status, 'x'), '管理员数据读取失败。'))
  })
})
