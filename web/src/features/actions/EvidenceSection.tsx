import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Flex, Form, Input, Typography, Upload } from 'antd'
import type { UploadFile } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { evidenceDownloadUrl, precheckEvidenceFile, uploadActionEvidence } from '../../api/product'
import type { EvidenceResponse } from '../../api/product'
import {
  TOO_LARGE_TEXT,
  TYPE_NOT_ALLOWED_TEXT,
  classifyCommandFailure,
  failureAlertType,
  failureNeedsRefresh,
} from '../../product/commandFailure'
import type { CommandFailure } from '../../product/commandFailure'
import { formatDateTime } from '../../product/format'
import { ItemList } from '../../ui/ItemList'
import { actorText } from '../actorNames'
import { SectionNotice } from '../SectionNotice'
import { SectionSpin } from '../SectionSpin'
import type { ResourceState } from '../useScopedResource'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.docx,.xlsx,.pptx,.txt,.csv'
const FILE_FIELD_ID = 'evidence-file'
const DESCRIPTION_FIELD_ID = 'evidence-description'

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

type UploadOutcome =
  | { type: 'success'; text: string }
  | { type: 'failure'; failure: CommandFailure }

interface EvidenceSectionProps {
  actionId: string
  cancelled: boolean
  state: ResourceState<EvidenceResponse[]>
  names: ReadonlyMap<string, string>
  // 上传已被服务器确认，或失败后需要核对服务器状态时，请页面重新读取。
  onRefresh: () => void
}

// 证据：Upload 只负责选择文件和文件列表；传输走 uploadActionEvidence（原始字节、MIME、编码文件名、说明），
// 由明确的“上传证据”按钮触发（beforeUpload 返回 false，不使用 Upload 自带的传输）。
// 没有真实的上传进度，所以不显示百分比；中断后不自动重传。下载是同源附件链接，不读成 Blob。
export function EvidenceSection({ actionId, cancelled, state, names, onRefresh }: EvidenceSectionProps) {
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<UploadOutcome | null>(null)
  const busyRef = useRef(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const selected = fileList[0] as (UploadFile & File) | undefined

  async function upload() {
    if (selected === undefined || busyRef.current) return
    const precheck = precheckEvidenceFile(selected)
    if (precheck !== null) {
      setOutcome({
        type: 'failure',
        failure: {
          kind: precheck === 'too_large' ? 'too-large' : 'type-not-allowed',
          message: precheck === 'too_large' ? TOO_LARGE_TEXT : TYPE_NOT_ALLOWED_TEXT,
          fieldErrors: {},
        },
      })
      return
    }
    busyRef.current = true
    setBusy(true)
    setOutcome(null)
    try {
      // 只发一次：失败或中断的上传不会自动重放。
      const evidence = await uploadActionEvidence(actionId, selected, description)
      if (!mountedRef.current) return
      setOutcome({
        type: 'success',
        text: `服务器已确认上传：${evidence.original_name} · ${formatBytes(evidence.size_bytes)} · SHA-256 ${evidence.sha256.slice(0, 12)}…`,
      })
      setFileList([])
      setDescription('')
      onRefresh()
    } catch (error) {
      if (!mountedRef.current) return
      const failure = classifyCommandFailure(error, { label: '上传', upload: true })
      setOutcome({ type: 'failure', failure })
      if (failureNeedsRefresh(failure)) onRefresh()
    } finally {
      busyRef.current = false
      if (mountedRef.current) setBusy(false)
    }
  }

  return (
    <section aria-labelledby="evidence-title">
      <Card title={<h2 id="evidence-title">证据</h2>}>
        <Flex vertical gap={24}>
          <Flex vertical gap={12} component="section" aria-labelledby="evidence-upload-title">
            <h3 id="evidence-upload-title">上传证据</h3>
            {cancelled ? (
              <Typography.Text type="secondary">当前整改项已取消，不能上传证据。</Typography.Text>
            ) : (
              <Form layout="vertical" requiredMark={false} disabled={busy} onFinish={() => void upload()}>
                <Form.Item label="证据文件" htmlFor={FILE_FIELD_ID} extra="选择后点击“上传证据”才会发送；允许 PDF、PNG、JPEG、DOCX、XLSX、PPTX、TXT、CSV。">
                  <Upload
                    id={FILE_FIELD_ID}
                    accept={ACCEPT}
                    maxCount={1}
                    fileList={fileList}
                    showUploadList={{ showRemoveIcon: !busy }}
                    beforeUpload={(file) => {
                      setFileList([file])
                      setOutcome(null)
                      return false
                    }}
                    onRemove={() => {
                      setFileList([])
                      setOutcome(null)
                    }}
                  >
                    <Button icon={<UploadOutlined aria-hidden />} disabled={busy}>
                      选择文件
                    </Button>
                  </Upload>
                </Form.Item>
                <Form.Item label="说明（可选）" htmlFor={DESCRIPTION_FIELD_ID}>
                  <Input.TextArea
                    id={DESCRIPTION_FIELD_ID}
                    value={description}
                    maxLength={1000}
                    rows={2}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </Form.Item>
                <Flex vertical gap={12} align="flex-start">
                  <Button type="primary" htmlType="submit" loading={busy} disabled={selected === undefined}>
                    上传证据
                  </Button>
                  <Typography.Text type="secondary">
                    文件大小、SHA-256 和存储位置由服务器计算与分配；上传失败不会自动重试。
                  </Typography.Text>
                </Flex>
              </Form>
            )}
            {outcome === null ? null : outcome.type === 'success' ? (
              <Alert type="success" showIcon role="status" title={outcome.text} />
            ) : outcome.failure.message === '' ? null : (
              <Alert type={failureAlertType(outcome.failure)} showIcon title={outcome.failure.message} />
            )}
          </Flex>

          <Flex vertical gap={12} component="section" aria-labelledby="evidence-list-title">
            <h3 id="evidence-list-title">已上传的证据</h3>
            <SectionSpin state={state}>
            <SectionNotice state={state} loadingLabel="正在读取证据" unavailableText="证据不可用。" />
            {state.status === 'ready' ? (
              <ItemList
                label="已上传的证据"
                emptyText="暂无证据。"
                items={state.data.map((evidence) => ({
                  key: evidence.id,
                  content: (
                    <Flex justify="space-between" align="flex-start" wrap gap={8}>
                      <Flex vertical>
                        <Typography.Text strong>{evidence.original_name}</Typography.Text>
                        <Typography.Text type="secondary">
                          {evidence.content_type ?? '未知类型'} · {formatBytes(evidence.size_bytes)} ·{' '}
                          {evidence.description ?? '无说明'}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          上传人 {actorText(evidence.uploaded_by, names)} · {formatDateTime(evidence.created_at)}
                        </Typography.Text>
                      </Flex>
                      <Button
                        href={evidenceDownloadUrl(evidence.id)}
                        icon={<DownloadOutlined aria-hidden />}
                        aria-label={`下载 ${evidence.original_name}`}
                      >
                        下载
                      </Button>
                    </Flex>
                  ),
                }))}
              />
            ) : null}
            </SectionSpin>
          </Flex>
        </Flex>
      </Card>
    </section>
  )
}
