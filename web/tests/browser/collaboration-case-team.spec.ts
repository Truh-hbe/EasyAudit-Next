import { expect, test, type Page, type Request, type Response, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Signed In User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

function reviewCase(id: string) {
  return {
    id,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'process_review',
    scenario_version: 1,
    title: `Team Case ${id}`,
    lifecycle: 'in_progress',
    planned_start_at: '2026-08-20T00:00:00Z',
    planned_end_at: '2026-08-30T00:00:00Z',
    started_at: '2026-08-21T00:00:00Z',
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data: { area_code: 'A-01', review_type: 'routine' },
    created_by: user.id,
    created_at: '2026-08-18T00:00:00Z',
  }
}

function member(caseId: string, userId: string, roleKey: string, displayName: string) {
  return { case_id: caseId, user_id: userId, role_key: roleKey, joined_at: '2026-08-18T00:00:00Z', display_name: displayName }
}

interface CaseMock {
  members: ReturnType<typeof member>[]
  memberReads: number
  adds: unknown[]
  removes: string[]
  candidateQueries: string[]
  removeStatus: number | 'abort'
  removeDetail: string
  addGate: Promise<void> | null
  postCount: number
  addStatus: number | 'abort'
}

// 为一个审查活动挂上主授权、从属读取和团队写入的 mock；所有状态由测试直接修改。
async function mockCase(page: Page, caseId: string): Promise<CaseMock> {
  const state: CaseMock = {
    members: [member(caseId, user.id, 'lead', 'Team Lead')],
    memberReads: 0,
    adds: [],
    removes: [],
    candidateQueries: [],
    removeStatus: 200,
    removeDetail: '',
    addGate: null,
    postCount: 0,
    addStatus: 201,
  }
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase(caseId)),
  )
  for (const child of ['findings', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  await page.route((url) => url.pathname === `/api/v1/management/review-cases/${caseId}/progress`, (route) =>
    fulfillJson(route, 404, { detail: 'Not found' }),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/members`, async (route) => {
    if (route.request().method() === 'POST') {
      state.postCount += 1
      await state.addGate
      if (state.addStatus === 'abort') return route.abort('failed')
      if (state.addStatus !== 201) return fulfillJson(route, state.addStatus, { detail: 'add rejected' })
      const body = route.request().postDataJSON() as { user_id: string; role_key: string }
      state.adds.push(body)
      state.members.push(member(caseId, body.user_id, body.role_key, 'Added Candidate'))
      return fulfillJson(route, 201, { case_id: caseId, user_id: body.user_id, role_key: body.role_key, joined_at: '2026-08-30T00:00:00Z' })
    }
    state.memberReads += 1
    return fulfillJson(route, 200, state.members)
  })
  await page.route((url) => url.pathname.startsWith(`/api/v1/review-cases/${caseId}/members/`), (route) => {
    state.removes.push(new URL(route.request().url()).pathname.split('/').pop() ?? '')
    if (state.removeStatus === 'abort') return route.abort('failed')
    if (state.removeStatus !== 200) return fulfillJson(route, state.removeStatus, { detail: state.removeDetail })
    state.members = state.members.filter((candidate) => !state.removes.includes(candidate.user_id))
    return fulfillJson(route, 200, { case_id: caseId, user_id: state.removes.at(-1), role_key: 'auditor', joined_at: '2026-08-18T00:00:00Z' })
  })
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/member-candidates`, (route) => {
    const params = new URL(route.request().url()).searchParams
    state.candidateQueries.push(`${params.get('role_key')}:${params.get('q')}`)
    return fulfillJson(route, 200, [
      { user_id: 'candidate-1', display_name: 'Candidate One' },
      { user_id: 'candidate-2', display_name: 'Candidate Two' },
    ])
  })
  return state
}

test.beforeEach(async ({ page }) => {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
})

test('团队面板：用 Drawer 按角色搜索候选人并添加，成功后刷新成员', async ({ page }) => {
  const state = await mockCase(page, 'case-team')
  await page.goto('/review-cases/case-team')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('Team Lead')).toBeVisible()
  await expect(team.getByText('审查组长', { exact: true })).toBeVisible()

  await team.getByRole('button', { name: '添加成员' }).click()
  const drawer = page.getByRole('dialog', { name: '添加成员' })
  await drawer.getByLabel('团队角色').click()
  await page.getByTitle('复核员').click()
  const memberSelect = drawer.getByLabel('成员')
  await memberSelect.fill('Cand')
  await expect.poll(() => state.candidateQueries).toContain('reviewer:Cand')
  await page.getByTitle('Candidate One').click()

  await drawer.getByRole('button', { name: '添加成员' }).click()
  await expect(page.getByRole('dialog', { name: '添加成员' })).toHaveCount(0)
  expect(state.adds).toEqual([{ user_id: 'candidate-1', role_key: 'reviewer' }])
  // 成功提示只有一个出口。
  await expect(page.getByText('已添加成员', { exact: true })).toHaveCount(1)
  await expect(team.getByText('Added Candidate')).toBeVisible()
  await expect(team.getByText('复核员', { exact: true })).toBeVisible()
})

