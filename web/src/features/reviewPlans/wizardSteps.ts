// 向导两步：先保存计划，再创建审查活动。进度由路由决定（/review-plans/new → /review-plans/:planId/review-cases/new）。
export const WIZARD_STEPS = [
  { title: '保存审查计划' },
  { title: '填写审查活动' },
]
