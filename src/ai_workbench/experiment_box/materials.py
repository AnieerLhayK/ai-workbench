"""Explicit, bounded attachments. No directory walking or URL crawling."""
import http.client
import ipaddress
from pathlib import Path
import socket
import ssl
from urllib.parse import urlsplit

from PySide6.QtGui import QImageReader

from .model import StoreError

TEXT = {".txt", ".md", ".json", ".csv", ".py", ".ps1", ".toml", ".yaml", ".yml", ".log"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}


def public_link(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise StoreError("资料链接仅支持公开 HTTPS 标准端口")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise StoreError("资料链接不能访问本机、内网或保留地址")
    address = addresses[0][4][0]
    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((address, 443), timeout=10)
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
    connection = PinnedHTTPS(parsed.hostname, timeout=10)
    try:
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request("GET", target, headers={"User-Agent": "ExperimentBox/1", "Accept": "text/plain,text/html,application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise StoreError("链接未返回可读取资料；不跟随重定向")
        media = response.getheader("Content-Type", "").split(";")[0]
        if media not in ("text/plain", "text/html", "text/markdown", "application/json"):
            raise StoreError("链接格式不支持；首版只解析文本与截图")
        data = response.read(200_001)
        if len(data) > 200_000:
            raise StoreError("链接资料超过 200 KB")
        return data.decode("utf-8")
    finally:
        connection.close()


def prepare(materials, directory):
    if len(materials) > 5:
        raise StoreError("每轮最多附加 5 项资料")
    texts, images = [], []
    total = 0
    for index, material in enumerate(materials):
        if material["type"] == "link":
            text = public_link(material["value"])
            texts.append(dict(source=material["value"], text=text))
            total += len(text.encode("utf-8"))
        elif material["type"] == "file":
            path = Path(material["value"])
            limit = 8_000_000 if path.suffix.lower() in IMAGES else 200_000
            if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
                raise StoreError("附加文件缺失、为链接或超过大小限制")
            if path.suffix.lower() in TEXT:
                with path.open("rb") as stream:
                    data = stream.read(200_001)
                if len(data) > 200_000:
                    raise StoreError("文本超过 200 KB")
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeError as error:
                    raise StoreError("文本不是 UTF-8，请转换后附加") from error
                total += len(text.encode("utf-8"))
                texts.append(dict(source=path.name, text=text))
            elif path.suffix.lower() in IMAGES:
                reader = QImageReader(str(path))
                size = reader.size()
                if not size.isValid() or size.width() * size.height() > 16_000_000:
                    raise StoreError("截图无效或超过 1600 万像素")
                image = reader.read()
                target = directory / f"attachment-{index}.png"
                if image.isNull() or not image.save(str(target), "PNG"):
                    raise StoreError("截图无法解析")
                images.append(str(target))
                texts.append(dict(source=path.name, text="本轮明确附加的截图"))
            else:
                raise StoreError("此格式尚不支持；请附加 UTF-8 文本或截图")
        else:
            raise StoreError("未知资料类型")
        if total > 500_000:
            raise StoreError("本轮文本资料超过 500 KB")
    return texts, images
