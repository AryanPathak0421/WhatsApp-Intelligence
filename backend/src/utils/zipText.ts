import zlib from 'node:zlib';

/**
 * Minimal, defensive ZIP reader for one purpose: pull the chat .txt out of a WhatsApp "Export chat" archive.
 * Not a general unzip: no ZIP64, no encryption, no nested archives, directories and __MACOSX entries are skipped, and decompression
 * is capped so a small archive cannot expand into memory ("zip bomb").
 */
export class ZipError extends Error {}

const u16 = (b: Buffer, o: number) => b.readUInt16LE(o);
const u32 = (b: Buffer, o: number) => b.readUInt32LE(o);

export function extractFirstTxt(zip: Buffer, maxBytes: number): { name: string; data: Buffer } {
  let eocd = -1;
  for (let i = zip.length - 22; i >= Math.max(0, zip.length - 22 - 65_535); i--) if (u32(zip, i) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new ZipError('Not a ZIP file');
  const count = u16(zip, eocd + 10), cdSize = u32(zip, eocd + 12), cdOffset = u32(zip, eocd + 16);
  if (count === 0xffff || cdOffset === 0xffffffff || cdSize === 0xffffffff) throw new ZipError('ZIP64 archives are not supported');
  let p = cdOffset;
  for (let n = 0; n < count; n++) {
    if (p + 46 > zip.length || u32(zip, p) !== 0x02014b50) throw new ZipError('Corrupt ZIP directory');
    const flags = u16(zip, p + 8), method = u16(zip, p + 10), compSize = u32(zip, p + 20), size = u32(zip, p + 24);
    const nameLen = u16(zip, p + 28), extraLen = u16(zip, p + 30), commentLen = u16(zip, p + 32), local = u32(zip, p + 42);
    const name = zip.subarray(p + 46, p + 46 + nameLen).toString('utf8');
    p += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith('/') || name.includes('__MACOSX') || !/\.txt$/i.test(name)) continue;
    if (flags & 1) throw new ZipError('Encrypted ZIP files are not supported');
    if (size > maxBytes) throw new ZipError('The text file inside the ZIP is too large');
    if (u32(zip, local) !== 0x04034b50) throw new ZipError('Corrupt ZIP entry');
    const start = local + 30 + u16(zip, local + 26) + u16(zip, local + 28);
    const raw = zip.subarray(start, start + compSize);
    if (method === 0) return { name, data: Buffer.from(raw) };
    if (method !== 8) throw new ZipError('Unsupported ZIP compression');
    try { return { name, data: zlib.inflateRawSync(raw, { maxOutputLength: maxBytes }) }; } catch { throw new ZipError('The ZIP entry could not be decompressed within the size limit'); }
  }
  throw new ZipError('No .txt chat file found inside the ZIP');
}
