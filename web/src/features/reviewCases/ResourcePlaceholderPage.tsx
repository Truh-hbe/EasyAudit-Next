import { Link, useParams } from 'react-router'

export function ResourcePlaceholderPage({ resource }: { resource: 'Finding' | 'ActionItem' }) {
  const params = useParams()
  const id = resource === 'Finding' ? params.findingId : params.actionItemId

  return (
    <section className="surface-page placeholder" aria-labelledby="resource-placeholder-title">
      <p className="eyebrow">M3.5.3 placeholder</p>
      <h1 id="resource-placeholder-title">{resource}</h1>
      <p>当前仅保留原始资源导航指针；本切片没有读取或推断该资源的协作、权限、整改或验证状态。</p>
      <p className="placeholder-note">资源 ID：{id ?? 'unknown'}</p>
      <Link to="/me/workbench">返回我的工作</Link>
    </section>
  )
}
