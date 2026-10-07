import type { ScenarioActionOperationContext, ScenarioActionOperations } from './registry'

// 整改项写操作的共用前置条件（两个 v1 场景的整改规则相同，规则仍属于各自场景）：
// 活跃审查活动（进行中/待关闭）+ 整改中的发现项；终态整改项另行禁止执行人管理。
// 只使用页面已读取的确定生命周期；父级状态未知（null）时不拦截，由服务器判断。
// 这是状态门槛，不是权限：角色是否允许一律由服务器判断。

function parentBlockedReason({ finding, reviewCase }: ScenarioActionOperationContext): string | null {
  if (reviewCase !== null && reviewCase !== 'in_progress' && reviewCase !== 'awaiting_closure') {
    return '审查活动当前不在进行中或待关闭阶段，整改项的写操作已关闭。'
  }
  switch (finding) {
    case 'verifying':
      return '发现项已提交验证，整改项暂时不能操作。需由有权限者驳回验证或重新打开发现项，使其回到整改中后才能继续整改。'
    case 'closed':
      return '发现项已关闭，整改项暂时不能操作。需由有权限者重新打开发现项后才能继续整改。'
    case 'voided':
      return '发现项已作废，整改项不能再操作。'
    case 'open':
      return '发现项尚未签发进入整改，整改项暂时不能操作。'
    default:
      return null
  }
}

export function standardActionOperations(context: ScenarioActionOperationContext): ScenarioActionOperations {
  const blockedReason = parentBlockedReason(context)
  if (blockedReason !== null) {
    return { blockedReason, writable: false, manageAssignees: false, uploadEvidence: false }
  }
  return {
    blockedReason: null,
    writable: true,
    manageAssignees: context.action === 'todo' || context.action === 'in_progress',
    uploadEvidence: context.action !== 'cancelled',
  }
}
