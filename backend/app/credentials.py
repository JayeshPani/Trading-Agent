from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from .config import AppConfig
from .store import SQLiteStore


class CredentialService:
    def __init__(self, config: AppConfig, store: SQLiteStore):
        self.config = config
        self.store = store
        self._fernet = Fernet(self._load_or_create_key())

    def save_breeze_credentials(self, app_key: str, secret_key: str) -> None:
        app_key_encrypted = self._encrypt(app_key.strip())
        secret_key_encrypted = self._encrypt(secret_key.strip())
        self.store.save_breeze_credentials(app_key_encrypted, secret_key_encrypted)

    def breeze_credentials_saved(self) -> bool:
        return self.store.breeze_credentials_saved() or self._env_credentials_saved()

    def get_breeze_credentials(self) -> tuple[str | None, str | None]:
        stored = self.store.get_breeze_credentials()
        if stored is None:
            return self.config.breeze_app_key, self.config.breeze_secret_key

        try:
            return self._decrypt(stored[0]), self._decrypt(stored[1])
        except InvalidToken as exc:
            raise HTTPException(status_code=500, detail="Stored Breeze credentials cannot be decrypted.") from exc

    def delete_breeze_credentials(self) -> None:
        self.store.delete_breeze_credentials()

    def _env_credentials_saved(self) -> bool:
        return bool(self.config.breeze_app_key and self.config.breeze_secret_key)

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")

    def _load_or_create_key(self) -> bytes:
        key_path = Path(self.config.encryption_key_path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            return key_path.read_bytes().strip()

        key = Fernet.generate_key()
        key_path.write_bytes(key)
        return key
