from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

import requests

from .config import AppConfig
from .instruments import InstrumentMapper
from .rate_limit import RateLimiter
from .schemas import (
    BrokerCandle,
    BrokerFunds,
    BrokerHolding,
    BrokerOrder,
    BrokerPosition,
    BrokerQuote,
    BrokerTrade,
    is_equity_symbol,
    normalize_symbol,
)
from .time_utils import next_session_expiry, now_utc

DEFAULT_EXCHANGE_CODE = "NSE"
DEFAULT_PRODUCT_TYPE = "cash"


RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
READ_RETRY_ATTEMPTS = 2
MAX_RETRY_DELAY_SECONDS = 5.0


class BreezeClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class BreezeRecoveryNotice:
    endpoint: str
    message: str


@dataclass(frozen=True)
class BreezeSession:
    session_token: str
    expires_at: str


class BreezeClient:
    def __init__(
        self,
        config: AppConfig,
        rate_limiter: RateLimiter,
        credential_provider: Callable[[], tuple[str | None, str | None]] | None = None,
    ):
        self.config = config
        self.rate_limiter = rate_limiter
        self.credential_provider = credential_provider
        self.instrument_mapper = InstrumentMapper(
            str(Path(config.database_path).with_name("security_master.csv"))
        )
        self._recovery_notices: list[BreezeRecoveryNotice] = []
        self._recovery_lock = threading.Lock()

    def validate_session(self, session_key: str) -> BreezeSession:
        app_key, secret_key = self._credentials()
        if not app_key or not secret_key:
            raise BreezeClientError("Breeze app key and secret key are required to validate a session.")

        self.rate_limiter.record_api_call()
        payload = {"SessionToken": session_key, "AppKey": app_key}
        try:
            response = requests.request(
                "GET",
                f"{self.config.breeze_base_url}/customerdetails",
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise BreezeClientError("Unable to reach Breeze while validating the session.") from exc

        if response.status_code >= 400:
            raise BreezeClientError(f"Breeze session validation failed with status {response.status_code}.")

        body = self._decode_response(response, "Breeze returned an invalid session validation response.")
        session_token = (body.get("Success") or {}).get("session_token")
        if not session_token:
            raise BreezeClientError("Breeze did not return a session token.")

        return BreezeSession(
            session_token=session_token,
            expires_at=next_session_expiry().isoformat(),
        )

    def get_quote(self, session_token: str, stock_code: str) -> BrokerQuote:
        stock = self._validate_stock(stock_code)
        breeze_stock = self.instrument_mapper.to_breeze(stock)
        raw = self._signed_request(
            "GET",
            "/quotes",
            {"stock_code": breeze_stock, "exchange_code": DEFAULT_EXCHANGE_CODE},
            session_token,
        )
        return map_quote(raw, stock)

    def get_quotes(self, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._signed_request("GET", "/quotes", payload, session_token)

    def get_historical_candles(
        self,
        session_token: str,
        *,
        stock_code: str,
        from_date: str,
        to_date: str,
        interval: str = "day",
    ) -> list[BrokerCandle]:
        stock = self._validate_stock(stock_code)
        breeze_stock = self.instrument_mapper.to_breeze(stock)
        raw = self._signed_request(
            "GET",
            "/historicalcharts",
            {
                "interval": interval,
                "from_date": from_date,
                "to_date": to_date,
                "stock_code": breeze_stock,
                "exchange_code": DEFAULT_EXCHANGE_CODE,
                "product_type": "Cash",
            },
            session_token,
        )
        return map_candles(raw, stock_code=stock, exchange_code=DEFAULT_EXCHANGE_CODE, interval=interval)

    def get_funds(self, session_token: str) -> BrokerFunds:
        raw = self._signed_request("GET", "/funds", {}, session_token)
        return map_funds(raw)

    def get_holdings(self, session_token: str) -> list[BrokerHolding]:
        start, end = _recent_broker_window()
        try:
            raw = self._signed_request(
                "GET",
                "/portfolioholdings",
                {
                    "exchange_code": DEFAULT_EXCHANGE_CODE,
                    "from_date": start,
                    "to_date": end,
                    "stock_code": "",
                    "portfolio_type": "",
                },
                session_token,
            )
        except BreezeClientError as exc:
            if _is_no_records_error(exc):
                return []
            raise
        return [
            item.model_copy(update={"stock_code": self.instrument_mapper.to_nse(item.stock_code)})
            for item in map_holdings(raw)
        ]

    def get_positions(self, session_token: str) -> list[BrokerPosition]:
        try:
            raw = self._signed_request("GET", "/portfoliopositions", {}, session_token)
        except BreezeClientError as exc:
            if _is_no_records_error(exc):
                return []
            raise
        return [
            item.model_copy(update={"stock_code": self.instrument_mapper.to_nse(item.stock_code)})
            for item in map_positions(raw)
        ]

    def place_order(self, session_token: str, payload: dict[str, Any]) -> BrokerOrder:
        stock = self._validate_stock(str(payload.get("stock_code") or payload.get("stockCode") or ""))
        safe_payload = self._cash_equity_payload(payload, require_static_ip=True, require_order_action=True)
        safe_payload["product"] = safe_payload.pop("product_type")
        raw = self._signed_request("POST", "/order", safe_payload, session_token)
        return map_order(raw, fallback_payload=safe_payload).model_copy(update={"stock_code": stock})

    def get_order_status(self, session_token: str, payload: dict[str, Any]) -> BrokerOrder:
        safe_payload = {
            "exchange_code": DEFAULT_EXCHANGE_CODE,
            "order_id": payload.get("order_id") or payload.get("orderId"),
        }
        raw = self._signed_request("GET", "/order", safe_payload, session_token)
        order = map_order(raw, fallback_payload=safe_payload)
        return order.model_copy(update={"stock_code": self.instrument_mapper.to_nse(order.stock_code)})

    def get_order_list(self, session_token: str) -> list[BrokerOrder]:
        start, end = _recent_broker_window()
        try:
            raw = self._signed_request(
                "GET",
                "/order",
                {
                    "exchange_code": DEFAULT_EXCHANGE_CODE,
                    "from_date": start,
                    "to_date": end,
                },
                session_token,
            )
        except BreezeClientError as exc:
            if _is_no_records_error(exc):
                return []
            raise
        return [
            order.model_copy(update={"stock_code": self.instrument_mapper.to_nse(order.stock_code)})
            for order in map_orders(raw)
        ]

    def cancel_order(self, session_token: str, payload: dict[str, Any]) -> BrokerOrder:
        self._require_static_ip()
        self.rate_limiter.record_order_action()
        safe_payload = {
            "exchange_code": DEFAULT_EXCHANGE_CODE,
            "order_id": payload.get("order_id") or payload.get("orderId"),
        }
        raw = self._signed_request("DELETE", "/order", safe_payload, session_token)
        return map_order(raw, fallback_payload=safe_payload)

    def modify_order(self, session_token: str, payload: dict[str, Any]) -> BrokerOrder:
        stock = self._validate_stock(str(payload.get("stock_code") or payload.get("stockCode") or ""))
        safe_payload = self._cash_equity_payload(payload, require_static_ip=True, require_order_action=True)
        raw = self._signed_request("PUT", "/order", safe_payload, session_token)
        return map_order(raw, fallback_payload=safe_payload).model_copy(update={"stock_code": stock})

    def get_trade_list(self, session_token: str, payload: dict[str, Any] | None = None) -> list[BrokerTrade]:
        start, end = _recent_broker_window()
        safe_payload = payload or {
            "from_date": start,
            "to_date": end,
            "exchange_code": DEFAULT_EXCHANGE_CODE,
            "product_type": "",
            "action": "",
            "stock_code": "",
        }
        try:
            raw = self._signed_request("GET", "/trades", safe_payload, session_token)
        except BreezeClientError as exc:
            if _is_no_records_error(exc):
                return []
            raise
        return [
            trade.model_copy(update={"stock_code": self.instrument_mapper.to_nse(trade.stock_code)})
            for trade in map_trades(raw)
        ]

    def square_off(self, session_token: str, payload: dict[str, Any]) -> BrokerOrder:
        stock = self._validate_stock(str(payload.get("stock_code") or payload.get("stockCode") or ""))
        safe_payload = self._cash_equity_payload(payload, require_static_ip=True, require_order_action=True)
        raw = self._signed_request("POST", "/squareoff", safe_payload, session_token)
        return map_order(raw, fallback_payload=safe_payload).model_copy(update={"stock_code": stock})

    def _signed_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        session_token: str,
    ) -> dict[str, Any]:
        app_key, secret_key = self._credentials()
        if not app_key or not secret_key:
            raise BreezeClientError("Breeze app key and secret key are required.")

        body = json.dumps(payload, separators=(",", ":"))
        attempts = READ_RETRY_ATTEMPTS if method.upper() == "GET" else 1
        last_error: BreezeClientError | None = None

        for attempt in range(attempts):
            self.rate_limiter.record_api_call()
            timestamp = (
                now_utc()
                .astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", ".000Z")
            )
            checksum = hashlib.sha256(
                f"{timestamp}{body}{secret_key}".encode("utf-8")
            ).hexdigest()
            try:
                response = requests.request(
                    method,
                    f"{self.config.breeze_base_url}{path}",
                    headers={
                        "Content-Type": "application/json",
                        "X-Checksum": f"token {checksum}",
                        "X-Timestamp": timestamp,
                        "X-AppKey": app_key,
                        "X-SessionToken": session_token,
                    },
                    data=body,
                    timeout=15,
                )
            except requests.RequestException as exc:
                last_error = BreezeClientError(
                    f"Breeze {method.upper()} {path} could not reach the broker.",
                    endpoint=path,
                    retryable=True,
                )
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise last_error from exc

            if response.status_code >= 400:
                retryable = response.status_code in RETRYABLE_STATUS_CODES
                last_error = BreezeClientError(
                    f"Breeze {method.upper()} {path} failed with status {response.status_code}.",
                    endpoint=path,
                    status_code=response.status_code,
                    retryable=retryable,
                )
                if retryable and attempt + 1 < attempts:
                    time.sleep(self._retry_delay(response, attempt))
                    continue
                raise last_error

            body_json = self._decode_response(response, "Breeze returned an invalid response.")
            if body_json.get("Error"):
                raise BreezeClientError(str(body_json["Error"]), endpoint=path)
            if attempt > 0:
                self._record_recovery(
                    path,
                    f"Breeze {method.upper()} {path} recovered after a temporary failure.",
                )
            return body_json

        raise last_error or BreezeClientError(
            f"Breeze {method.upper()} {path} failed.",
            endpoint=path,
        )

    def consume_recovery_notices(self) -> list[BreezeRecoveryNotice]:
        with self._recovery_lock:
            notices = list(self._recovery_notices)
            self._recovery_notices.clear()
        return notices

    def _record_recovery(self, endpoint: str, message: str) -> None:
        with self._recovery_lock:
            self._recovery_notices.append(
                BreezeRecoveryNotice(endpoint=endpoint, message=message)
            )

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        base_delay = 0.5 * (2**attempt)
        retry_after = getattr(response, "headers", {}).get("Retry-After")
        if not retry_after:
            return base_delay
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = max(
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                    0.0,
                )
            except (TypeError, ValueError, OverflowError):
                return base_delay
        return min(max(delay, base_delay), MAX_RETRY_DELAY_SECONDS)

    def has_credentials(self) -> bool:
        app_key, secret_key = self._credentials()
        return bool(app_key and secret_key)

    def _credentials(self) -> tuple[str | None, str | None]:
        if self.credential_provider is not None:
            return self.credential_provider()
        return self.config.breeze_app_key, self.config.breeze_secret_key

    def _cash_equity_payload(
        self,
        payload: dict[str, Any],
        *,
        require_static_ip: bool,
        require_order_action: bool,
    ) -> dict[str, Any]:
        stock = self._validate_stock(str(payload.get("stock_code") or payload.get("stockCode") or ""))
        exchange_code = str(payload.get("exchange_code") or payload.get("exchangeCode") or DEFAULT_EXCHANGE_CODE).upper()
        product_type = str(payload.get("product_type") or payload.get("productType") or DEFAULT_PRODUCT_TYPE).lower()
        order_type = str(payload.get("order_type") or payload.get("orderType") or "limit").lower()

        if exchange_code != DEFAULT_EXCHANGE_CODE:
            raise BreezeClientError("Only NSE cash-equity orders are allowed in BreezePilot.")
        if product_type != DEFAULT_PRODUCT_TYPE:
            raise BreezeClientError("Only cash equity product_type is allowed in BreezePilot.")
        if order_type == "market":
            raise BreezeClientError("Market orders are not permitted through BreezePilot.")
        if order_type not in {"limit", "stoploss"}:
            raise BreezeClientError("Only limit or stoploss orders are allowed through BreezePilot.")
        if require_static_ip:
            self._require_static_ip()
        if require_order_action:
            self.rate_limiter.record_order_action()

        safe_payload = dict(payload)
        safe_payload["stock_code"] = self.instrument_mapper.to_breeze(stock)
        safe_payload["exchange_code"] = DEFAULT_EXCHANGE_CODE
        safe_payload["product_type"] = DEFAULT_PRODUCT_TYPE
        safe_payload["order_type"] = order_type
        return safe_payload

    def _require_static_ip(self) -> None:
        if not self.config.static_ip_ready:
            raise BreezeClientError("Live order actions require deployment from the registered static IP.")

    @staticmethod
    def _validate_stock(stock_code: str) -> str:
        stock = normalize_symbol(stock_code)
        if not is_equity_symbol(stock):
            raise BreezeClientError("Only cash-equity stock symbols are allowed.")
        return stock

    @staticmethod
    def _decode_response(response: requests.Response, message: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise BreezeClientError(message) from exc
        if not isinstance(body, dict):
            raise BreezeClientError(message)
        return body


def map_quote(raw: dict[str, Any], fallback_stock_code: str) -> BrokerQuote:
    row = _first_success(raw)
    return BrokerQuote(
        stockCode=fallback_stock_code,
        exchangeCode=_text(_field(row, "exchange_code", "exchangeCode"), DEFAULT_EXCHANGE_CODE),
        lastPrice=_float(
            _field(row, "ltp", "last_trade_price", "lastPrice", "last_price", "last", "close"), 0
        ),
        open=_maybe_float(_field(row, "open", "OpenPrice")),
        high=_maybe_float(_field(row, "high", "HighPrice")),
        low=_maybe_float(_field(row, "low", "LowPrice")),
        close=_maybe_float(_field(row, "close", "ClosePrice", "previous_close")),
        volume=_maybe_float(_field(row, "volume", "ttq", "total_quantity_traded")),
        timestamp=_maybe_text(_field(row, "ltt", "last_traded_time", "timestamp", "datetime")),
    )


def map_candles(
    raw: dict[str, Any],
    *,
    stock_code: str,
    exchange_code: str,
    interval: str,
) -> list[BrokerCandle]:
    candles: list[BrokerCandle] = []
    for row in _success_rows(raw):
        candles.append(
            BrokerCandle(
                stockCode=stock_code,
                exchangeCode=_text(_field(row, "exchange_code", "exchangeCode"), exchange_code),
                interval=interval,
                datetime=_text(_field(row, "datetime", "date", "timestamp"), ""),
                open=_float(_field(row, "open"), 0),
                high=_float(_field(row, "high"), 0),
                low=_float(_field(row, "low"), 0),
                close=_float(_field(row, "close"), 0),
                volume=_maybe_float(_field(row, "volume")),
            )
        )
    return candles


def map_funds(raw: dict[str, Any]) -> BrokerFunds:
    row = _first_success(raw)
    return BrokerFunds(
        totalBankBalance=_maybe_float(_field(row, "total_bank_balance", "totalBankBalance")),
        allocatedEquity=_maybe_float(_field(row, "allocated_equity", "allocatedEquity")),
        blockByTradeEquity=_maybe_float(_field(row, "block_by_trade_equity", "blockByTradeEquity")),
        unallocatedBalance=_maybe_float(_field(row, "unallocated_balance", "unallocatedBalance")),
    )


def map_holdings(raw: dict[str, Any]) -> list[BrokerHolding]:
    return [
        BrokerHolding(
            stockCode=_text(_field(row, "stock_code", "stockCode"), ""),
            isin=_maybe_text(_field(row, "stock_ISIN", "isin", "stockIsin")),
            quantity=_float(_field(row, "quantity", "demat_total_bulk_quantity"), 0),
            availableQuantity=_maybe_float(_field(row, "demat_avail_quantity", "availableQuantity")),
        )
        for row in _success_rows(raw)
    ]


def map_positions(raw: dict[str, Any]) -> list[BrokerPosition]:
    return [
        BrokerPosition(
            stockCode=_text(_field(row, "stock_code", "stockCode"), ""),
            exchangeCode=_text(_field(row, "exchange_code", "exchangeCode"), DEFAULT_EXCHANGE_CODE),
            productType=_text(_field(row, "product_type", "productType"), DEFAULT_PRODUCT_TYPE),
            quantity=_float(_field(row, "quantity", "open_quantity", "openQuantity"), 0),
            averagePrice=_maybe_float(_field(row, "average_price", "averagePrice", "averageExecutedRate")),
            pnl=_maybe_float(_field(row, "pnl", "profitLoss", "mtm")),
            action=_maybe_text(_field(row, "action", "orderFlow")),
        )
        for row in _success_rows(raw)
    ]


def map_order(raw: dict[str, Any], fallback_payload: dict[str, Any] | None = None) -> BrokerOrder:
    row = _first_success(raw)
    fallback_payload = fallback_payload or {}
    return BrokerOrder(
        orderId=_text(_field(row, "order_id", "orderId", "orderReference"), ""),
        stockCode=_maybe_text(_field(row, "stock_code", "stockCode")) or _maybe_text(fallback_payload.get("stock_code")),
        action=_maybe_text(_field(row, "action", "orderFlow")) or _maybe_text(fallback_payload.get("action")),
        quantity=_maybe_float(_field(row, "quantity", "orderQuantity", "orderTotalQuantity"))
        or _maybe_float(fallback_payload.get("quantity")),
        price=_maybe_float(_field(row, "price", "limitRate")) or _maybe_float(fallback_payload.get("price")),
        status=_maybe_text(_field(row, "status", "orderStatus")),
        orderType=_maybe_text(_field(row, "order_type", "orderType")) or _maybe_text(fallback_payload.get("order_type")),
        productType=_maybe_text(_field(row, "product_type", "productType"))
        or _maybe_text(fallback_payload.get("product_type")),
        exchangeCode=_maybe_text(_field(row, "exchange_code", "exchangeCode"))
        or _maybe_text(fallback_payload.get("exchange_code")),
        createdAt=_maybe_text(_field(row, "orderDate", "created_at", "createdAt")),
        message=_maybe_text(_field(row, "message")),
    )


def map_orders(raw: dict[str, Any]) -> list[BrokerOrder]:
    return [map_order({"Success": row}) for row in _success_rows(raw)]


def map_trades(raw: dict[str, Any]) -> list[BrokerTrade]:
    trades: list[BrokerTrade] = []
    for row in _success_rows(raw):
        trades.append(
            BrokerTrade(
                tradeId=_text(_field(row, "trade_id", "tradeId", "tradeReference"), ""),
                orderId=_maybe_text(_field(row, "order_id", "orderId", "orderReference")),
                stockCode=_maybe_text(_field(row, "stock_code", "stockCode")),
                action=_maybe_text(_field(row, "action", "orderFlow")),
                quantity=_maybe_float(_field(row, "quantity", "executedQuantity")),
                price=_maybe_float(_field(row, "price", "executionPrice", "averageExecutedRate")),
                tradeDate=_maybe_text(_field(row, "trade_date", "tradeDate", "orderTradeDate")),
                exchangeCode=_maybe_text(_field(row, "exchange_code", "exchangeCode")),
                productType=_maybe_text(_field(row, "product_type", "productType")),
            )
        )
    return trades


def _success_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    success = raw.get("Success")
    if success is None:
        return []
    if isinstance(success, list):
        return [item for item in success if isinstance(item, dict)]
    if isinstance(success, dict):
        nested = success.get("Success")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        return [success]
    return []


def _first_success(raw: dict[str, Any]) -> dict[str, Any]:
    rows = _success_rows(raw)
    return rows[0] if rows else {}


def _field(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _float(value: Any, default: float) -> float:
    parsed = _maybe_float(value)
    return default if parsed is None else parsed


def _maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _text(value: Any, default: str) -> str:
    parsed = _maybe_text(value)
    return default if parsed is None else parsed


def _maybe_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _is_no_records_error(exc: BreezeClientError) -> bool:
    message = str(exc).strip().lower()
    return any(
        phrase in message
        for phrase in (
            "no positions available",
            "no holdings available",
            "no orders available",
            "no trades available",
            "no data found",
        )
    )


def _recent_broker_window() -> tuple[str, str]:
    end = now_utc().astimezone(timezone.utc)
    start = end - timedelta(days=5)
    return _breeze_datetime(start), _breeze_datetime(end)


def _breeze_datetime(value) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
