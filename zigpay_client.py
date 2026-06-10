"""
ZigPay / ZigCore API Client
============================
Cliente Python para a API de integração ZigCore.
Documentação: https://api.zigcore.com.br/integration

Uso:
    from zigpay_client import ZigPayClient

    client = ZigPayClient(token="SEU_TOKEN")
    lojas = client.get_lojas(rede="SUA_REDE")
"""

import logging
import os
from datetime import date, datetime
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ZigPayClient")


# ─── Exceções customizadas ─────────────────────────────────────────────────────
class ZigPayError(Exception):
    """Erro genérico da API ZigPay."""


class ZigPayAuthError(ZigPayError):
    """Token inválido ou sem permissão."""


class ZigPayNotFoundError(ZigPayError):
    """Recurso não encontrado."""


class ZigPayRateLimitError(ZigPayError):
    """Limite de requisições atingido."""


# ─── Cliente ───────────────────────────────────────────────────────────────────
class ZigPayClient:
    """
    Cliente completo para a API de integração ZigCore/ZigPay.

    Parâmetros
    ----------
    token : str
        Token de integração (Authorization header).
        Pode ser passado direto ou via variável de ambiente ZIGPAY_TOKEN.
    base_url : str, opcional
        URL base. Padrão: produção (https://api.zigcore.com.br/integration).
    timeout : int, opcional
        Timeout em segundos por requisição (padrão: 30).
    max_retries : int, opcional
        Número de tentativas automáticas em caso de erro de rede (padrão: 3).
    """

    BASE_URL_PROD = "https://api.zigcore.com.br/integration"
    BASE_URL_DEV  = "https://api-develop.zigpay.dev"

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.token = token or os.environ.get("ZIGPAY_TOKEN")
        if not self.token:
            raise ZigPayAuthError(
                "Token não informado. Passe via parâmetro 'token' "
                "ou defina a variável de ambiente ZIGPAY_TOKEN."
            )

        self.base_url = (base_url or self.BASE_URL_PROD).rstrip("/")
        self.timeout  = timeout

        # Session com retry automático
        self.session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # ── Helpers internos ────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: Optional[dict] = None) -> list | dict:
        url = f"{self.base_url}{path}"
        logger.debug("GET %s | params=%s", url, params)
        response = self.session.get(url, headers=self._headers, params=params, timeout=self.timeout)
        return self._handle(response)

    def _post(self, path: str, body: dict) -> list | dict | None:
        url = f"{self.base_url}{path}"
        logger.debug("POST %s | body=%s", url, body)
        response = self.session.post(url, headers=self._headers, json=body, timeout=self.timeout)
        return self._handle(response)

    @staticmethod
    def _handle(response: requests.Response) -> list | dict | None:
        if response.status_code == 200:
            if response.content:
                return response.json()
            return None
        if response.status_code == 401:
            raise ZigPayAuthError("Token inválido ou sem permissão (401).")
        if response.status_code == 404:
            raise ZigPayNotFoundError(f"Recurso não encontrado (404): {response.url}")
        if response.status_code == 429:
            raise ZigPayRateLimitError("Limite de requisições atingido (429). Aguarde e tente novamente.")
        # Outros erros
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise ZigPayError(f"Erro HTTP {response.status_code}: {detail}")

    @staticmethod
    def _fmt(d: date | str | None) -> Optional[str]:
        """Converte date/datetime para string YYYY-MM-DD."""
        if d is None:
            return None
        if isinstance(d, (date, datetime)):
            return d.strftime("%Y-%m-%d")
        return str(d)

    # ── 1. Lojas ────────────────────────────────────────────────────────────────

    def get_lojas(self, rede: str) -> list:
        """
        Retorna a lista de lojas da rede.

        Parâmetros
        ----------
        rede : str  — Identificador da rede.

        Retorna
        -------
        list de {"id": str, "name": str}
        """
        logger.info("Buscando lojas da rede '%s'...", rede)
        return self._get("/erp/lojas", {"rede": rede})

    # ── 2. Saída de Produtos ────────────────────────────────────────────────────

    def get_saida_produtos(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
        refunded: Optional[bool] = None,
        product_sku: Optional[str] = None,
    ) -> list:
        """
        Produtos vendidos em um intervalo de tempo.

        Parâmetros
        ----------
        loja       : str  — ID da loja.
        dtinicio   : str/date — Data início (YYYY-MM-DD).
        dtfim      : str/date — Data fim (YYYY-MM-DD).
        refunded   : bool, opcional — True=somente cancelados; False/None=não cancelados.
        product_sku: str, opcional — Filtrar por SKU.
        """
        logger.info("Buscando saída de produtos | loja=%s de %s a %s", loja, dtinicio, dtfim)
        params = {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        }
        if refunded is not None:
            params["refunded"] = str(refunded).lower()
        if product_sku:
            params["productSku"] = product_sku
        return self._get("/erp/saida-produtos", params)

    # ── 3. Compradores ──────────────────────────────────────────────────────────

    def get_compradores(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
        transaction_id: Optional[str] = None,
    ) -> list:
        """Compradores em um intervalo de tempo."""
        logger.info("Buscando compradores | loja=%s de %s a %s", loja, dtinicio, dtfim)
        params = {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        }
        if transaction_id:
            params["transactionId"] = transaction_id
        return self._get("/erp/compradores", params)

    # ── 4. Faturamento ──────────────────────────────────────────────────────────

    def get_faturamento(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """
        Faturamento da loja por período.

        Retorna lista de entradas com paymentId, paymentName, value (centavos),
        redeId, lojaId, eventId, eventDate.
        """
        logger.info("Buscando faturamento | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/faturamento", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 5. Faturamento — Máquinas Integradas ────────────────────────────────────

    def get_faturamento_maquina(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Detalhes de faturamento para máquinas de pagamento integradas."""
        logger.info("Buscando faturamento maquina | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/faturamento/detalhesMaquinaIntegrada", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 6. Notas Fiscais (lista) ─────────────────────────────────────────────────

    def get_notas_fiscais(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
        page: Optional[int] = None,
    ) -> list:
        """Notas fiscais emitidas no período."""
        logger.info("Buscando notas fiscais | loja=%s de %s a %s", loja, dtinicio, dtfim)
        params = {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        }
        if page is not None:
            params["page"] = page
        return self._get("/erp/invoice", params)

    # ── 7. Nota Fiscal (detalhe) ─────────────────────────────────────────────────

    def get_nota_fiscal(self, invoice_id: str) -> dict:
        """Detalhes de uma nota fiscal específica."""
        logger.info("Buscando nota fiscal id=%s", invoice_id)
        return self._get(f"/erp/invoices/{invoice_id}")

    # ── 8. Check-ins ─────────────────────────────────────────────────────────────

    def get_checkins(
        self,
        loja: str,
        desde: str | date,
        dtfim: Optional[str | date] = None,
        page: Optional[int] = None,
    ) -> list:
        """Check-ins realizados na loja."""
        logger.info("Buscando check-ins | loja=%s desde %s", loja, desde)
        params = {"loja": loja, "desde": self._fmt(desde)}
        if dtfim:
            params["dtfim"] = self._fmt(dtfim)
        if page is not None:
            params["page"] = page
        return self._get("/erp/checkins", params)

    # ── 9. Recargas ───────────────────────────────────────────────────────────────

    def get_recargas(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Recargas / pré-pagamentos no período."""
        logger.info("Buscando recargas | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/recharges", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 10. Criar Bônus ───────────────────────────────────────────────────────────

    def criar_bonus(
        self,
        document: str,
        document_type: str,
        username: str,
        value: int,
        cashback_id: str,
        obs: Optional[str] = None,
    ) -> None:
        """
        Cria um bônus de cashback para o usuário.

        Parâmetros
        ----------
        document      : str  — CPF, RG ou Telefone.
        document_type : str  — "CPF", "RG" ou "Telefone".
        username      : str  — Nome do usuário.
        value         : int  — Valor em centavos (ex: 1000 = R$10,00).
        cashback_id   : str  — UUID único para identificar o bônus.
        obs           : str, opcional — Observações.
        """
        logger.info("Criando bônus | document=%s value=%d centavos", document, value)
        body = {
            "document": document,
            "documentType": document_type,
            "username": username,
            "value": value,
            "cashbackId": cashback_id,
        }
        if obs:
            body["obs"] = obs
        return self._post("/cashback/give", body)

    # ── 11. Remover Bônus ─────────────────────────────────────────────────────────

    def remover_bonus(self, cashback_id: str) -> None:
        """Remove um bônus existente pelo cashbackId."""
        logger.info("Removendo bônus cashbackId=%s", cashback_id)
        return self._post("/cashback/remove", {"cashbackId": cashback_id})

    # ── 12. Listar Bônus do Place ─────────────────────────────────────────────────

    def get_bonus(self, place_id: str) -> list:
        """Bônus disponíveis para um place/loja."""
        logger.info("Buscando bônus | placeId=%s", place_id)
        return self._get("/cashback", {"placeId": place_id})

    # ── 13. Detalhe de um Bônus ───────────────────────────────────────────────────

    def get_bonus_detalhe(self, cashback_id: str) -> dict:
        """Detalhes de um bônus específico."""
        logger.info("Buscando detalhe do bônus id=%s", cashback_id)
        return self._get(f"/cashback/{cashback_id}")

    # ── 14. Extrato (Flow) ────────────────────────────────────────────────────────

    def get_extrato(
        self,
        loja: str,
        since: str | date,
        until: str | date,
    ) -> list:
        """Fluxo do extrato da loja. Para datas anteriores a 2025-08-06."""
        logger.info("Buscando extrato | loja=%s de %s a %s", loja, since, until)
        return self._get("/erp/extractFlow", {
            "loja": loja,
            "since": self._fmt(since),
            "until": self._fmt(until),
        })

    # ── 15. Estornos ──────────────────────────────────────────────────────────────

    def get_estornos(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Estornos realizados no período."""
        logger.info("Buscando estornos | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/refunds", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 16. Cardápio ──────────────────────────────────────────────────────────────

    def get_cardapio(self, loja: str) -> list:
        """Cardápio de produtos da loja."""
        logger.info("Buscando cardápio | loja=%s", loja)
        return self._get("/erp/menuProducts", {"loja": loja})

    # ── 17. Gorjetas ──────────────────────────────────────────────────────────────

    def get_gorjetas(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Gorjetas registradas por transação no período."""
        logger.info("Buscando gorjetas | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/gorjeta", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 18. Transações de Check-in de Usuário ─────────────────────────────────────

    def get_checkin_transacoes(
        self,
        user_id: str,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Transações e produtos de um usuário específico via check-in."""
        logger.info("Buscando transações do usuário %s | loja=%s", user_id, loja)
        return self._get(f"/erp/checkins/{user_id}", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 19. Pagamentos de Check-in de Usuário ─────────────────────────────────────

    def get_checkin_pagamentos(
        self,
        user_id: str,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Pagamentos realizados por um usuário específico."""
        logger.info("Buscando pagamentos do usuário %s | loja=%s", user_id, loja)
        return self._get(f"/erp/checkins/{user_id}/payments", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 20. Estornos de Check-in de Usuário ───────────────────────────────────────

    def get_checkin_estornos(
        self,
        user_id: str,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Estornos de transações de um usuário específico."""
        logger.info("Buscando estornos do usuário %s | loja=%s", user_id, loja)
        return self._get(f"/erp/checkins/{user_id}/refunds", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 21. Mesas ─────────────────────────────────────────────────────────────────

    def get_mesas(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Mesas abertas e fechadas no período."""
        logger.info("Buscando mesas | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/tables", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 22. Extrato Financeiro ────────────────────────────────────────────────────

    def get_extrato_financeiro(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Extrato financeiro completo da loja."""
        logger.info("Buscando extrato financeiro | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/financialExtract", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 23. NPS ───────────────────────────────────────────────────────────────────

    def get_nps(
        self,
        loja: str,
        since: str | date,
        until: str | date,
    ) -> list:
        """Respostas NPS dos clientes."""
        logger.info("Buscando NPS | loja=%s de %s a %s", loja, since, until)
        return self._get("/erp/getNpsCustomerAnswers", {
            "loja": loja,
            "since": self._fmt(since),
            "until": self._fmt(until),
        })

    # ── 24. Extrato Flow V2 ───────────────────────────────────────────────────────

    def get_extrato_v2(
        self,
        loja: str,
        since: str | date,
        until: str | date,
    ) -> list:
        """
        Fluxo do extrato V2 com categorias detalhadas.
        ⚠️ Funciona apenas para datas a partir de 2025-08-06.
        """
        logger.info("Buscando extrato V2 | loja=%s de %s a %s", loja, since, until)
        return self._get("/erp/extractFlowV2", {
            "loja": loja,
            "since": self._fmt(since),
            "until": self._fmt(until),
        })

    # ── 25. Descontos por Funcionário ─────────────────────────────────────────────

    def get_descontos(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Descontos aplicados por funcionário no período."""
        logger.info("Buscando descontos | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/discounts", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })

    # ── 26. Transações de Adquirente ──────────────────────────────────────────────

    def get_transacoes_adquirente(
        self,
        loja: str,
        dtinicio: str | date,
        dtfim: str | date,
    ) -> list:
        """Transações de maquininha integrada com NSU e código de autorização."""
        logger.info("Buscando transações adquirente | loja=%s de %s a %s", loja, dtinicio, dtfim)
        return self._get("/erp/acquirerTransactions", {
            "loja": loja,
            "dtinicio": self._fmt(dtinicio),
            "dtfim": self._fmt(dtfim),
        })
