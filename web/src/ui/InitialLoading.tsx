import { Skeleton } from 'antd'

// 首次加载占位：骨架本身对读屏隐藏，用视觉隐藏的 status 文本告知加载中；
// 调用方在内容区根节点同时设置 aria-busy。
export function InitialLoading({ label, rows }: { label: string; rows: number }) {
  return (
    <>
      <div aria-hidden>
        <Skeleton active paragraph={{ rows }} />
      </div>
      <span className="visually-hidden" role="status">{label}</span>
    </>
  )
}
