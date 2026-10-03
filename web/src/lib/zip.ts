// 依存なしの最小 ZIP(無圧縮/store method) ライター。
// WAV は非圧縮なので store で十分。複数の変換済み WAV を 1 つの ZIP に
// まとめてダウンロードするために使う（外部ライブラリ・ネットワーク不要）。

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export interface ZipEntry {
  name: string;
  data: Uint8Array;
}

// DOS 時刻は固定（再現性・簡潔さ優先。1980-01-01 00:00）。
const DOS_TIME = 0;
const DOS_DATE = 0x21;

export function buildZip(entries: ZipEntry[]): Blob {
  const enc = new TextEncoder();
  const local: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;

  for (const e of entries) {
    const nameBytes = enc.encode(e.name);
    const crc = crc32(e.data);
    const size = e.data.length;

    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); // local file header signature
    lh.setUint16(4, 20, true); // version needed
    lh.setUint16(6, 0x0800, true); // flags: UTF-8 filename
    lh.setUint16(8, 0, true); // method: store
    lh.setUint16(10, DOS_TIME, true);
    lh.setUint16(12, DOS_DATE, true);
    lh.setUint32(14, crc, true);
    lh.setUint32(18, size, true); // compressed size
    lh.setUint32(22, size, true); // uncompressed size
    lh.setUint16(26, nameBytes.length, true);
    lh.setUint16(28, 0, true); // extra length
    const lhb = new Uint8Array(lh.buffer);
    local.push(lhb, nameBytes, e.data);

    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); // central dir header signature
    ch.setUint16(4, 20, true); // version made by
    ch.setUint16(6, 20, true); // version needed
    ch.setUint16(8, 0x0800, true); // flags: UTF-8
    ch.setUint16(10, 0, true); // method: store
    ch.setUint16(12, DOS_TIME, true);
    ch.setUint16(14, DOS_DATE, true);
    ch.setUint32(16, crc, true);
    ch.setUint32(20, size, true);
    ch.setUint32(24, size, true);
    ch.setUint16(28, nameBytes.length, true);
    ch.setUint16(30, 0, true); // extra length
    ch.setUint16(32, 0, true); // comment length
    ch.setUint16(34, 0, true); // disk number
    ch.setUint16(36, 0, true); // internal attrs
    ch.setUint32(38, 0, true); // external attrs
    ch.setUint32(42, offset, true); // local header offset
    central.push(new Uint8Array(ch.buffer), nameBytes);

    offset += lhb.length + nameBytes.length + size;
  }

  const centralStart = offset;
  let centralSize = 0;
  for (const c of central) centralSize += c.length;

  const eocd = new DataView(new ArrayBuffer(22));
  eocd.setUint32(0, 0x06054b50, true); // end of central dir signature
  eocd.setUint16(8, entries.length, true); // entries on this disk
  eocd.setUint16(10, entries.length, true); // total entries
  eocd.setUint32(12, centralSize, true);
  eocd.setUint32(16, centralStart, true);

  // 全パートを単一バッファへ結合して返す（Blob の BlobPart 型差異を回避しつつ効率的）。
  const parts = [...local, ...central, new Uint8Array(eocd.buffer)];
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let pos = 0;
  for (const p of parts) {
    out.set(p, pos);
    pos += p.length;
  }
  return new Blob([out], { type: 'application/zip' });
}

// data:URI もしくは生 base64 → Uint8Array
export function dataUriToBytes(uri: string): Uint8Array {
  const comma = uri.indexOf(',');
  const b64 = comma >= 0 ? uri.slice(comma + 1) : uri;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
