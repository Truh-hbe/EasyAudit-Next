import { participantRoleName } from './terms'

// 后端结构化错误码（src/easyaudit_next/rules.py 的 RuleCode / FieldErrorCode）对应的界面中文。
// 服务端 `detail` 是英文排障文本，界面永不显示；未知 code 一律用通用中文。
// 每个 RuleCode 都必须在这里有一条（scripts/check_error_codes.py 检查）。

type Params = Readonly<Record<string, unknown>>

interface RuleContext {
  // 操作名称，如 "签发发现项"。
  label: string
  params: Params
}

function numberParam(params: Params, key: string): string {
  const value = params[key]
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

function rolesParam(params: Params): string {
  const roles = params.roles
  if (!Array.isArray(roles) || roles.length === 0) return '所需角色'
  return roles.map((role) => (typeof role === 'string' ? participantRoleName(role) : '未知角色')).join('、')
}

export const RULE_MESSAGES: Readonly<Record<string, (context: RuleContext) => string>> = {
  'request.invalid': ({ label }) => `提交内容不符合要求，${label}未完成。请检查后重试。`,
  'rule.unspecified': ({ label }) => genericRuleMessage(label),

  'workflow.invalid_transition': ({ label }) => `当前状态下不能${label}。请刷新后确认最新状态。`,
  'workflow.unknown_action': ({ label }) => `${label}不被当前规则支持，未完成。`,
  'workflow.missing_context': ({ label }) => `${label}缺少当前状态信息，未完成。请刷新后重试。`,

  'case.close_blocked_by_open_findings': () => '仍有发现项未关闭或作废，暂时不能关闭审查活动。',

  'finding.missing_participant_roles': ({ params }) => `签发前需要先指定：${rolesParam(params)}。`,
  'finding.issue_requires_nonconformity': () => '只有不符合项才能签发整改。',
  'finding.accept_requires_observation': () => '只有观察项才能直接接受。',
  'finding.requires_open': ({ label }) => `发现项当前不是待签发状态，不能${label}。请刷新后确认。`,
  'finding.invalid_case_lifecycle': ({ label, params }) => {
    switch (params.operation) {
      case 'create':
        return '审查活动进行中才能记录发现项。'
      case 'manage_participants':
        return '当前审查活动状态下不能调整发现项的参与方。'
      default:
        return `当前审查活动状态下不能${label}。`
    }
  },
  'finding.participants_locked': () => '发现项已结束，参与方不能再调整。',
  'finding.invalid_type': () => '发现项类型无效，请重新选择。',
  'finding.verification_requires_actions': () => '至少需要一个未取消的整改项，才能提交验证。',
  'finding.verification_requires_actions_done': () => '所有未取消的整改项都完成后，才能提交验证。',
  'finding.reopen_after_case_closure': () => '审查活动已关闭，不能再重新打开发现项。',

  'submission.plan_requires_rectifying': () => '只有整改中的发现项才能提交整改计划。',
  'submission.mismatch': ({ label }) => `${label}与当前步骤不匹配，未完成。请刷新页面后重试。`,
  'verification.case_closed': () => '审查活动已关闭，不能再验证发现项。',

  'action.requires_rectifying_finding': () => '只有整改中的发现项才能操作整改项。',
  'action.requires_active_case': () => '审查活动进行中才能操作整改项。',
  'action.already_exists': () => '该发现项已有整改项，请刷新后查看。',
  'action.missing': () => '当前没有整改项，请刷新后确认。',
  'action.assignees_locked': () => '整改项已结束，执行人不能再调整。',
  'action.evidence_on_cancelled': () => '整改项已取消，不能再登记证据。',
  'action.transfer_requires_done': () => '只有已完成的整改项才能转交并重开。',
  'action.executor_still_active': () => '原执行人仍可操作，可以直接重新打开，无需转交。',

  'role.not_allowed_for_actor': () => '所选对象不能担任该角色，请重新选择。',

  'nudge.no_eligible_recipients': () => '当前没有可催办的对象。',
  'export.row_limit_exceeded': ({ params }) => {
    const max = numberParam(params, 'max_rows')
    return `导出行数超过${max === '' ? '' : ` ${max} `}行的上限，请缩小筛选范围后重试。`
  },

  'evidence.file_empty': () => '文件为空，未上传。',
  'evidence.filename_invalid': () => '文件名无效，未上传。请重命名文件后重试。',

  'password.too_short': ({ params }) => {
    const min = numberParam(params, 'min')
    return `密码长度不足${min === '' ? '' : `，至少需要 ${min} 个字符`}。`
  },
  'password.too_long': ({ params }) => {
    const max = numberParam(params, 'max')
    return `密码过长${max === '' ? '' : `，不能超过 ${max} 个字符`}。`
  },
  'password.reused': () => '新密码不能与当前密码相同。',
  'password.current_invalid': () => '当前密码不正确。',
}

export function genericRuleMessage(label: string): string {
  return `${label}不满足当前规则，未完成。`
}

// 页面级规则错误的中文提示；未知 code 或没有 code 用通用中文。
export function ruleMessage(code: string | null, params: Params, label: string): string {
  const render = code !== null && Object.hasOwn(RULE_MESSAGES, code) ? RULE_MESSAGES[code] : undefined
  return render === undefined ? genericRuleMessage(label) : render({ label, params })
}

export const FIELD_MESSAGES: Readonly<Record<string, (fieldLabel: string, params: Params) => string>> = {
  required: (field) => `请填写${field}`,
  padded: (field) => `${field}首尾不能有空格`,
  too_long: (field, params) => {
    const max = numberParam(params, 'max')
    return max === '' ? `${field}过长` : `${field}不能超过 ${max} 个字符`
  },
  too_short: (field, params) => {
    const min = numberParam(params, 'min')
    return min === '' ? `${field}过短` : `${field}至少需要 ${min} 个字符`
  },
  invalid_choice: (field) => `请选择有效的${field}`,
  invalid_datetime: (field) => `${field}的时间格式无效`,
  range: (field) => `${field}超出允许范围`,
  invalid: (field) => `${field}不符合要求`,
}

// 字段级提示；未知字段码用"不符合要求"。
export function fieldMessage(code: string, field: string, fieldLabel: string, params: Params): string {
  if (code === 'range' && field === 'planned_end_at') return `${fieldLabel}不能早于开始时间`
  const render = Object.hasOwn(FIELD_MESSAGES, code) ? FIELD_MESSAGES[code] : undefined
  return render === undefined ? `${fieldLabel}不符合要求` : render(fieldLabel, params)
}