test('团队面板：候选搜索 403 只显示权限提示，不留候选人名称', async ({ page }) => {
  await mockCase(page, 'case-forbidden')
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-forbidden/member-candidates', (route) =>
    fulfillJson(route, 403, { detail: 'forbidden' }),
  )
  await page.goto('/review-cases/case-forbidden')
  await page.getByRole('button', { name: '添加成员' }).click()
  const drawer = page.getByRole('dialog', { name: '添加成员' })
  await expect(drawer.getByRole('alert')).toContainText('当前用户没有管理审查团队的权限。')
  await drawer.getByLabel('成员').click()
  await expect(page.getByText('Candidate One')).toHaveCount(0)
})

test('团队面板：移除需要二次确认，取消不发请求', async ({ page }) => {
  const state = await mockCase(page, 'case-remove')
  state.members.push(member('case-remove', 'member-2', 'auditor', 'Removable Auditor'))
  await page.goto('/review-cases/case-remove')
  const team = page.getByRole('region', { name: '团队管理' })
  const row = team.getByRole('listitem').filter({ hasText: 'Removable Auditor' })

  await row.getByRole('button', { name: /移除/ }).click()
  const confirm = page.getByRole('dialog', { name: '移除成员' })
  await expect(confirm).toContainText('Removable Auditor')
  await confirm.getByRole('button', { name: /取\s*消/ }).click()
  await expect(confirm).toHaveCount(0)
  expect(state.removes).toEqual([])

  await row.getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect(team.getByText('Removable Auditor')).toHaveCount(0)
  expect(state.removes).toEqual(['member-2'])
})

test('团队面板：移除最后一名管理者的 409 显示业务原因并保持成员不变', async ({ page }) => {
  const state = await mockCase(page, 'case-last')
  state.removeStatus = 409
  state.removeDetail = 'Cannot remove the final effective Case manager'
  await page.goto('/review-cases/case-last')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('Team Lead')).toBeVisible()
  const readsBefore = state.memberReads

  await team.getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect(team.getByText('审查活动至少需要保留一名有效的审查组长，无法移除最后一名管理者。')).toBeVisible()
  await expect(team.getByText('Team Lead')).toBeVisible()
  expect(state.memberReads).toBe(readsBefore)
})

test('团队面板：移除的并发 409 提示数据已变化并重新读取，不自动重放', async ({ page }) => {
  const state = await mockCase(page, 'case-changed')
  state.removeStatus = 409
  state.removeDetail = 'CaseMember changed concurrently'
  await page.goto('/review-cases/case-changed')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('Team Lead')).toBeVisible()
  const readsBefore = state.memberReads

  await team.getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect(team.getByText('数据已变化，正在获取最新状态。')).toBeVisible()
  await expect.poll(() => state.memberReads).toBeGreaterThan(readsBefore)
  expect(state.removes).toHaveLength(1)
})

for (const { status, retryAfter, expected } of [
  { status: 503, retryAfter: '30', expected: '服务繁忙，请30 秒后手动重试。' },
  { status: 429, retryAfter: null, expected: '服务繁忙，请稍后手动重试。' },
]) {
  test(`团队面板：移除遇到 ${status}${retryAfter === null ? '（无 Retry-After）' : '（Retry-After）'}时提示等待并由用户手动重试，不自动重放`, async ({ page }) => {
    const state = await mockCase(page, 'case-busy')
    await page.goto('/review-cases/case-busy')
    const team = page.getByRole('region', { name: '团队管理' })
    await expect(team.getByText('Team Lead')).toBeVisible()
    let deletes = 0
    await page.route((url) => url.pathname.startsWith('/api/v1/review-cases/case-busy/members/'), (route) => {
      deletes += 1
      return route.fulfill({
        status,
        contentType: 'application/json',
        headers: retryAfter === null ? {} : { 'Retry-After': retryAfter },
        body: JSON.stringify({ detail: 'busy' }),
      })
    })
    const readsBefore = state.memberReads

    await team.getByRole('button', { name: /移除/ }).click()
    await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
    await expect(team.getByText(expected)).toBeVisible()
    await expect(team.getByText('Team Lead')).toBeVisible()
    // 等待足够久，确认没有后台自动重放，也没有把它当作冲突去刷新成员。
    await page.waitForTimeout(1000)
    expect(deletes).toBe(1)
    expect(state.memberReads).toBe(readsBefore)

    // 用户手动再点一次才会发第二个请求。
    await team.getByRole('button', { name: /移除/ }).click()
    await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
    await expect.poll(() => deletes).toBe(2)
  })
}

