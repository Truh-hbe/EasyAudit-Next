import { expect, test, type Page, type Route } from '@playwright/test'

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
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/members`, (route) => {
    if (route.request().method() === 'POST') {
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

    await page.goto('/review-cases/case-narrow')
    await expect(page.getByRole('heading', { name: 'Team Case case-narrow' })).toBeVisible()
    await expect(page.getByRole('region', { name: '团队管理' }).getByText('Team Lead')).toBeVisible()
    expect(await overflow()).toBeLessThanOrEqual(1)
  })
}
