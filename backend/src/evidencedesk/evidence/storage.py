import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from evidencedesk.config import get_settings


class PrivateStorage:
    def __init__(self, root: Path | None = None):
        self.root = (root or get_settings().storage_root).resolve()
        if os.name == "nt" and not str(self.root).startswith("\\\\?\\"):
            value = str(self.root)
            self.root = Path(
                "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
            )
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_./-]{1,500}", key) or ".." in key or key.startswith("/"):
            raise ValueError("Chave de objeto inválida")
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Objeto fora do armazenamento privado")
        return target

    def put(self, key: str, content: bytes) -> str:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = hashlib.sha256(content).hexdigest()
        if target.exists():
            if self.checksum(key) != expected:
                raise ValueError("Objeto imutável já existe com conteúdo diferente")
            return expected
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Link publishes a complete file atomically without replacing a winner.
            # Both NTFS and the container volume support same-filesystem hard links.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if self.checksum(key) != expected:
                    raise ValueError("Objeto imutável já existe com conteúdo diferente") from None
        finally:
            temporary.unlink(missing_ok=True)
        if self.checksum(key) != expected:
            raise OSError("Checksum do objeto gravado não corresponde")
        return expected

    def checksum(self, key: str) -> str:
        with self.path(key).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
