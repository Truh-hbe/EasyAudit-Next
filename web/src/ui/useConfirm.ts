import { App } from 'antd'
import type { ModalFuncProps } from 'antd'
import { useCallback, useEffect, useRef } from 'react'

// modal.confirm 由根级 App 持有，不会随组件卸载。这里保存实例并在卸载时销毁，
// 页面在资源（路由）变化时也可主动 destroy，避免确认框带着旧对象的闭包残留。
export function useConfirm() {
  const { modal } = App.useApp()
  const instance = useRef<{ destroy: () => void } | null>(null)
  const destroy = useCallback(() => {
    instance.current?.destroy()
    instance.current = null
  }, [])
  useEffect(() => destroy, [destroy])
  const confirm = useCallback(
    (config: ModalFuncProps) => {
      destroy()
      instance.current = modal.confirm(config)
    },
    [modal, destroy],
  )
  return { confirm, destroy }
}
