import { useEffect, useRef, useState } from 'react'

import type { CommandFailure, CommandResult } from '../../product/commandFailure'

// 抽屉里的写操作：失败时抽屉保持打开并保留已填内容，进行中不能关闭。
// 每次打开、关闭或卸载都换一个编辑会话：晚到的结果只影响发起它的会话，不能关闭或污染后来打开的抽屉。
export function useDrawerCommand(open: boolean, onClose: () => void) {
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<CommandFailure | null>(null)
  const submittingRef = useRef(false)
  const sessionRef = useRef(0)

  useEffect(() => {
    sessionRef.current += 1
    if (open) setFailure(null)
    return () => {
      sessionRef.current += 1
    }
  }, [open])

  async function submit(run: () => Promise<CommandResult>) {
    if (submittingRef.current) return
    submittingRef.current = true
    const session = sessionRef.current
    setSubmitting(true)
    setFailure(null)
    let result: CommandResult
    try {
      result = await run()
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
    if (sessionRef.current !== session) return
    if (result.ok) onClose()
    else if (result.failure.kind !== 'busy' && result.failure.kind !== 'session') setFailure(result.failure)
  }

  return { submitting, failure, submit, clearFieldErrors: () => setFailure((current) => (current === null ? null : { ...current, fieldErrors: {} })) }
}
