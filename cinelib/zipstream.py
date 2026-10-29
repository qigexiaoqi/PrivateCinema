"""Streaming ZIP writer (stdlib only).

Needed because a download bundle can contain a multi-gigabyte film: we cannot
buffer it in memory or on disk, so entries are streamed to the socket.  Video
entries are STORED (no recompression); text/sidecar entries are DEFLATEd.
ZIP64 records are emitted automatically for large entries.
"""
from __future__ import annotations

import struct
import zlib
from datetime import datetime

_LOCAL = struct.Struct("<IHHHHHIIIHH")
_CENTRAL = struct.Struct("<IHHHHHHIIIHHHHHII")
_DESC = struct.Struct("<IIII")
_DESC64 = struct.Struct("<IIQQ")
_LIMIT = 0xFFFFFFFF


def _dos_time(dt: datetime) -> tuple[int, int]:
    dt = dt or datetime.now()
    year = max(1980, min(dt.year, 2107))
    dtime = (dt.hour << 11) | (dt.minute << 5) | (dt.second // 2)
    ddate = ((year - 1980) << 9) | (dt.month << 5) | dt.day
    return dtime, ddate


class ZipStream:
    def __init__(self, out):
        self.out = out
        self.entries: list[dict] = []
        self.offset = 0
        self._closed = False

    # ---------------------------------------------------------------- utils
    def _w(self, data: bytes) -> None:
        self.out.write(data)
        self.offset += len(data)

    def _entry(self, name: str) -> tuple[bytes, int, int]:
        name_b = name.replace("\\", "/").encode("utf-8")
        dt, dd = _dos_time(datetime.now())
        return name_b, dt, dd

    # ------------------------------------------------------------ add entry
    def add_bytes(self, name: str, data: bytes, compress: bool = True) -> None:
        name_b, dtime, ddate = self._entry(name)
        crc = zlib.crc32(data) & 0xFFFFFFFF
        method = zlib.DEFLATED if compress else 0
        payload = zlib.compressobj(6, zlib.DEFLATED, -15)
        packed = payload.compress(data) + payload.flush() if compress else data
        if len(packed) >= len(data):
            packed, method = data, 0
        csize, usize = len(packed), len(data)
        zip64 = usize >= _LIMIT or csize >= _LIMIT
        extra = b""
        if zip64:
            extra = struct.pack("<HHQQ", 0x0001, 16, usize, csize)
        flags = 0x0800
        version = 45 if zip64 else 20
        header_off = self.offset
        self._w(_LOCAL.pack(0x04034B50, version, flags, method, dtime, ddate, crc,
                            0xFFFFFFFF if zip64 else csize,
                            0xFFFFFFFF if zip64 else usize,
                            len(name_b), len(extra)))
        self._w(name_b + extra + packed)
        self.entries.append(dict(name=name_b, method=method, crc=crc, csize=csize,
                                 usize=usize, dtime=dtime, ddate=ddate,
                                 offset=header_off, version=version))

    def add_precompressed(self, name: str, crc: int, method: int, packed: bytes,
                          usize: int) -> None:
        """Add an entry whose deflate payload and CRC were computed up-front.

        Needed when the caller must know the exact archive size before streaming
        (so Content-Length can be sent and the browser shows progress).
        """
        name_b, dtime, ddate = self._entry(name)
        zip64 = usize >= _LIMIT or len(packed) >= _LIMIT
        extra = b""
        if zip64:
            extra = struct.pack("<HHQQ", 0x0001, 16, usize, len(packed))
        version = 45 if zip64 else 20
        header_off = self.offset
        self._w(_LOCAL.pack(0x04034B50, version, 0x0800, method, dtime, ddate, crc,
                            0xFFFFFFFF if zip64 else len(packed),
                            0xFFFFFFFF if zip64 else usize,
                            len(name_b), len(extra)))
        self._w(name_b + extra + packed)
        self.entries.append(dict(name=name_b, method=method, crc=crc,
                                 csize=len(packed), usize=usize, dtime=dtime,
                                 ddate=ddate, offset=header_off,
                                 version=version))

    def add_stream(self, name: str, size: int, chunks, compress: bool = False,
                   on_bytes=None) -> None:
        """Stream an entry of known size whose CRC is only known at the end."""
        name_b, dtime, ddate = self._entry(name)
        zip64 = size >= _LIMIT
        method = 0
        flags = 0x0008 | 0x0800
        version = 45 if zip64 else 20
        extra = b""
        if zip64:
            extra = struct.pack("<HHQQ", 0x0001, 16, size, size)
        header_off = self.offset
        self._w(_LOCAL.pack(0x04034B50, version, flags, method, dtime, ddate, 0,
                            0xFFFFFFFF if zip64 else 0,
                            0xFFFFFFFF if zip64 else 0,
                            len(name_b), len(extra)))
        self._w(name_b + extra)
        crc = 0
        written = 0
        for chunk in chunks:
            if not chunk:
                continue
            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
            written += len(chunk)
            self._w(chunk)
            if on_bytes:
                on_bytes(len(chunk))
        crc_done = crc
        if zip64:
            self._w(_DESC64.pack(0x08074B50, crc_done, written, written))
        else:
            self._w(_DESC.pack(0x08074B50, crc_done, written, written))
        self.entries.append(dict(name=name_b, method=method, crc=crc_done, csize=written,
                                 usize=written, dtime=dtime, ddate=ddate,
                                 offset=header_off, version=version))

    # --------------------------------------------------------------- finish
    def close(self) -> None:
        if self._closed:
            return
        cd_start = self.offset
        for e in self.entries:
            name_b = e["name"]
            zip64 = e["usize"] >= _LIMIT or e["csize"] >= _LIMIT or e["offset"] >= _LIMIT
            extra = b""
            csize = e["csize"]
            usize = e["usize"]
            offset = e["offset"]
            if zip64:
                parts = []
                extra_len = 0
                if usize >= _LIMIT:
                    parts.append(struct.pack("<Q", usize)); extra_len += 8
                if csize >= _LIMIT:
                    parts.append(struct.pack("<Q", csize)); extra_len += 8
                if offset >= _LIMIT:
                    parts.append(struct.pack("<Q", offset)); extra_len += 8
                extra = struct.pack("<HH", 0x0001, extra_len) + b"".join(parts)
                csize = usize = offset = _LIMIT
            flags = 0x0800 | (0x0008 if not zip64 else 0)
            self._w(_CENTRAL.pack(0x02014B50, 0x031E, 45 if zip64 else 20, flags,
                                  e["method"], e["dtime"], e["ddate"], e["crc"],
                                  csize, usize, len(name_b), len(extra), 0, 0, 0,
                                  0, offset))
            self._w(name_b + extra)
        cd_size = self.offset - cd_start
        count = len(self.entries)
        zip64_eocd = count >= 0xFFFF or cd_start >= _LIMIT or cd_size >= _LIMIT
        if zip64_eocd:
            eocd64_off = self.offset
            self._w(struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 0x031E, 45, 0, 0,
                                count, count, cd_size, cd_start))
            self._w(struct.pack("<IIQI", 0x07064B50, 0, eocd64_off, 1))
        self._w(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0,
                            min(count, 0xFFFF), min(count, 0xFFFF),
                            min(cd_size, _LIMIT), min(cd_start, _LIMIT), 0))
        self._closed = True
