import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'

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

  it('retains credential reset success feedback across background data refresh', async () => {
    const { doc } = setupDomMock()

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/admin/organization')) {
        return new Response(JSON.stringify({ id: 'org-1', name: 'Test Org', is_active: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/departments')) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/users') && url.includes('/credential-reset')) {
        return new Response(JSON.stringify({ id: 'user-1' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/users')) {
        return new Response(
          JSON.stringify([
            {
              id: 'user-1',
              display_name: 'User 1',
              platform_role: 'ordinary_user',
              is_active: true,
              primary_department_id: null,
            },
          ]),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        )
      }
      if (url.includes('/api/v1/admin/scenario-status')) {
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('Not Found', { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rootEl = doc.createElement('div')
    const root = createRoot(rootEl)

    await act(async () => {
      root.render(<AdminPage />)
    })

    // Wait for initial load
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20))
    })

    const forms = findNodesByTag(rootEl, 'FORM')
    const resetForm = forms[2]
    const selects = findNodesByTag(resetForm, 'SELECT')
    const inputs = findNodesByTag(resetForm, 'INPUT')

    // Select target user and fill temporary password
    await act(async () => {
      getReactProps(selects[0]).onChange({ target: { value: 'user-1' } })
    })
    await act(async () => {
      getReactProps(inputs[0]).onChange({ target: { value: 'temporary-password-123' } })
    })

    // Submit reset
    await act(async () => {
      await getReactProps(resetForm).onSubmit({ preventDefault: () => {} })
    })

    // Wait for reset API and subsequent data refresh to complete
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })

    expect(findStatusText(rootEl)).toBe('临时凭据已重置；目标用户下次登录必须修改密码。')
    expect(inputs[0].value).toBe('')

    vi.unstubAllGlobals()
  })

  it('clears or replaces feedback when a new operation or edit begins', async () => {
    const { doc } = setupDomMock()

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/admin/organization')) {
        return new Response(JSON.stringify({ id: 'org-1', name: 'Test Org', is_active: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/departments')) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/users') && url.includes('/credential-reset')) {
        return new Response(JSON.stringify({ id: 'user-1' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/users')) {
        return new Response(
          JSON.stringify([
            {
              id: 'user-1',
              display_name: 'User 1',
              platform_role: 'ordinary_user',
              is_active: true,
              primary_department_id: null,
            },
          ]),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        )
      }
      if (url.includes('/api/v1/admin/scenario-status')) {
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('Not Found', { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rootEl = doc.createElement('div')
    const root = createRoot(rootEl)

    await act(async () => {
      root.render(<AdminPage />)
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20))
    })

    const forms = findNodesByTag(rootEl, 'FORM')
    const departmentForm = forms[0]
    const resetForm = forms[2]
    const selects = findNodesByTag(resetForm, 'SELECT')
    const inputs = findNodesByTag(resetForm, 'INPUT')

    // Reset credential successfully
    await act(async () => {
      getReactProps(selects[0]).onChange({ target: { value: 'user-1' } })
    })
    await act(async () => {
      getReactProps(inputs[0]).onChange({ target: { value: 'temporary-password-123' } })
    })
    await act(async () => {
      await getReactProps(resetForm).onSubmit({ preventDefault: () => {} })
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    expect(findStatusText(rootEl)).toBe('临时凭据已重置；目标用户下次登录必须修改密码。')

    // Submitting department form with empty name replaces feedback with new validation error
    await act(async () => {
      await getReactProps(departmentForm).onSubmit({ preventDefault: () => {} })
    })
    expect(findStatusText(rootEl)).toBe('请输入部门名称。')

    // Clicking edit on a user clears the feedback
    const userButtons = findNodesByTag(rootEl, 'BUTTON')
    const editUserButton = userButtons.find((b: any) => b.textContent === '编辑')
    expect(editUserButton).toBeDefined()
    await act(async () => {
      getReactProps(editUserButton).onClick()
    })
    expect(findStatusText(rootEl)).toBeNull()

    vi.unstubAllGlobals()
  })

  it('retains department creation feedback across background data refresh', async () => {
    const { doc } = setupDomMock()

    const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/v1/admin/organization')) {
        return new Response(JSON.stringify({ id: 'org-1', name: 'Test Org', is_active: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/departments') && init?.method === 'POST') {
        return new Response(
          JSON.stringify({ id: 'dept-1', name: 'New Dept', parent_id: null, is_active: true }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/api/v1/admin/departments')) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/users')) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/v1/admin/scenario-status')) {
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('Not Found', { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rootEl = doc.createElement('div')
    const root = createRoot(rootEl)

    await act(async () => {
      root.render(<AdminPage />)
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20))
    })

    const forms = findNodesByTag(rootEl, 'FORM')
    const deptForm = forms[0]
    const deptInput = findNodesByTag(deptForm, 'INPUT')[0]

    await act(async () => {
      getReactProps(deptInput).onChange({ target: { value: 'New Dept' } })
    })

    await act(async () => {
      await getReactProps(deptForm).onSubmit({ preventDefault: () => {} })
    })

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })

    expect(findStatusText(rootEl)).toBe('部门已由服务器创建。')

    vi.unstubAllGlobals()
  })
})
