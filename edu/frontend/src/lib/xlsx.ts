/**
 * 极简 XLSX 解析器：读取 .xlsx（ZIP + XML）首个工作表的网格数据。
 *
 * 仅依赖浏览器原生能力，通过 DEFLATE 解压（DecompressionStream）解析表格，
 * 无需引入第三方库即可支持题库 xlsx 导入。
 */

interface ZipEntry {
  name: string
  method: number
  start: number
  compressedSize: number
}

/** 读取 ZIP 中央目录，建立文件名到条目信息的映射。 */
async function readZipEntries(buffer: ArrayBuffer): Promise<Map<string, ZipEntry>> {
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)

  // 从文件尾部向前查找 End of Central Directory (EOCD) 签名 0x06054b50
  let eocd = -1
  for (let i = bytes.length - 22; i >= 0 && i >= bytes.length - 65558; i--) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new Error('无效的 xlsx 文件')

  const entryCount = view.getUint16(eocd + 10, true)
  let offset = view.getUint32(eocd + 16, true)
  const entries = new Map<string, ZipEntry>()

  for (let i = 0; i < entryCount; i++) {
    if (view.getUint32(offset, true) !== 0x02014b50) break
    const method = view.getUint16(offset + 10, true)
    const compressedSize = view.getUint32(offset + 20, true)
    const nameLength = view.getUint16(offset + 28, true)
    const extraLength = view.getUint16(offset + 30, true)
    const commentLength = view.getUint16(offset + 32, true)
    const localOffset = view.getUint32(offset + 42, true)
    const name = new TextDecoder('utf-8').decode(bytes.subarray(offset + 46, offset + 46 + nameLength))
    entries.set(name, { name, method, start: localOffset, compressedSize })
    offset += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

/** 解压单个 ZIP 条目内容。 */
async function extractEntry(buffer: ArrayBuffer, entry: ZipEntry): Promise<Uint8Array> {
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)
  const nameLength = view.getUint16(entry.start + 26, true)
  const extraLength = view.getUint16(entry.start + 28, true)
  const dataStart = entry.start + 30 + nameLength + extraLength
  const compressed = bytes.subarray(dataStart, dataStart + entry.compressedSize)

  if (entry.method === 0) return compressed
  if (entry.method !== 8) throw new Error('暂不支持该压缩方式')
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('当前浏览器不支持解析 xlsx，请使用 Chrome/Edge 或改用 CSV')
  }
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}

/** 解析共享字符串表 sharedStrings.xml。 */
function parseSharedStrings(xml: string): string[] {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  const result: string[] = []
  for (const si of Array.from(doc.getElementsByTagName('si'))) {
    let text = ''
    for (const t of Array.from(si.getElementsByTagName('t'))) text += t.textContent ?? ''
    result.push(text)
  }
  return result
}

/** 将 A1 样式的列引用转换为 0 基列索引。 */
function columnIndex(ref: string): number {
  const letters = (ref.match(/^[A-Z]+/) || [''])[0]
  let index = 0
  for (const ch of letters) index = index * 26 + (ch.charCodeAt(0) - 64)
  return index - 1
}

/** 解析工作表 XML，返回二维字符串数组（按行）。 */
function parseSheet(xml: string, shared: string[]): string[][] {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  const rows: string[][] = []
  for (const row of Array.from(doc.getElementsByTagName('row'))) {
    const cells: string[] = []
    for (const c of Array.from(row.getElementsByTagName('c'))) {
      const idx = columnIndex(c.getAttribute('r') || '') 
      const type = c.getAttribute('t')
      let value = ''
      if (type === 'inlineStr') {
        const is = c.getElementsByTagName('is')[0]
        value = is ? Array.from(is.getElementsByTagName('t')).map((t) => t.textContent ?? '').join('') : ''
      } else {
        const v = c.getElementsByTagName('v')[0]
        const raw = v?.textContent ?? ''
        value = type === 's' ? shared[Number(raw)] ?? '' : raw
      }
      cells[idx >= 0 ? idx : cells.length] = value
    }
    rows.push(cells)
  }
  return rows
}

/** 读取 xlsx 文件并返回首个工作表的二维数组。 */
export async function readXlsx(file: File): Promise<string[][]> {
  const buffer = await file.arrayBuffer()
  const entries = await readZipEntries(buffer)
  const decoder = new TextDecoder('utf-8')

  const sharedEntry = entries.get('xl/sharedStrings.xml')
  const shared = sharedEntry
    ? parseSharedStrings(decoder.decode(await extractEntry(buffer, sharedEntry)))
    : []

  // 优先取 workbook 中声明的首个 sheet，否则回退到 sheet1
  let sheetName = 'xl/worksheets/sheet1.xml'
  const workbook = entries.get('xl/workbook.xml')
  if (workbook) {
    const wb = new DOMParser().parseFromString(decoder.decode(await extractEntry(buffer, workbook)), 'application/xml')
    const first = wb.getElementsByTagName('sheet')[0]
    const relId = first?.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id')
      || first?.getAttribute('r:id')
    if (relId) {
      const rels = entries.get('xl/_rels/workbook.xml.rels')
      if (rels) {
        const relDoc = new DOMParser().parseFromString(decoder.decode(await extractEntry(buffer, rels)), 'application/xml')
        for (const rel of Array.from(relDoc.getElementsByTagName('Relationship'))) {
          if (rel.getAttribute('Id') === relId) {
            const target = rel.getAttribute('Target') || ''
            sheetName = target.startsWith('/') ? target.slice(1) : `xl/${target.replace(/^\.\//, '')}`
            break
          }
        }
      }
    }
  }
  const sheetEntry = entries.get(sheetName) || entries.get('xl/worksheets/sheet1.xml')
  if (!sheetEntry) throw new Error('xlsx 缺少工作表')
  return parseSheet(decoder.decode(await extractEntry(buffer, sheetEntry)), shared)
}

