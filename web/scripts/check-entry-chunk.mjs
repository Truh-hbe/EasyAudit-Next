// 守护入口包：从入口 chunk 出发，沿静态 `imports` 递归，检查 antd Table 的主实现不在其中。
// 动态 import（`dynamicImports`，即 React.lazy 页面）不遍历，Table 只允许出现在那里。
//
// 判定标准（实测：在 Shell 中渲染 <Table> 时，入口里会出现下列模块）：
//   antd/es/table/Table.js、antd/es/table/InternalTable.js、@rc-component/table/es/Table.js。
// 不能禁止所有 `antd/es/table/*`：入口本来就含有很小的 `TableMeasureRowContext.js`
// （被 Typography 等组件引用），只匹配上面三个主实现模块。
//
// 通过 Vite 的 JS API 构建并读取内存中的 bundle 元数据（write: false），
// 不需要打开 build.manifest，也不会在 dist 里多出任何文件。
import { build } from 'vite'

const tableImplementation =
  /[\\/](antd[\\/](es|lib)[\\/]table[\\/](Table|InternalTable)\.js|@rc-component[\\/]table[\\/](es|lib)[\\/]Table\.js|rc-table[\\/](es|lib)[\\/]Table\.js)$/

const result = await build({ logLevel: 'silent', build: { write: false } })
const outputs = Array.isArray(result) ? result : [result]
const chunks = outputs.flatMap((o) => ('output' in o ? o.output : [])).filter((c) => c.type === 'chunk')
const byFile = new Map(chunks.map((c) => [c.fileName, c]))
const entries = chunks.filter((c) => c.isEntry)

if (entries.length === 0) {
  console.error('check:entry: 没有找到入口 chunk')
  process.exit(1)
}

const seen = new Set()
const violations = []
function visit(chunk, path) {
  if (seen.has(chunk.fileName)) return
  seen.add(chunk.fileName)
  const here = [...path, chunk.fileName]
  for (const id of Object.keys(chunk.modules)) {
    if (tableImplementation.test(id)) violations.push({ id, path: here })
  }
  for (const dep of chunk.imports) {
    const next = byFile.get(dep)
    if (next !== undefined) visit(next, here)
  }
}
for (const entry of entries) visit(entry, [])

if (violations.length > 0) {
  console.error('check:entry: 入口静态闭包包含 antd Table 实现，应只出现在懒加载页面 chunk 中：')
  for (const v of violations) {
    console.error(`  ${v.id.split('node_modules/').pop()}\n    via ${v.path.join(' -> ')}`)
  }
  process.exit(1)
}
console.log(`check:entry: ok（入口静态闭包 ${seen.size} 个 chunk，不含 antd Table 实现）`)
