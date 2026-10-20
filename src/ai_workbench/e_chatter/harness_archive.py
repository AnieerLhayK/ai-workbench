"""Read bounded named metadata from the installed official Electron archive."""
import json
import struct

from .files import ChatterError


def read_file(path, name):
    try:
        with path.open("rb") as stream:
            size = struct.unpack("<I", stream.read(8)[4:])[0]
            if size > 16 * 1024 * 1024:
                raise ValueError()
            raw = stream.read(size)
            header = json.loads(raw[8:8 + struct.unpack("<I", raw[4:8])[0]])
            for part in name.split("/"):
                header = header["files"][part]
            if int(header["size"]) > 2 * 1024 * 1024 or "link" in header or header.get("unpacked"):
                raise ValueError()
            stream.seek(8 + size + int(header["offset"]))
            return stream.read(int(header["size"])).decode("utf-8")
    except (OSError, KeyError, ValueError, struct.error) as error:
        raise ChatterError("无法读取官方 Harness 运行时元数据") from error