// ==================== XLSX 生成（用于导入模板） ====================

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff
  for (let i = 0; i < bytes.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function xmlEscape(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function colName(index: number): string {
  let name = ''
  let n = index
  while (n >= 0) {
    name = String.fromCharCode(65 + (n % 26)) + name
    n = Math.floor(n / 26) - 1
  }
  return name
}

/** 用一段字节拼装 ZIP（采用 store 存储，无需压缩）。 */
function zip(files: { name: string; data: Uint8Array }[]): Blob {
  const encoder = new TextEncoder()
  const localParts: Uint8Array[] = []
  const centralParts: Uint8Array[] = []
  let offset = 0

  const now = new Date()
  const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2)
  const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()

  for (const file of files) {
    const nameBytes = encoder.encode(file.name)
    const crc = crc32(file.data)
    const size = file.data.length

    const local = new Uint8Array(30 + nameBytes.length)
    const lv = new DataView(local.buffer)
    lv.setUint32(0, 0x04034b50, true)
    lv.setUint16(4, 20, true)
    lv.setUint16(6, 0, true)
    lv.setUint16(8, 0, true)
    lv.setUint16(10, dosTime, true)
    lv.setUint16(12, dosDate, true)
    lv.setUint32(14, crc, true)
    lv.setUint32(18, size, true)
    lv.setUint32(22, size, true)
    lv.setUint16(26, nameBytes.length, true)
    lv.setUint16(28, 0, true)
    local.set(nameBytes, 30)
    localParts.push(local, file.data)

    const central = new Uint8Array(46 + nameBytes.length)
    const cv = new DataView(central.buffer)
    cv.setUint32(0, 0x02014b50, true)
    cv.setUint16(4, 20, true)
    cv.setUint16(6, 20, true)
    cv.setUint16(8, 0, true)
    cv.setUint16(10, 0, true)
    cv.setUint16(12, dosTime, true)
    cv.setUint16(14, dosDate, true)
    cv.setUint32(16, crc, true)
    cv.setUint32(20, size, true)
    cv.setUint32(24, size, true)
    cv.setUint16(28, nameBytes.length, true)
    cv.setUint16(30, 0, true)
    cv.setUint16(32, 0, true)
    cv.setUint16(34, 0, true)
    cv.setUint16(36, 0, true)
    cv.setUint32(38, 0, true)
    cv.setUint32(42, offset, true)
    central.set(nameBytes, 46)
    centralParts.push(central)

    offset += local.length + size
  }

  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0)
  const end = new Uint8Array(22)
  const ev = new DataView(end.buffer)
  ev.setUint32(0, 0x06054b50, true)
  ev.setUint16(8, files.length, true)
  ev.setUint16(10, files.length, true)
  ev.setUint32(12, centralSize, true)
  ev.setUint32(16, offset, true)

  const parts = [...localParts, ...centralParts, end]
  const total = parts.reduce((sum, part) => sum + part.length, 0)
  const merged = new Uint8Array(total)
  let cursor = 0
  for (const part of parts) {
    merged.set(part, cursor)
    cursor += part.length
  }
  return new Blob([merged.buffer as ArrayBuffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

/** 生成仅含首个工作表（内联字符串）的 xlsx Blob。 */
export function buildXlsx(rows: (string | number)[][]): Blob {
  const encoder = new TextEncoder()
  const sheetRows = rows
    .map((row, r) => {
      const cells = row
        .map((value, c) => {
          const ref = `${colName(c)}${r + 1}`
          const text = xmlEscape(String(value ?? ''))
          return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${text}</t></is></c>`
        })
        .join('')
      return `<row r="${r + 1}">${cells}</row>`
    })
    .join('')

  const files = [
    {
      name: '[Content_Types].xml',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
          '<Default Extension="xml" ContentType="application/xml"/>' +
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
          '</Types>',
      ),
    },
    {
      name: '_rels/.rels',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
          '</Relationships>',
      ),
    },
    {
      name: 'xl/workbook.xml',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
          '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
      ),
    },
    {
      name: 'xl/_rels/workbook.xml.rels',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
          '</Relationships>',
      ),
    },
    {
      name: 'xl/worksheets/sheet1.xml',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
          `<sheetData>${sheetRows}</sheetData></worksheet>`,
      ),
    },
  ]
  return zip(files)
}
