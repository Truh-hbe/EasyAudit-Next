// 操作人、提出人等只显示已授权接口返回过的名称；接口只给 ID 时显示"名称暂不可用"和短 ID（design.md）。
export function actorText(actorId: string | null, names: ReadonlyMap<string, string>): string {
  if (actorId === null) return '系统'
  return names.get(actorId) ?? `名称暂不可用（${actorId.slice(0, 8)}）`
}
