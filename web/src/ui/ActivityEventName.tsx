import { activityEventName, isKnownActivityEvent } from '../product/terms'

export function ActivityEventName({ eventType }: { eventType: string }) {
  if (isKnownActivityEvent(eventType)) {
    return <strong>{activityEventName(eventType)}</strong>
  }
  return (
    <>
      <strong>未知操作</strong>
      <span className="status-tag-raw">{eventType}</span>
    </>
  )
}
