from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_BASE_URL = "https://api.zigcore.com.br/integration"


class ZigApiError(RuntimeError):
    """Erro retornado pela API Zig."""


@dataclass
class ZigClient:
    token: str
    base_url: str = DEFAULT_BASE_URL
    timeout: int = 60

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.token:
            raise ValueError("ZIG_API_TOKEN nao informado")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json,
            timeout=self.timeout,
        )
        if not response.ok:
            body = response.text[:1000]
            raise ZigApiError(
                f"{method.upper()} {url} falhou com HTTP {response.status_code}: {body}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ZigApiError(f"Resposta nao esta em JSON: {response.text[:1000]}") from exc

    def listar_lojas(self, rede: str) -> list[dict[str, Any]]:
        if not rede:
            raise ValueError("ZIG_REDE nao informado")
        data = self.request("GET", "/erp/lojas", params={"rede": rede})
        return data if isinstance(data, list) else []

    def cardapio(self, loja_id: str) -> list[dict[str, Any]]:
        if not loja_id:
            raise ValueError("loja_id nao informado")
        data = self.request("GET", "/erp/menuProducts", params={"loja": loja_id})
        return data if isinstance(data, list) else []
