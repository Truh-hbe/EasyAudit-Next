interface PlaceholderPageProps {
  title: string
  slice: string
  description: string
}

export function PlaceholderPage({ title, slice, description }: PlaceholderPageProps) {
  return (
    <section className="placeholder" aria-labelledby="placeholder-title">
      <p className="eyebrow">{slice}</p>
      <h1 id="placeholder-title">{title}</h1>
      <p>{description}</p>
      <p className="placeholder-note">
        当前仅提供产品结构入口；本页没有读取、推断或缓存业务领域状态。
      </p>
    </section>
  )
}
