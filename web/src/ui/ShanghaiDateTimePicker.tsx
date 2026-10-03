import type { Dayjs } from 'dayjs'
import type { FocusEvent, KeyboardEvent } from 'react'
import { useMemo, useRef, useState } from 'react'

import { DISPLAY_DATE_TIME_TEXT_FORMAT as FORMAT } from '../product/format'
import { WallTimePicker, wallTimeGenerateConfig } from './wallTimeGenerateConfig'

// 文本 → 面板的值（UTC 承载的墙上时间）。严格解析：越界或不存在的日期（02/30、12:99）返回 undefined。
function toPickerValue(text: string | undefined): Dayjs | undefined {
  return wallTimeGenerateConfig.locale.parse('zh_CN', text ?? '', [FORMAT]) ?? undefined
}

export interface ShanghaiDateTimePickerProps {
  // 表单值是 `YYYY/MM/DD HH:mm` 文本（上海墙上时间）；空串表示未填写。无法解析的输入也原样保存，交给校验报错。
  value?: string
  onChange?: (text: string) => void
  id?: string
  // Form.Item 会用自己的错误 id 覆盖元素上的 aria-describedby，所以说明文字的 id 走单独的 prop，与注入的 id 合并。
  'aria-describedby'?: string
  hintId?: string
}

// 按上海时间输入的日期时间选择器。
// 直接使用 DatePicker 有三个问题：面板和键入的文本都由设备时区的 dayjs 处理——设备夏令时空洞里的时刻会被改成别的值，
// “此刻”是设备的当地时间；无效文本会被清空或归一化成另一个时刻；日期框里按 Enter 还会提交整个表单。所以：
// - 面板用 UTC 承载墙上时间的 generateConfig（见 wallTimeGenerateConfig），“此刻”取上海当前的墙上时间；
// - 键入的原始文本是事实来源：Enter、失焦时原样交给表单校验，无效时输入框保留原文（preserveInvalidOnBlur），
//   面板保持上一个有效值；
// - 日期框里的 Enter 只确认日期，不提交表单。
// 时区解释只发生在提交时：format.ts 按 Asia/Shanghai 转换，不存在的时刻照样拒绝。
export function ShanghaiDateTimePicker({ value, onChange, id, 'aria-describedby': injectedDescribedBy, hintId }: ShanghaiDateTimePickerProps) {
  // 自上次同步以来键入的原始文本；null 表示没有待提交的键入。
  const describedBy = [injectedDescribedBy, hintId].filter((part) => part !== undefined && part !== '').join(' ') || undefined
  const typed = useRef<string | null>(null)
  // 输入框的可见文本只在面板值变化时同步；无效文本状态下重新确认同一个值不会变，所以用 key 重建选择器来恢复。
  const [syncKey, setSyncKey] = useState(0)
  // 面板的值：文本有效时跟随文本，无效时保持上一个有效值，清空时为空。
  const lastValid = useRef<Dayjs | undefined>(undefined)
  const pickerValue = useMemo(() => {
    if ((value ?? '') === '') lastValid.current = undefined
    else lastValid.current = toPickerValue(value) ?? lastValid.current
    return lastValid.current
  }, [value])

  function commitTyped() {
    if (typed.current === null) return
    onChange?.(typed.current)
    typed.current = null
  }

  return (
    <div
      onInput={(event) => {
        if (event.target instanceof HTMLInputElement) typed.current = event.target.value
      }}
      onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== 'Enter' || !(event.target instanceof HTMLInputElement)) return
        // 日期框里的 Enter 只确认日期，不提交表单。
        event.preventDefault()
        commitTyped()
      }}
      onBlur={(event: FocusEvent<HTMLDivElement>) => {
        if (event.target instanceof HTMLInputElement) commitTyped()
      }}
    >
      <WallTimePicker
        key={syncKey}
        id={id}
        aria-describedby={describedBy}
        value={pickerValue}
        showTime={{ format: 'HH:mm' }}
        format={FORMAT}
        preserveInvalidOnBlur
        onChange={(picked: Dayjs | null) => {
          // 面板选择或清除：以选中的墙上时间为准，丢弃待提交的键入。
          typed.current = null
          onChange?.(picked === null ? '' : picked.format(FORMAT))
        }}
        // 无效文本时面板保持上一个有效值：重新确认同一个值不会触发 onChange，所以在显式确认时也同步。
        onOk={(picked: Dayjs) => {
          typed.current = null
          if ((value ?? '') !== '' && toPickerValue(value) === undefined) setSyncKey((key) => key + 1)
          onChange?.(picked.format(FORMAT))
        }}
      />
    </div>
  )
}