test('团队面板：移除时网络中断是“未确认”，先刷新核对，不当作冲突也不重放', async ({ page }) => {
  const state = await mockCase(page, 'case-unknown')
  state.removeStatus = 'abort'
  await page.goto('/review-cases/case-unknown')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('Team Lead')).toBeVisible()
  const readsBefore = state.memberReads

  await team.getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect(team.getByText(/未确认是否已移除成员/)).toBeVisible()
  await expect.poll(() => state.memberReads).toBeGreaterThan(readsBefore)
  expect(state.removes).toHaveLength(1)
})

test('团队面板：写请求 404 说明权限已丢失，立即移除审查活动内容', async ({ page }) => {
  const state = await mockCase(page, 'case-gone')
  state.removeStatus = 404
  state.removeDetail = 'ReviewCase not found'
  await page.goto('/review-cases/case-gone')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('Team Lead')).toBeVisible()

  // 之后主授权检查也会失败。
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-gone', (route) =>
    fulfillJson(route, 404, { detail: 'ReviewCase not found' }),
  )
  await team.getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Team Case case-gone')).toHaveCount(0)
  await expect(page.getByText('Team Lead')).toHaveCount(0)
})

test('团队面板：切换审查活动后丢弃 Drawer、候选人和晚到的候选响应', async ({ page }) => {
  await mockCase(page, 'case-a')
  await mockCase(page, 'case-b')
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-a/member-candidates', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    return fulfillJson(route, 200, [{ user_id: 'late', display_name: 'Late Candidate From A' }])
  })
  await page.goto('/review-cases/case-a')
  await page.getByRole('button', { name: '添加成员' }).click()
  await expect(page.getByRole('dialog', { name: '添加成员' })).toBeVisible()

  await page.evaluate(`history.pushState({}, '', '/review-cases/case-b'); dispatchEvent(new PopStateEvent('popstate'))`)
  await expect(page.getByRole('heading', { name: 'Team Case case-b' })).toBeVisible()
  await expect(page.getByRole('dialog', { name: '添加成员' })).toHaveCount(0)
  await page.waitForTimeout(900)
  await expect(page.getByText('Late Candidate From A')).toHaveCount(0)
  await expect(page.getByText('Team Case case-a')).toHaveCount(0)
})

for (const width of [375, 320]) {
  test(`审查活动列表和详情在 ${width}px 下没有页面级横向溢出`, async ({ page }) => {
    await mockCase(page, 'case-narrow')
    await page.route((url) => url.pathname === '/api/v1/review-cases', (route) =>
      fulfillJson(route, 200, {
        items: [{ ...reviewCase('case-narrow'), title: 'A very long review case title that must wrap or scroll inside its container' }],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    )
    await page.setViewportSize({ width, height: 800 })
    const overflow = () =>
      page.evaluate(() => {
        const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } })
          .document.documentElement
        return root.scrollWidth - root.clientWidth
      })

    await page.goto('/review-cases')
    await expect(page.getByRole('link', { name: /A very long review case title/ })).toBeVisible()
    expect(await overflow()).toBeLessThanOrEqual(1)

    // 状态单元格必须落在表格滚动容器的当前可视区域内（长标题不能把它挤出首屏）。
    const statusCell = page.getByRole('row', { name: /A very long review case title/ }).getByRole('cell', { name: '审查中' })
    await expect(statusCell).toBeVisible()
    const cell = await statusCell.boundingBox()
    const container = await statusCell.evaluate((element) => {
      const win = globalThis as unknown as {
        getComputedStyle(el: unknown): { overflowX: string }
      }
      let node = (element as unknown as { parentElement: unknown }).parentElement as
        | { parentElement: unknown; getBoundingClientRect(): { left: number; right: number } }
        | null
      while (node !== null && !['auto', 'scroll'].includes(win.getComputedStyle(node).overflowX)) {
        node = node.parentElement as typeof node
      }
      if (node === null) return null
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.right }
    })
    expect(cell).not.toBeNull()
    expect(container).not.toBeNull()
    expect(cell!.x).toBeGreaterThanOrEqual(container!.left - 1)
    expect(cell!.x + cell!.width).toBeLessThanOrEqual(container!.right + 1)

    await page.goto('/review-cases/case-narrow')
    await expect(page.getByRole('heading', { name: 'Team Case case-narrow' })).toBeVisible()
    await expect(page.getByRole('region', { name: '团队管理' }).getByText('Team Lead')).toBeVisible()
    expect(await overflow()).toBeLessThanOrEqual(1)
  })
}

