import { Button } from 'antd'
import type { ButtonProps } from 'antd'
import type { MouseEvent } from 'react'
import { useHref, useLinkClickHandler } from 'react-router'
import type { To } from 'react-router'

export interface ButtonLinkProps
  extends Omit<ButtonProps, 'href' | 'htmlType' | 'loading' | 'onClick'> {
  to: To
  replace?: boolean
}

// 站内跳转的按钮外观：渲染为 <a href>，保留新标签页和修饰键等链接行为。
export function ButtonLink({ to, replace, target, ...buttonProps }: ButtonLinkProps) {
  const href = useHref(to)
  const handleClick = useLinkClickHandler<HTMLAnchorElement>(to, { replace, target })
  return (
    <Button
      {...buttonProps}
      href={href}
      target={target}
      onClick={(event: MouseEvent<HTMLElement>) =>
        handleClick(event as MouseEvent<HTMLAnchorElement>)
      }
    />
  )
}
