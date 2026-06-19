from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from fastapi import HTTPException

from .store import SQLiteStore

PBKDF2_ITERATIONS = 210_000


class AuthService:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def register(self, username: str, password: str) -> str:
        if self.store.account_exists():
            raise HTTPException(status_code=400, detail="A local BreezePilot account already exists.")

        salt = base64.b64encode(os.urandom(16)).decode("ascii")
        password_hash = self._hash_password(password, salt)
        self.store.create_account(username.strip(), password_hash, salt)
        return self._issue_token(username.strip())

    def login(self, username: str, password: str) -> str:
        account = self.store.get_account()
        if account is None:
            raise HTTPException(status_code=400, detail="Create a local account first.")
        if account["username"] != username.strip():
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        expected = account["password_hash"]
        actual = self._hash_password(password, account["salt"])
        if not hmac.compare_digest(expected, actual):
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        return self._issue_token(account["username"])

    def logout(self, token: str | None) -> None:
        if token:
            self.store.delete_auth_token(self._token_hash(token))

    def authenticate_token(self, token: str | None) -> bool:
        if not token:
            return False
        return self.store.auth_token_exists(self._token_hash(token))

    def _issue_token(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        self.store.save_auth_token(self._token_hash(token), username)
        return token

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt.encode("ascii")),
            PBKDF2_ITERATIONS,
        )
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