for (const width of [375, 320]) {
  test(`添加成员 Drawer 打开时在 ${width}px 下没有页面级横向溢出`, async ({ page }) => {
    await mockCase(page, 'case-narrow-drawer')
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/review-cases/case-narrow-drawer')
    const team = page.getByRole('region', { name: '团队管理' })
    await expect(team.getByText('Team Lead')).toBeVisible()

    await team.getByRole('button', { name: '添加成员' }).click()
    const drawer = page.getByRole('dialog', { name: '添加成员' })
    await expect(drawer.getByLabel('团队角色')).toBeVisible()
    await drawer.getByLabel('成员').fill('Cand')
    await expect(page.getByTitle('Candidate One')).toBeVisible()
    // 滑入动画期间面板在视口外，scrollWidth 会瞬时变大；轮询到稳定状态再断言。
    await expect
      .poll(() =>
        page.evaluate(() => {
          const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } })
            .document.documentElement
          return root.scrollWidth - root.clientWidth
        }),
      )
      .toBeLessThanOrEqual(1)
    // Drawer 本身也不应超出视口。
    // 面板有滑入动画，轮询到动画结束后再断言位置。
    await expect
      .poll(async () => {
        const box = await drawer.boundingBox()
        return box !== null && box.x >= -1 && box.x + box.width <= width + 1
      })
      .toBe(true)
  })
}

