# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add only an ADB-authentication policy to a disposable SDK ramdisk copy.

Android first-stage init copies adb_debug.prop from a marked ramdisk into its
private debug-ramdisk directory. PropertyLoadBootDefaults loads that policy last.
The existing userdebug/root capability and original SDK system image are kept.
"""
from pathlib import Path
import hashlib
import json
import os
import stat
import struct
import gzip
import io



def decompress(data):
    """Read vendor gzip/newc/LZ4 ramdisks without an OS-specific CLI."""
    if data.startswith(b'070701'):return data
    if data.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            raw=stream.read((128<<20)+1)
        if len(raw)>128<<20:raise RuntimeError('Android ramdisk exceeds its bound.')
        return raw
    import lz4.block
    import lz4.frame
    output=bytearray();offset=0
    while offset<len(data):
        magic=data[offset:offset+4]
        if magic==b'\x02\x21\x4c\x18':
            offset+=4
            while offset<len(data):
                if data[offset:offset+4] in (b'\x02\x21\x4c\x18',b'\x04\x22\x4d\x18'):break
                if len(data)-offset<4:raise RuntimeError('Truncated Android LZ4 block.')
                size=struct.unpack_from('<I',data,offset)[0];offset+=4
                if size==0:break
                if size>(8<<20)+65536 or size>len(data)-offset:raise RuntimeError('Invalid Android LZ4 block size.')
                output.extend(lz4.block.decompress(data[offset:offset+size],uncompressed_size=8<<20));offset+=size
                if len(output)>128<<20:raise RuntimeError('Android ramdisk exceeds its bound.')
        elif magic==b'\x04\x22\x4d\x18':
            decoder=lz4.frame.LZ4FrameDecompressor()
            output.extend(decoder.decompress(data[offset:],max_length=(128<<20)+1-len(output)))
            if not decoder.eof:raise RuntimeError('Android LZ4 frame is truncated or too large.')
            offset=len(data)-len(decoder.unused_data or b'')
        else:raise RuntimeError('Unsupported Android ramdisk compression.')
    return bytes(output)


def parse(raw, offset=0):
    records = []
    while True:
        header = raw[offset:offset + 110]
        if len(header) != 110 or header[:6] != b"070701":
            raise RuntimeError("Unsupported/truncated newc ramdisk record")
        values = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        size, name_size = values[6], values[11]
        name = raw[offset + 110:offset + 110 + name_size]
        if not name.endswith(b"\0") or size > len(raw):
            raise RuntimeError("Invalid newc ramdisk record")
        start = (offset + 110 + name_size + 3) & ~3
        data = raw[start:start + size]
        if len(data) != size:
            raise RuntimeError("Truncated ramdisk data")
        records.append((name[:-1].decode(), values, data))
        offset = (start + size + 3) & ~3
        if records[-1][0] == "TRAILER!!!":
            return records, offset


def archives(raw):
    result, offset = [], 0
    while offset < len(raw):
        while offset < len(raw) and raw[offset] == 0:
            offset += 1
        if offset == len(raw):
            break
        records, offset = parse(raw, offset)
        result.append(records)
    return result


def encode(records):
    raw = bytearray()
    for name, values, data in records:
        name = name.encode() + b"\0"
        values = list(values)
        values[6], values[11] = len(data), len(name)
        raw.extend(b"070701" + b"".join(f"{x:08x}".encode() for x in values))
        raw.extend(name)
        raw.extend(b"\0" * (-len(raw) % 4))
        raw.extend(data)
        raw.extend(b"\0" * (-len(raw) % 4))
    raw.extend(b"\0" * (-len(raw) % 512))
    return bytes(raw)


def build(source, destination):
    SOURCE, DEST = Path(source), Path(destination)
    os.umask(0o077)
    DEST.mkdir(parents=True, exist_ok=True)
    original = decompress(SOURCE.read_bytes())
    original_archives = archives(original)
    names = {name for records in original_archives for name, _, _ in records}
    if {"force_debuggable", "adb_debug.prop"} & names:
        raise RuntimeError("The source already contains a debug policy; refusing to replace it.")
    # New regular root-owned mode0644 entries; preserve every original record.
    def record(name, data, ino):
        return name, [ino, stat.S_IFREG | 0o644, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name) + 1, 0], data
    added = [record("force_debuggable", b"", 100000),
             record("adb_debug.prop", b"ro.adb.secure=1\n", 100001),
             record("TRAILER!!!", b"", 100002)]
    # Android SDK ramdisks contain concatenated archives, including drivers
    # after the first trailer. Keep ALL source bytes, including their padding.
    cpio = original + encode(added)
    decoded = archives(cpio)
    assert cpio[:len(original)] == original
    assert decoded == original_archives + [added]
    image = DEST / "ramdisk-adb-auth.img"
    # Linux initramfs accepts uncompressed newc directly. Keep the whole
    # original uncompressed archive stream, then the small auth policy.
    image.write_bytes(cpio)
    assert archives(decompress(image.read_bytes())) == original_archives + [added]
    report = {"source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "derived_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
              "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "original_records_preserved": True,
              "original_uncompressed_bytes_preserved": True,
              "original_archive_count": len(original_archives),
              "added_files": {"force_debuggable": "empty marker", "adb_debug.prop": "ro.adb.secure=1"},
              "original_sdk_files_modified": False, "compression": "uncompressed-newc", "runtime_acceptance_complete": False}
    (DEST / "policy.json").write_text(json.dumps(report, indent=2) + "\n")
    (DEST / "builder.py").write_bytes(Path(__file__).read_bytes())
    return {**report, "path": str(image.resolve())}
