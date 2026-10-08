import zlib from 'node:zlib';

/** Builds a real ZIP (deflate or stored) in memory so the reader is tested against the format, not against itself. */
export function makeZip(entries: { name: string; data: Buffer; deflate?: boolean; claimSize?: number; flags?: number }[]): Buffer {
  const locals: Buffer[] = [], central: Buffer[] = [];
  let offset = 0;
  for (const e of entries) {
    const comp = e.deflate === false ? e.data : zlib.deflateRawSync(e.data);
    const name = Buffer.from(e.name);
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(e.flags ?? 0, 6); lh.writeUInt16LE(e.deflate === false ? 0 : 8, 8);
    lh.writeUInt32LE(comp.length, 18); lh.writeUInt32LE(e.claimSize ?? e.data.length, 22); lh.writeUInt16LE(name.length, 26);
    locals.push(lh, name, comp);
    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt16LE(e.flags ?? 0, 8); ch.writeUInt16LE(e.deflate === false ? 0 : 8, 10);
    ch.writeUInt32LE(comp.length, 20); ch.writeUInt32LE(e.claimSize ?? e.data.length, 24); ch.writeUInt16LE(name.length, 28); ch.writeUInt32LE(offset, 42);
    central.push(ch, name);
    offset += 30 + name.length + comp.length;
  }
  const cd = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, end]);
}