// 把 initialDone 之后的所有候选人搜索挂在 gate 上，并记录每个请求最终是被放行送达，还是被客户端取消。
// 取消是预期结果（修复后的行为）；fulfill 因其他原因失败则记入 unexpectedErrors，由测试断言为空。
function holdCandidateSearches(page: Page, caseId: string, gate: { promise: Promise<void> }) {
  const tracker = {
    active: false,
    held: 0,
    delivered: [] as Response[],
    aborted: new Set<Request>(),
    unexpectedErrors: [] as unknown[],
    heldRequests: [] as Request[],
  }
  page.on('requestfailed', (request) => tracker.aborted.add(request))
  page.on('response', (response) => {
    if (tracker.heldRequests.includes(response.request())) tracker.delivered.push(response)
  })
  void page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/member-candidates`, async (route) => {
    if (!tracker.active) return route.fallback()
    const request = route.request()
    tracker.held += 1
    tracker.heldRequests.push(request)
    await gate.promise
    try {
      await fulfillJson(route, 200, [{ user_id: 'candidate-ghost', display_name: 'Ghost Candidate' }])
    } catch (error) {
      // 请求已被客户端取消时 fulfill 失败是预期的；requestfailed 事件可能稍晚到达，先让出一轮。
      await new Promise((resolve) => setTimeout(resolve, 50))
      if (!tracker.aborted.has(request)) tracker.unexpectedErrors.push(error)
    }
  })
  return {
    tracker,
    // 放行之后，等每个被挂住的请求要么完整送达页面、要么确认被取消，再等页面处理完响应。
    async settle() {
      await expect
        .poll(() => tracker.delivered.length + [...tracker.aborted].filter((r) => tracker.heldRequests.includes(r)).length)
        .toBe(tracker.held)
      for (const response of tracker.delivered) await response.finished()
      await page.evaluate(
        () =>
          new Promise<void>((resolve) => {
            const win = globalThis as unknown as { requestAnimationFrame(cb: () => void): void }
            win.requestAnimationFrame(() => win.requestAnimationFrame(() => resolve()))
          }),
      )
      expect(tracker.unexpectedErrors).toEqual([])
    },
  }
}

test('添加成员：POST 403 之后，旧的候选人搜索 200 晚到也不会把姓名写回来', async ({ page }) => {
  const state = await mockCase(page, 'case-late-search')
  const addGate = deferred()
  const searchGate = deferred()
  const held = holdCandidateSearches(page, 'case-late-search', searchGate)
  state.addStatus = 403
  await page.goto('/review-cases/case-late-search')
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('button', { name: '添加成员' }).click()
  const drawer = page.getByRole('dialog', { name: '添加成员' })
  await pickCandidate(page, drawer, 'Cand', 'Candidate One')
  held.tracker.active = true
  state.addGate = addGate.promise

  // 再发起一次搜索并让它停在途中（此后所有候选人请求都被挂住），然后提交添加。
  await drawer.getByLabel('成员').fill('Late')
  await expect.poll(() => held.tracker.held).toBeGreaterThan(0)
  // 下拉框展开时按钮被遮挡，直接派发点击，不通过失焦收起下拉框。
  await drawer.getByRole('button', { name: '添加成员' }).dispatchEvent('click')
  await expect.poll(() => state.postCount).toBe(1)
  // 等过防抖时间，让提交时失焦可能触发的搜索也发出（修复后它们已被取消）。
  await page.waitForTimeout(600)

  // POST 先失败：候选人和已选成员被清空，403 提示出现；然后旧搜索才返回 200。
  addGate.resolve()
  await expect(drawer.getByText('当前用户没有管理审查团队的权限。')).toBeVisible()
  await expect(drawer.getByText('Candidate One')).toHaveCount(0)
  searchGate.resolve()
  await held.settle()

  await drawer.getByLabel('成员').click()
  await expect(page.getByTitle('Ghost Candidate')).toHaveCount(0)
  await expect(drawer.getByText('Candidate One')).toHaveCount(0)
  await expect(drawer.getByText('当前用户没有管理审查团队的权限。')).toBeVisible()
})

test('添加成员：POST 在途时关闭重开，POST 403 后新会话里晚到的候选人搜索也不会写回姓名', async ({ page }) => {
  const state = await mockCase(page, 'case-reopen-403')
  const addGate = deferred()
  const searchGate = deferred()
  const held = holdCandidateSearches(page, 'case-reopen-403', searchGate)
  state.addStatus = 403
  await page.goto('/review-cases/case-reopen-403')
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('button', { name: '添加成员' }).click()
  let drawer = page.getByRole('dialog', { name: '添加成员' })
  await pickCandidate(page, drawer, 'Cand', 'Candidate One')
  state.addGate = addGate.promise
  await drawer.getByRole('button', { name: '添加成员' }).click()
  await expect.poll(() => state.postCount).toBe(1)

  // POST 仍在途：关闭再重开，新会话发起的候选搜索停在途中。
  held.tracker.active = true
  await drawer.getByRole('button', { name: /Close|关闭/ }).first().click()
  await expect(page.getByRole('dialog', { name: '添加成员' })).toHaveCount(0)
  await team.getByRole('button', { name: '添加成员' }).click()
  drawer = page.getByRole('dialog', { name: '添加成员' })
  await expect.poll(() => held.tracker.held).toBeGreaterThan(0)

  // 旧 POST 返回 403（发起它的会话已不是当前会话），随后新会话的搜索才返回 200。
  addGate.resolve()
  await expect(team.getByText('当前用户没有管理审查团队的权限。')).toBeVisible()
  searchGate.resolve()
  await held.settle()

  await drawer.getByLabel('成员').click()
  await expect(page.getByTitle('Ghost Candidate')).toHaveCount(0)
  await expect(drawer.getByText('Candidate One')).toHaveCount(0)
})

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

async function pickCandidate(page: Page, drawer: ReturnType<Page['locator']>, query: string, name: string) {
  await drawer.getByLabel('成员').fill(query)
  await page.getByTitle(name, { exact: true }).last().click()
}

test('移除确认框：切换到无权访问的活动后确认框被销毁，且不会向旧活动发 DELETE', async ({ page }) => {
  const a = await mockCase(page, 'case-a')
  a.members.push(member('case-a', 'member-2', 'auditor', 'Removable Auditor'))
  await mockCase(page, 'case-b')
  const gate = deferred()
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-b', async (route) => {
    await gate.promise
    return fulfillJson(route, 404, { detail: 'ReviewCase not found' })
  })
  await page.goto('/review-cases/case-a')
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('listitem').filter({ hasText: 'Removable Auditor' }).getByRole('button', { name: /移除/ }).click()
  await expect(page.getByRole('dialog', { name: '移除成员' })).toBeVisible()

  await page.evaluate(`history.pushState({}, '', '/review-cases/case-b'); dispatchEvent(new PopStateEvent('popstate'))`)
  await expect(page.getByRole('dialog', { name: '移除成员' })).toHaveCount(0)
  gate.resolve()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Removable Auditor')).toHaveCount(0)
  await page.waitForTimeout(300)
  expect(a.removes).toEqual([])
})

test('添加成员：请求未完成时关闭再重开 Drawer，表单完整重置，且不会产生第二个 POST', async ({ page }) => {
  const state = await mockCase(page, 'case-lock')
  const gate = deferred()
  state.addGate = gate.promise
  await page.goto('/review-cases/case-lock')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('Team Lead')).toBeVisible()

  await team.getByRole('button', { name: '添加成员' }).click()
  let drawer = page.getByRole('dialog', { name: '添加成员' })
  await drawer.getByLabel('团队角色').click()
  await page.getByTitle('复核员', { exact: true }).last().click()
  await pickCandidate(page, drawer, 'Cand', 'Candidate One')
  await drawer.getByRole('button', { name: '添加成员' }).click()
  await expect.poll(() => state.postCount).toBe(1)

  await drawer.getByRole('button', { name: /Close|关闭/ }).first().click()
  await expect(page.getByRole('dialog', { name: '添加成员' })).toHaveCount(0)
  await team.getByRole('button', { name: '添加成员' }).click()
  drawer = page.getByRole('dialog', { name: '添加成员' })
  // 重开后角色回到默认值、成员为空；搜索使用的也是这个默认角色。
  await expect(drawer.getByTitle('审查组长')).toBeVisible()
  await expect(drawer.getByTitle('Candidate One')).toHaveCount(0)
  await expect.poll(() => state.candidateQueries.at(-1)).toBe('lead:')

  // 旧写请求仍在途：重开的会话里表单保持禁用，无法再提交同一个成员。
  await expect(drawer.getByLabel('成员')).toBeDisabled()
  await expect(drawer.getByRole('button', { name: '添加成员' })).toBeDisabled()
  await page.waitForTimeout(300)
  expect(state.postCount).toBe(1)

  gate.resolve()
  await expect(team.getByText('Added Candidate')).toBeVisible()
  expect(state.postCount).toBe(1)
  // 旧请求的结果不应关闭新开的会话。
  await expect(page.getByRole('dialog', { name: '添加成员' })).toBeVisible()
})

test('添加成员：候选搜索返回 403 后，已选候选人姓名也被清空', async ({ page }) => {
  await mockCase(page, 'case-clear')
  await page.goto('/review-cases/case-clear')
  await page.getByRole('button', { name: '添加成员' }).click()
  const drawer = page.getByRole('dialog', { name: '添加成员' })
  await pickCandidate(page, drawer, '', 'Candidate One')
  await expect(drawer.getByTitle('Candidate One')).toBeVisible()

  await page.route((url) => url.pathname === '/api/v1/review-cases/case-clear/member-candidates', (route) =>
    fulfillJson(route, 403, { detail: 'forbidden' }),
  )
  await drawer.getByLabel('成员').fill('x')
  await expect(drawer.getByRole('alert')).toContainText('当前用户没有管理审查团队的权限。')
  await expect(page.getByText('Candidate One')).toHaveCount(0)
  await expect(page.getByText('Candidate Two')).toHaveCount(0)
})

test('移除自己的最后一个角色后重新确认主授权，403 时立即移除全部受保护内容', async ({ page }) => {
  const state = await mockCase(page, 'case-self')
  state.members.push(member('case-self', 'other-lead', 'lead', 'Other Lead'))
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-self/findings', (route) =>
    fulfillJson(route, 200, [{ id: 'f1', organization_id: user.organization_id, case_id: 'case-self', title: 'Visible Finding', description: null, severity: 'high', lifecycle: 'rectifying', scenario_data: {}, raised_by: user.id, raised_at: '2026-08-22T00:00:00Z' }]),
  )
  await page.route((url) => url.pathname === '/api/v1/management/review-cases/case-self/progress', (route) =>
    fulfillJson(route, 200, { as_of: '2026-08-28T10:00:00Z', case: { id: 'case-self', review_plan_id: null, title: 'x', scenario_key: 'process_review', scenario_version: 1, lifecycle: 'in_progress', planned_start_at: null, planned_end_at: null, deadline_bucket: 'none', findings: { total: 1, open: 0, rectifying: 1, verifying: 0, closed: 0, voided: 0 }, actions: { total: 0, todo: 0, in_progress: 0, done: 0, cancelled: 0, overdue: 0, due_soon: 0 } }, findings: [], overdue_actions: [], due_soon_actions: [] }),
  )
  await page.goto('/review-cases/case-self')
  const team = page.getByRole('region', { name: '团队管理' })
  await expect(page.getByText('Visible Finding')).toBeVisible()
  await expect(page.getByText('整改项已逾期')).toBeVisible()

  // 删除成功之后，服务端不再允许当前用户访问这个活动。
  for (const suffix of ['', '/members', '/findings', '/activities']) {
    await page.route((url) => url.pathname === `/api/v1/review-cases/case-self${suffix}`, (route) =>
      route.request().method() === 'DELETE' ? route.fallback() : fulfillJson(route, 403, { detail: 'forbidden' }),
    )
  }
  await page.route((url) => url.pathname === '/api/v1/management/review-cases/case-self/progress', (route) =>
    fulfillJson(route, 403, { detail: 'forbidden' }),
  )
  await team.getByRole('listitem').filter({ hasText: 'Team Lead' }).getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()

  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Team Case case-self')).toHaveCount(0)
  await expect(page.getByText('Visible Finding')).toHaveCount(0)
  await expect(page.getByText('整改项已逾期')).toHaveCount(0)
  await expect(page.getByText('Other Lead')).toHaveCount(0)
})

// 用可编程的主读取/成员读取结果覆盖 mockCase 的默认路由（后注册的路由优先）。
// 开发模式下 StrictMode 会让首次加载重复读取，所以策略只在 arm() 之后生效，计数也从 arm() 起算。
async function stubReadPolicy(
  page: Page,
  caseId: string,
  policy: {
    caseRead?: (n: number) => Promise<number> | number
    membersRead?: (n: number) => Promise<number> | number
  },
) {
  let armed = false
  const counters = {
    caseReads: 0,
    membersReads: 0,
    arm() {
      armed = true
      counters.caseReads = 0
      counters.membersReads = 0
    },
  }
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, async (route) => {
    if (armed) counters.caseReads += 1
    const status = !armed || policy.caseRead === undefined ? 200 : await policy.caseRead(counters.caseReads)
    return status === 200 ? fulfillJson(route, 200, reviewCase(caseId)) : fulfillJson(route, status, { detail: 'x' })
  })
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/members`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    if (armed) counters.membersReads += 1
    const status = !armed || policy.membersRead === undefined ? 200 : await policy.membersRead(counters.membersReads)
    return status === 200 ? route.fallback() : fulfillJson(route, status, { detail: 'x' })
  })
  return counters
}

async function removeOtherMember(page: Page) {
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('listitem').filter({ hasText: 'Other Member' }).getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
}

async function caseWithOtherMember(page: Page, caseId: string) {
  const state = await mockCase(page, caseId)
  state.members.push(member(caseId, 'other-member', 'auditor', 'Other Member'))
  return state
}

test('主授权重读：从属资源第一次就被拒绝（观察员看管理进度）不触发额外的主读取', async ({ page }) => {
  await mockCase(page, 'case-edge')
  const managementGate = deferred()
  await page.route((url) => url.pathname === '/api/v1/management/review-cases/case-edge/progress', async (route) => {
    await managementGate.promise
    return fulfillJson(route, 403, { detail: 'forbidden' })
  })
  const counters = await stubReadPolicy(page, 'case-edge', {})
  counters.arm()
  await page.goto('/review-cases/case-edge')
  // 管理进度只在主授权通过后才会请求；它被扣住时，主加载已经完成。
  await expect(page.getByRole('region', { name: '团队管理' }).getByText('Team Lead')).toBeVisible()
  // 开发模式 StrictMode 会让首次加载的请求次数不稳定（取决于 abort 与拦截器的先后），所以只记录基线，不断言精确次数。
  const baseline = counters.caseReads
  expect(baseline).toBeGreaterThanOrEqual(1)

  managementGate.resolve()
  await expect(page.getByText('当前用户没有可用的管理进度摘要。')).toBeVisible()
  // 触发会在同一个响应处理里同步发出请求；给拦截器一个确定的处理窗口后确认没有新增。
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 300)))
  expect(counters.caseReads).toBe(baseline)
})

test('主授权重读：重读在途时又移除了自己，旧重读返回 200 后补读一次，补读 403 即移除内容', async ({ page }) => {
  const state = await caseWithOtherMember(page, 'case-dirty')
  state.members.push(member('case-dirty', 'second-lead', 'lead', 'Second Lead'))
  const caseGate = deferred()
  const counters = await stubReadPolicy(page, 'case-dirty', {
    // 第 1 次重读被扣住并返回 200（发出时当前用户还有角色）；之后的补读返回 403。
    caseRead: async (n) => {
      if (n === 1) {
        await caseGate.promise
        return 200
      }
      return 403
    },
  })
  await page.goto('/review-cases/case-dirty')
  await expect(page.getByText('Other Member')).toBeVisible()
  counters.arm()
  await removeOtherMember(page)
  await expect.poll(() => counters.caseReads).toBe(1)

  // 重读还在途，又移除了自己的最后一个角色：第二次触发只标记 dirty，不另发请求。
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('listitem').filter({ hasText: 'Team Lead' }).getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect.poll(() => state.removes.length).toBe(2)
  await page.waitForTimeout(300)
  expect(counters.caseReads).toBe(1)
  await expect(page.getByText('Team Case case-dirty')).toBeVisible()

  caseGate.resolve()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Team Case case-dirty')).toHaveCount(0)
  expect(counters.caseReads).toBe(2)
})

test('主授权重读：首次加载时成员接口就返回 403，也会重新确认主授权并移除内容', async ({ page }) => {
  await mockCase(page, 'case-first')
  let denied = false
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-first', (route) =>
    denied ? fulfillJson(route, 403, { detail: 'forbidden' }) : route.fallback(),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-first/members', (route) => {
    denied = true
    return fulfillJson(route, 403, { detail: 'forbidden' })
  })
  await page.goto('/review-cases/case-first')
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Team Case case-first')).toHaveCount(0)
})

test('主授权重读：页面内重新加载成功后，旧代次迟到的 403 不会污染新加载', async ({ page }) => {
  const state = await caseWithOtherMember(page, 'case-ctx')
  state.members.push(member('case-ctx', 'third-member', 'observer', 'Third Member'))
  const gate = deferred()
  const counters = await stubReadPolicy(page, 'case-ctx', {
    // 第 1 次（写操作后的静默重读）被扣住并最终返回 403；之后的读取（含重新加载）都返回 200。
    caseRead: async (n) => {
      if (n === 1) {
        await gate.promise
        return 403
      }
      return 200
    },
  })
  await page.goto('/review-cases/case-ctx')
  await expect(page.getByText('Other Member')).toBeVisible()
  counters.arm()
  await removeOtherMember(page)
  await expect.poll(() => counters.caseReads).toBe(1)

  // 重读在途时，另一次写操作返回 404：页面在同一实例内重新加载（新代次），重新加载读取返回 200。
  state.removeStatus = 404
  state.removeDetail = 'ReviewCase not found'
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('listitem').filter({ hasText: 'Third Member' }).getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect.poll(() => counters.caseReads).toBe(2)
  await expect(page.getByRole('heading', { name: 'Team Case case-ctx' })).toBeVisible()

  gate.resolve()
  await page.waitForTimeout(500)
  await expect(page.getByRole('heading', { name: 'Team Case case-ctx' })).toBeVisible()
  await expect(page.getByText('内容不存在或无权访问')).toHaveCount(0)
})

test('主授权重读：重读返回 500 时保留内容（真正走到 500 分支），之后的触发仍可重读，确认 403 才移除', async ({ page }) => {
  const state = await caseWithOtherMember(page, 'case-500')
  state.members.push(member('case-500', 'third', 'observer', 'Third Member'))
  const counters = await stubReadPolicy(page, 'case-500', { caseRead: (n) => (n === 1 ? 500 : 403) })
  await page.goto('/review-cases/case-500')
  await expect(page.getByText('Other Member')).toBeVisible()
  counters.arm()
  await removeOtherMember(page)
  await expect.poll(() => counters.caseReads).toBe(1)
  await expect(page.getByText('Team Case case-500')).toBeVisible()

  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByRole('listitem').filter({ hasText: 'Third Member' }).getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Team Case case-500')).toHaveCount(0)
})

for (const [label, status, expected] of [
  ['成功', 201, null],
  ['明确拒绝（409）', 409, '该成员已在团队中，或团队已发生变化，正在获取最新状态。'],
  ['明确拒绝（422）', 422, 'add rejected'],
  ['结果未知（网络中断）', 'abort', '未确认是否已添加成员'],
  ['结果未知（500）', 500, '未确认是否已添加成员'],
] as const) {
  test(`添加成员：请求在途时关闭 Drawer，${label}仍在面板上有反馈`, async ({ page }) => {
    const state = await mockCase(page, 'case-outcome')
    const gate = deferred()
    state.addGate = gate.promise
    state.addStatus = status
    await page.goto('/review-cases/case-outcome')
    const team = page.getByRole('region', { name: '团队管理' })
    await expect(team.getByText('Team Lead')).toBeVisible()
    await team.getByRole('button', { name: '添加成员' }).click()
    const drawer = page.getByRole('dialog', { name: '添加成员' })
    await pickCandidate(page, drawer, 'Cand', 'Candidate One')
    await drawer.getByRole('button', { name: '添加成员' }).click()
    await expect.poll(() => state.postCount).toBe(1)
    await drawer.getByRole('button', { name: /Close|关闭/ }).first().click()
    await expect(page.getByRole('dialog', { name: '添加成员' })).toHaveCount(0)
    const readsBefore = state.memberReads

    gate.resolve()
    if (expected === null) {
      await expect(page.getByText('已添加成员', { exact: true })).toHaveCount(1)
      await expect(team.getByText('Added Candidate')).toBeVisible()
    } else {
      await expect(team.getByText(expected, { exact: false })).toBeVisible()
      await expect(team.getByText('Added Candidate')).toHaveCount(0)
      await expect(page.getByText('已添加成员', { exact: true })).toHaveCount(0)
      if (status === 409 || status === 'abort' || status === 500) {
        await expect.poll(() => state.memberReads).toBeGreaterThan(readsBefore)
      }
    }
    await page.waitForTimeout(300)
    expect(state.postCount).toBe(1)
  })
}
