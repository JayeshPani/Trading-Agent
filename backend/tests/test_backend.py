from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.agent import (
    HermesClient,
    HermesClientError,
    HermesDecisionResult,
    parse_hermes_decision,
)
from backend.app.breeze import BreezeClient, BreezeClientError, BreezeSession
from backend.app.config import AppConfig
from backend.app.main import create_app
from backend.app.improvement import ImprovementProviderError, _decode_review_content
from backend.app.rate_limit import RateLimiter, RateLimitError
from backend.app.schemas import StrategyVersion
from backend.app.schemas import (
    AgentDecisionDraft,
    ConstrainedStrategyRule,
    DailyImprovementReview,
    ImprovementReviewDraft,
    StrategyRuleCondition,
)
from backend.app.store import SQLiteStore
from backend.app.time_utils import (
    IST,
    build_intraday_market_clock,
    current_trading_day,
    is_intraday_entry_cutoff_time,
    is_intraday_square_off_time,
    now_utc,
    utc_iso,
)


class FakeBreezeClient:
    def __init__(self) -> None:
        self.validated_session_key: str | None = None
        self.quote_prices: dict[str, float] = {}
        self.quote_volumes: dict[str, float] = {}
        self.historical_candles: dict[str, list[dict[str, object]]] = {}
        self.quote_calls = 0
        self.historical_calls = 0
        self.place_order_calls = 0
        self.cancel_order_calls = 0
        self.square_off_calls = 0
        self.order_status = "executed"

    def validate_session(self, session_key: str) -> BreezeSession:
        self.validated_session_key = session_key
        return BreezeSession(
            session_token="SECRET_SESSION_TOKEN",
            expires_at=(now_utc() + timedelta(days=1)).isoformat(),
        )

    def place_order(self, session_token: str, payload: dict[str, object]) -> dict[str, object]:
        self.place_order_calls += 1
        return {"Success": {"order_id": "live-test"}}

    def get_quote(self, session_token: str, stock_code: str):
        self.quote_calls += 1
        price = self.quote_prices.get(stock_code, 1500)
        volume = self.quote_volumes.get(stock_code, 10000)
        return {
            "stockCode": stock_code,
            "exchangeCode": "NSE",
            "lastPrice": price,
            "open": price - 10,
            "high": price + 10,
            "low": price - 20,
            "close": price - 5,
            "volume": volume,
            "timestamp": "2026-06-15T09:20:00+05:30",
        }

    def get_historical_candles(
        self,
        session_token: str,
        *,
        stock_code: str,
        from_date: str,
        to_date: str,
        interval: str = "day",
    ):
        self.historical_calls += 1
        if stock_code in self.historical_candles:
            return self.historical_candles[stock_code]
        price = self.quote_prices.get(stock_code, 1500)
        volume = self.quote_volumes.get(stock_code, 10000)
        return [
            {
                "stockCode": stock_code,
                "exchangeCode": "NSE",
                "interval": interval,
                "datetime": from_date,
                "open": price - 10,
                "high": price + 10,
                "low": price - 20,
                "close": price,
                "volume": volume,
            }
        ]

    def get_funds(self, session_token: str):
        return {
            "totalBankBalance": 100000,
            "allocatedEquity": 50000,
            "blockByTradeEquity": 0,
            "unallocatedBalance": 50000,
        }

    def get_holdings(self, session_token: str):
        return [{"stockCode": "HDFCBANK", "isin": "INE040A01034", "quantity": 2, "availableQuantity": 2}]

    def get_positions(self, session_token: str):
        return [
            {
                "stockCode": "HDFCBANK",
                "exchangeCode": "NSE",
                "productType": "cash",
                "quantity": 2,
                "averagePrice": 1500,
                "pnl": 0,
                "action": "buy",
            }
        ]

    def get_order_list(self, session_token: str):
        return [{"orderId": "OID-1", "stockCode": "HDFCBANK", "status": "ordered"}]

    def get_order_status(self, session_token: str, payload: dict[str, object]):
        return {"orderId": payload["order_id"], "status": self.order_status}

    def cancel_order(self, session_token: str, payload: dict[str, object]):
        self.cancel_order_calls += 1
        return {"orderId": payload["order_id"], "status": "cancelled"}

    def get_trade_list(self, session_token: str):
        return [{"tradeId": "TID-1", "orderId": "OID-1", "stockCode": "HDFCBANK"}]

    def square_off(self, session_token: str, payload: dict[str, object]):
        self.square_off_calls += 1
        return {"orderId": "SQ-1", "stockCode": payload["stock_code"], "status": "ordered"}


class TimeUtilsTests(unittest.TestCase):
    def test_intraday_entry_cutoff_starts_at_310_pm_ist(self) -> None:
        before_cutoff = datetime(2026, 6, 18, 15, 9, 59, tzinfo=IST)
        at_cutoff = datetime(2026, 6, 18, 15, 10, tzinfo=IST)

        self.assertFalse(is_intraday_entry_cutoff_time(before_cutoff))
        self.assertTrue(is_intraday_entry_cutoff_time(at_cutoff))

    def test_intraday_square_off_window_starts_at_320_pm_ist(self) -> None:
        before_cutoff = datetime(2026, 6, 18, 15, 19, 59, tzinfo=IST)
        at_cutoff = datetime(2026, 6, 18, 15, 20, tzinfo=IST)
        after_market_close = datetime(2026, 6, 18, 15, 31, tzinfo=IST)

        self.assertFalse(is_intraday_square_off_time(before_cutoff))
        self.assertTrue(is_intraday_square_off_time(at_cutoff))
        self.assertFalse(is_intraday_square_off_time(after_market_close))

    def test_market_clock_reports_late_session_minutes_and_entry_permission(self) -> None:
        clock = build_intraday_market_clock(datetime(2026, 6, 18, 15, 5, tzinfo=IST))

        self.assertEqual(clock["marketPhase"], "late-session")
        self.assertEqual(clock["minutesUntilEntryCutoff"], 5)
        self.assertEqual(clock["minutesUntilSquareOff"], 15)
        self.assertTrue(clock["newEntriesAllowed"])


def make_client(
    *,
    trading_mode: str = "paper",
    enforce_market_hours: bool = False,
    static_ip_ready: bool = False,
    with_env_credentials: bool = True,
    hermes_enabled: bool = False,
    hermes_api_key: str | None = None,
    automation_enabled: bool = False,
    auto_live_entries_enabled: bool = False,
    auto_live_exits_enabled: bool = False,
    scanner_max_symbols_per_cycle: int = 20,
    auto_paper_scan_interval_seconds: int = 0,
    auto_paper_monitor_interval_seconds: int = 0,
    self_improvement_enabled: bool = False,
    auto_challenger_promotion: bool = False,
):
    tempdir = tempfile.TemporaryDirectory()
    db_path = f"{tempdir.name}/test.db"
    config = AppConfig(
        database_path=db_path,
        encryption_key_path=f"{tempdir.name}/fernet.key",
        trading_mode=trading_mode,
        breeze_app_key="APP_KEY_SECRET" if with_env_credentials else None,
        breeze_secret_key="SECRET_KEY_VALUE" if with_env_credentials else None,
        static_ip_ready=static_ip_ready,
        enforce_market_hours=enforce_market_hours,
        hermes_enabled=hermes_enabled,
        hermes_base_url="https://api.moonshot.ai/v1",
        hermes_model="kimi-k2.6",
        hermes_api_key=hermes_api_key,
        hermes_provider="kimi",
        hermes_timeout_seconds=60,
        automation_enabled=automation_enabled,
        auto_paper_scan_interval_seconds=auto_paper_scan_interval_seconds,
        auto_paper_monitor_interval_seconds=auto_paper_monitor_interval_seconds,
        auto_live_exit_interval_seconds=0,
        auto_live_entry_interval_seconds=0,
        scanner_max_symbols_per_cycle=scanner_max_symbols_per_cycle,
        auto_live_entries_enabled=auto_live_entries_enabled,
        auto_live_exits_enabled=auto_live_exits_enabled,
        self_improvement_enabled=self_improvement_enabled,
        self_improvement_time_ist="15:45",
        auto_challenger_promotion=auto_challenger_promotion,
        challenger_canary_percent=10,
    )
    store = SQLiteStore(db_path)
    fake_breeze = FakeBreezeClient()
    app = create_app(config=config, store=store, breeze_client=fake_breeze)
    app.state.fake_breeze = fake_breeze
    return TestClient(app), tempdir, store


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_user(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/account/register",
        json={"username": "local", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    return auth_headers(response.json()["token"])


def complete_setup(client: TestClient) -> dict[str, str]:
    headers = register_user(client)
    session = client.post("/api/session", json={"sessionKey": "RAW_SESSION_KEY"}, headers=headers)
    assert session.status_code == 200, session.text
    return headers


def passing_candles(stock_code: str = "HDFCBANK", count: int = 150) -> list[dict[str, object]]:
    candles: list[dict[str, object]] = []
    price = 100.0
    for index in range(count):
        price += 0.8 if index % 2 == 0 else -0.7
        candles.append(
            {
                "stockCode": stock_code,
                "exchangeCode": "NSE",
                "interval": "day",
                "datetime": f"2026-01-{(index % 28) + 1:02d}",
                "open": round(price - 0.1, 2),
                "high": round(price * 1.031, 2),
                "low": round(price * 0.995, 2),
                "close": round(price, 2),
                "volume": 10000,
            }
        )
    return candles


class BackendApiTests(unittest.TestCase):
    def test_settings_round_trip_and_validation(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        invalid = client.put("/api/settings", json={"budget": 0})
        self.assertEqual(invalid.status_code, 422)

        payload = {
            "budget": 25000,
            "stopLossPercent": 1.2,
            "dailyMaxLoss": 500,
            "maxTradesPerDay": 2,
            "targetPercent": 4,
            "mode": "intraday",
            "stockPreset": "CUSTOM",
            "allowedStocks": ["hdfcbank", " icicibank "],
        }
        response = client.put("/api/settings", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["allowedStocks"], ["HDFCBANK", "ICICIBANK"])
        self.assertEqual(data["targetPercent"], 4)

        fetched = client.get("/api/settings")
        self.assertEqual(fetched.json()["budget"], 25000)

    def test_risk_rejects_trade_above_remaining_total_budget(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 1000,
                "maxTradesPerDay": 5,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK", "RELIANCE"],
            },
            headers=headers,
        )
        store.insert_trade(
            stock="HDFCBANK",
            side="BUY",
            quantity=5,
            entry_price=1500,
            stop_loss=1477.5,
            target=1545,
            mode="intraday",
            strategy="VWAP pullback",
            strategy_version="v1",
            paper=True,
        )
        client.app.state.fake_breeze.quote_prices["RELIANCE"] = 1000
        client.app.state.fake_breeze.historical_candles["RELIANCE"] = passing_candles(
            "RELIANCE"
        )

        response = client.post("/api/paper/run-once", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["riskDecision"], "rejected")
        self.assertIn("remaining available budget", response.json()["riskReason"])

    def test_settings_reject_invalid_target_percent(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        response = client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 0,
                "mode": "intraday",
                "stockPreset": "NIFTY 50",
                "allowedStocks": [],
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_derivative_looking_symbols(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        response = client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["NIFTY25JUNFUT"],
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_paper_autopilot_creates_trade_and_explanation(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        response = client.post("/api/autopilot/start", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["autopilotEnabled"])

        dashboard = client.get("/api/dashboard", headers=headers).json()
        self.assertTrue(dashboard["autopilotEnabled"])
        self.assertEqual(dashboard["pnl"]["openTradesCount"], 1)
        self.assertEqual(dashboard["latestExplanation"]["riskDecision"], "approved")

    def test_emergency_exit_closes_open_trades_and_locks(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.post("/api/autopilot/start", headers=headers)
        response = client.post("/api/emergency-exit", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["locked"])

        dashboard = client.get("/api/dashboard", headers=headers).json()
        self.assertFalse(dashboard["autopilotEnabled"])
        self.assertEqual(dashboard["riskStatus"], "locked")
        self.assertEqual(dashboard["pnl"]["openTradesCount"], 0)
        self.assertEqual(len(client.get("/api/trades/history", headers=headers).json()), 1)

    def test_live_mode_refuses_without_static_ip(self) -> None:
        client, tempdir, store = make_client(trading_mode="live")
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        response = client.post("/api/autopilot/start", headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("session", response.json()["detail"].lower())

    def test_session_response_does_not_expose_secrets(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        response = client.post("/api/session", json={"sessionKey": "RAW_SESSION_KEY"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        body = json.dumps(response.json())
        self.assertIn("active", body)
        self.assertNotIn("RAW_SESSION_KEY", body)
        self.assertNotIn("SECRET_SESSION_TOKEN", body)
        self.assertNotIn("SECRET_KEY_VALUE", body)
        self.assertNotIn("APP_KEY_SECRET", body)

        dashboard_body = json.dumps(client.get("/api/dashboard", headers=headers).json())
        self.assertNotIn("RAW_SESSION_KEY", dashboard_body)
        self.assertNotIn("SECRET_SESSION_TOKEN", dashboard_body)
        self.assertNotIn("SECRET_KEY_VALUE", dashboard_body)
        self.assertNotIn("APP_KEY_SECRET", dashboard_body)

    def test_broker_status_does_not_require_session(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        response = client.get("/api/broker/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["credentialsConfigured"])
        self.assertEqual(data["sessionStatus"], "missing")
        self.assertFalse(data["staticIpReady"])

    def test_broker_inspection_endpoints_return_normalized_objects(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        quote = client.get("/api/broker/quote/HDFCBANK", headers=headers)
        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.json()["stockCode"], "HDFCBANK")
        self.assertEqual(quote.json()["exchangeCode"], "NSE")

        history = client.get("/api/broker/history/HDFCBANK?interval=day", headers=headers)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["stockCode"], "HDFCBANK")

        portfolio = client.get("/api/broker/portfolio", headers=headers)
        self.assertEqual(portfolio.status_code, 200)
        self.assertEqual(portfolio.json()["holdings"][0]["stockCode"], "HDFCBANK")

        orders = client.get("/api/broker/orders", headers=headers)
        self.assertEqual(orders.status_code, 200)
        self.assertEqual(orders.json()[0]["orderId"], "OID-1")

        trades = client.get("/api/broker/trades", headers=headers)
        self.assertEqual(trades.status_code, 200)
        self.assertEqual(trades.json()[0]["tradeId"], "TID-1")

        body = json.dumps(
            {
                "quote": quote.json(),
                "history": history.json(),
                "portfolio": portfolio.json(),
                "orders": orders.json(),
                "trades": trades.json(),
            }
        )
        self.assertNotIn("RAW_SESSION_KEY", body)
        self.assertNotIn("SECRET_SESSION_TOKEN", body)
        self.assertNotIn("SECRET_KEY_VALUE", body)
        self.assertNotIn("APP_KEY_SECRET", body)

    def test_broker_endpoint_rejects_invalid_stock(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        response = client.get("/api/broker/quote/NIFTY25JUNFUT", headers=headers)
        self.assertEqual(response.status_code, 400)

    def test_hermes_parser_rejects_unsupported_strategy(self) -> None:
        with self.assertRaises(HermesClientError):
            parse_hermes_decision(
                json.dumps(
                    {
                        "action": "PROPOSE_ENTRY",
                        "stock": "HDFCBANK",
                        "strategy": "creative-ai-strategy",
                        "side": "BUY",
                        "quantity": 1,
                        "entryPrice": 1500,
                        "stopLoss": 1480,
                        "target": 1530,
                        "confidence": 0.7,
                        "reasons": ["test"],
                        "risks": [],
                    }
                )
            )

    def test_hermes_parser_normalizes_percentage_confidence(self) -> None:
        decision = parse_hermes_decision(
            json.dumps(
                {
                    "action": "SKIP",
                    "confidence": 62,
                    "reasons": ["No sufficiently strong setup."],
                    "risks": [],
                }
            )
        )

        self.assertEqual(decision.confidence, 0.62)

    def test_hermes_parser_normalizes_single_reason_and_risk_strings(self) -> None:
        decision = parse_hermes_decision(
            json.dumps(
                {
                    "action": "SKIP",
                    "confidence": 0.4,
                    "reasons": "Volume confirmation is weak.",
                    "risks": "Opening-session signals may be unreliable.",
                }
            )
        )

        self.assertEqual(decision.reasons, ["Volume confirmation is weak."])
        self.assertEqual(decision.risks, ["Opening-session signals may be unreliable."])

    def test_hermes_parser_normalizes_common_non_entry_schema_variations(self) -> None:
        decision = parse_hermes_decision(
            json.dumps(
                {
                    "decision": {
                        "action": "hold",
                        "reasons": [{"summary": "An existing position is already open."}],
                        "risks": None,
                    }
                }
            )
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertEqual(decision.confidence, 0)
        self.assertEqual(
            decision.reasons,
            ['{"summary":"An existing position is already open."}'],
        )
        self.assertEqual(decision.risks, [])

    def test_hermes_parser_extracts_json_from_wrapping_text_and_double_encoding(self) -> None:
        wrapped = parse_hermes_decision(
            'Decision follows:\n{"action":"HOLD","confidence":0.5,"reasons":["Open trade."],"risks":[]}\nDone.'
        )
        encoded = parse_hermes_decision(
            json.dumps(
                json.dumps(
                    {
                        "action": "SKIP",
                        "confidence": 0.2,
                        "reasons": ["No clean setup."],
                        "risks": [],
                    }
                )
            )
        )

        self.assertEqual(wrapped.action, "HOLD")
        self.assertEqual(encoded.action, "SKIP")

    def test_agent_status_reports_kimi_without_exposing_api_key(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True, hermes_api_key="KIMI_SECRET_KEY")
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = register_user(client)

        response = client.get("/api/agent/status", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["provider"], "kimi")
        self.assertEqual(data["model"], "kimi-k2.6")
        self.assertEqual(data["baseUrl"], "https://api.moonshot.ai/v1")
        self.assertTrue(data["apiKeyConfigured"])
        self.assertNotIn("KIMI_SECRET_KEY", json.dumps(data))

    def test_hermes_client_sends_kimi_authorization_header(self) -> None:
        config = AppConfig(
            database_path=":memory:",
            encryption_key_path="backend/data/test.key",
            trading_mode="paper",
            breeze_app_key=None,
            breeze_secret_key=None,
            static_ip_ready=False,
            enforce_market_hours=False,
            hermes_enabled=True,
            hermes_base_url="https://api.moonshot.ai/v1",
            hermes_model="kimi-k2.6",
            hermes_api_key="KIMI_SECRET_KEY",
            hermes_provider="kimi",
            hermes_timeout_seconds=60,
        )
        captured: dict[str, object] = {}

        class FakeHttpResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "action": "SKIP",
                                            "confidence": 0.1,
                                            "reasons": ["No clean setup."],
                                            "risks": ["Weak signals."],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeHttpResponse()

        with patch("backend.app.agent.urllib.request.urlopen", side_effect=fake_urlopen):
            decision = HermesClient(config).decide({"safe": True})

        self.assertEqual(decision.action, "SKIP")
        self.assertEqual(captured["url"], "https://api.moonshot.ai/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer KIMI_SECRET_KEY")
        self.assertEqual(captured["body"]["model"], "kimi-k2.6")
        self.assertEqual(captured["body"]["thinking"], {"type": "disabled"})
        self.assertNotIn("temperature", captured["body"])
        self.assertEqual(captured["timeout"], 60)
        system_prompt = captured["body"]["messages"][0]["content"]
        self.assertIn("long-only", system_prompt)
        self.assertIn("side BUY", system_prompt)
        self.assertIn("scanner.shortlist", system_prompt)
        self.assertIn("15:10 IST", system_prompt)
        self.assertIn("15:20 IST", system_prompt)
        self.assertIn("Do not emit TIGHTEN_STOP", system_prompt)
        self.assertIn("JSON arrays of short strings", system_prompt)
        self.assertIn("scanner.ageSeconds", system_prompt)

    def test_hermes_client_reports_provider_http_error_detail(self) -> None:
        config = AppConfig(
            database_path=":memory:",
            encryption_key_path="backend/data/test.key",
            trading_mode="paper",
            breeze_app_key=None,
            breeze_secret_key=None,
            static_ip_ready=False,
            enforce_market_hours=False,
            hermes_enabled=True,
            hermes_base_url="https://api.moonshot.ai/v1",
            hermes_model="kimi-k2.6",
            hermes_api_key="KIMI_SECRET_KEY",
            hermes_provider="kimi",
            hermes_timeout_seconds=60,
        )
        error = urllib.error.HTTPError(
            url="https://api.moonshot.ai/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(
                json.dumps(
                    {"error": {"message": "invalid temperature: only 1 is allowed"}}
                ).encode("utf-8")
            ),
        )

        with patch("backend.app.agent.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(
                HermesClientError,
                "HTTP 400: invalid temperature: only 1 is allowed",
            ):
                HermesClient(config).decide({"safe": True})

    def test_hermes_client_repairs_invalid_structured_response_once(self) -> None:
        config = AppConfig(
            database_path=":memory:",
            encryption_key_path="backend/data/test.key",
            trading_mode="paper",
            breeze_app_key=None,
            breeze_secret_key=None,
            static_ip_ready=False,
            enforce_market_hours=False,
            hermes_enabled=True,
            hermes_base_url="https://api.moonshot.ai/v1",
            hermes_model="kimi-k2.6",
            hermes_api_key="KIMI_SECRET_KEY",
            hermes_provider="kimi",
            hermes_timeout_seconds=60,
        )
        responses = [
            {"choices": [{"message": {"content": '{"action":"WAIT"}'}}]},
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "SKIP",
                                    "confidence": 0.3,
                                    "reasons": ["Weak volume."],
                                    "risks": ["Opening volatility."],
                                }
                            )
                        }
                    }
                ]
            },
        ]
        requests: list[dict[str, object]] = []

        class FakeHttpResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return FakeHttpResponse(responses[len(requests) - 1])

        with patch("backend.app.agent.urllib.request.urlopen", side_effect=fake_urlopen):
            decision = HermesClient(config).decide({"safe": True})

        self.assertEqual(decision.action, "SKIP")
        self.assertEqual(decision.reasons, ["Weak volume."])
        self.assertEqual(decision.integrity_status, "repaired")
        self.assertEqual(len(requests), 2)
        self.assertIn("Repair the supplied trading decision", requests[1]["messages"][0]["content"])

    def test_agent_integrity_tracks_system_error_and_recovery(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)

        with patch(
            "backend.app.agent.HermesClient.decide",
            side_effect=HermesClientError("Hermes returned invalid structured JSON."),
        ):
            failed = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertEqual(failed.json()["decision"]["integrityStatus"], "system_error")
        self.assertEqual(failed.json()["decision"]["action"], "SKIP")
        self.assertEqual(client.get("/api/trades/open", headers=headers).json(), [])
        unhealthy = client.get("/api/agent/status", headers=headers).json()
        self.assertFalse(unhealthy["healthy"])
        self.assertEqual(unhealthy["consecutiveSystemErrors"], 1)
        validation = client.get("/api/paper/validation", headers=headers).json()
        self.assertEqual(validation["unresolvedAgentErrors"], 1)
        self.assertIn("Unresolved agent decision errors", validation["reason"])

        recovered_draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "SKIP",
                    "confidence": 0.4,
                    "reasons": ["Weak volume."],
                    "risks": ["No clean setup."],
                }
            )
        )
        with patch(
            "backend.app.agent.HermesClient.decide",
            return_value=HermesDecisionResult(
                draft=recovered_draft,
                integrity_status="genuine",
                integrity_message="Kimi returned a valid decision directly.",
            ),
        ):
            recovered = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["decision"]["integrityStatus"], "genuine")
        healthy = client.get("/api/agent/status", headers=headers).json()
        self.assertTrue(healthy["healthy"])
        self.assertEqual(healthy["consecutiveSystemErrors"], 0)
        self.assertIsNotNone(healthy["lastValidDecisionAt"])

    def test_repaired_entry_can_open_paper_trade_after_risk_approval(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["VWAP support held."],
                    "risks": ["Weak volume."],
                }
            )
        )

        with patch(
            "backend.app.agent.HermesClient.decide",
            return_value=HermesDecisionResult(
                draft=draft,
                integrity_status="repaired",
                integrity_message="Kimi decision was normalized by one schema-repair request.",
            ),
        ):
            response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["integrityStatus"], "repaired")
        self.assertEqual(response.json()["decision"]["riskDecision"], "approved")
        self.assertIsNotNone(response.json()["decision"]["tradeId"])

    def test_agent_integrity_backfill_relabels_known_fallback_rows(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        with store._lock, store._conn:
            store._conn.execute(
                """
                INSERT INTO agent_decisions (
                    id, run_id, action, confidence, reasons, risks, risk_decision,
                    risk_reason, source, created_at, integrity_status, integrity_message
                )
                VALUES (
                    'legacy-error', 'legacy-run', 'SKIP', 0,
                    '["Hermes did not produce a usable decision."]',
                    '["Hermes returned invalid structured JSON."]',
                    'none', 'No entry risk review required.', 'paper_cycle',
                    '2026-06-19T04:00:00+00:00', NULL, NULL
                )
                """
            )
            store._conn.execute(
                """
                INSERT INTO agent_decisions (
                    id, run_id, action, confidence, reasons, risks, risk_decision,
                    risk_reason, source, created_at, integrity_status, integrity_message
                )
                VALUES (
                    'legacy-genuine', 'legacy-run-2', 'SKIP', 0.4,
                    '["Weak volume."]', '["Opening risk."]',
                    'none', 'No entry risk review required.', 'paper_cycle',
                    '2026-06-19T04:05:00+00:00', NULL, NULL
                )
                """
            )
            store._backfill_agent_integrity()

        decisions = {decision.id: decision for decision in store.list_agent_decisions()}
        self.assertEqual(decisions["legacy-error"].integrity_status, "system_error")
        self.assertEqual(decisions["legacy-genuine"].integrity_status, "genuine")

    def test_hermes_paper_cycle_opens_trade_after_risk_approval(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["VWAP support held."],
                    "risks": ["Paper mode only."],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["decision"]["riskDecision"], "approved")
        self.assertIsNotNone(data["decision"]["tradeId"])
        self.assertEqual(client.app.state.fake_breeze.place_order_calls, 0)
        self.assertEqual(len(client.get("/api/trades/open", headers=headers).json()), 1)

    def test_hermes_context_includes_intraday_market_clock(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        captured: dict[str, object] = {}
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "SKIP",
                    "confidence": 0.2,
                    "reasons": ["No clean setup."],
                    "risks": ["Late session."],
                }
            )
        )

        def capture_context(context):
            captured.update(context)
            return draft

        clock = {
            "currentTimeIst": "2026-06-18T15:05:00+05:30",
            "marketPhase": "late-session",
            "entryCutoffIst": "15:10",
            "squareOffIst": "15:20",
            "minutesUntilEntryCutoff": 5,
            "minutesUntilSquareOff": 15,
            "newEntriesAllowed": True,
        }
        with (
            patch("backend.app.agent.build_intraday_market_clock", return_value=clock),
            patch("backend.app.agent.HermesClient.decide", side_effect=capture_context),
        ):
            response = client.post("/api/agent/analyze", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(captured["marketClock"], clock)
        self.assertIn("generatedAtUtc", captured["scanner"])
        self.assertIn("generatedAtIst", captured["scanner"])
        self.assertGreaterEqual(captured["scanner"]["ageSeconds"], 0)

    def test_hermes_rejects_sell_entry_for_long_only_strategy(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "SELL",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1520,
                    "target": 1470,
                    "confidence": 0.72,
                    "reasons": ["Model attempted a short entry."],
                    "risks": [],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["riskDecision"], "rejected")
        self.assertIn("long BUY entries only", response.json()["decision"]["riskReason"])
        self.assertEqual(client.get("/api/trades/open", headers=headers).json(), [])

    def test_hermes_rejects_stock_absent_from_scanner_shortlist(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True, scanner_max_symbols_per_cycle=1)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "RELIANCE",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["Model selected a non-shortlisted stock."],
                    "risks": [],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["riskDecision"], "rejected")
        self.assertIn("absent from the current scanner shortlist", response.json()["decision"]["riskReason"])

    def test_hermes_rejects_strategy_mismatch_and_stale_entry_price(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        mismatched = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "EMA crossover",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["Wrong strategy."],
                    "risks": [],
                }
            )
        )
        with patch("backend.app.agent.HermesClient.decide", return_value=mismatched):
            mismatch_response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(mismatch_response.status_code, 200, mismatch_response.text)
        self.assertIn(
            "does not match the scanner-assigned strategy",
            mismatch_response.json()["decision"]["riskReason"],
        )

        stale = mismatched.model_copy(
            update={"strategy": "VWAP pullback", "entry_price": 1600}
        )
        with patch("backend.app.agent.HermesClient.decide", return_value=stale):
            stale_response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(stale_response.status_code, 200, stale_response.text)
        self.assertIn(
            "not aligned with the current scanner quote",
            stale_response.json()["decision"]["riskReason"],
        )

    def test_hermes_rejects_entry_after_310_pm_cutoff(self) -> None:
        client, tempdir, store = make_client(
            hermes_enabled=True,
            enforce_market_hours=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["Late entry attempt."],
                    "risks": [],
                }
            )
        )

        with (
            patch("backend.app.agent.HermesClient.decide", return_value=draft),
            patch("backend.app.agent.is_intraday_entry_cutoff_time", return_value=True),
        ):
            response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["riskDecision"], "rejected")
        self.assertIn("Intraday entry cutoff has passed", response.json()["decision"]["riskReason"])

    def test_hermes_paper_cycle_reduces_quantity_to_risk_budget(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 100,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["VWAP support held."],
                    "risks": [],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/agent/paper-cycle", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["quantity"], 5)
        self.assertEqual(client.get("/api/trades/open", headers=headers).json()[0]["quantity"], 5)

    def test_hermes_live_proposal_prepares_order_without_broker_submission(self) -> None:
        client, tempdir, store = make_client(
            trading_mode="live",
            static_ip_ready=True,
            hermes_enabled=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()
        headers = complete_setup(client)
        backtest = client.post(
            "/api/backtests/run",
            json={"strategy": "VWAP pullback", "stockCode": "HDFCBANK"},
            headers=headers,
        )
        self.assertEqual(backtest.status_code, 200, backtest.text)
        self.assertTrue(backtest.json()["passed"])
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.74,
                    "reasons": ["Scanner and Hermes agree."],
                    "risks": ["Requires manual confirmation."],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/agent/live-proposal", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["decision"]["riskDecision"], "approved")
        self.assertEqual(data["liveOrder"]["status"], "prepared")
        self.assertEqual(data["decision"]["orderId"], data["liveOrder"]["id"])
        self.assertEqual(client.app.state.fake_breeze.place_order_calls, 0)

    def test_hermes_responses_do_not_expose_secrets(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "SKIP",
                    "confidence": 0.2,
                    "reasons": ["Weak setup."],
                    "risks": ["No trade."],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/agent/analyze", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        serialized = json.dumps(response.json())
        self.assertNotIn("APP_KEY_SECRET", serialized)
        self.assertNotIn("SECRET_KEY_VALUE", serialized)
        self.assertNotIn("SECRET_SESSION_TOKEN", serialized)
        self.assertNotIn("RAW_SESSION_KEY", serialized)

    def test_automation_start_requires_env_master_switch(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)

        status = client.get("/api/automation/status", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["configEnabled"])

        start = client.post("/api/automation/start", headers=headers)
        self.assertEqual(start.status_code, 400)
        self.assertIn("AUTOMATION_ENABLED", start.json()["detail"])

    def test_automation_run_once_opens_paper_trade_after_risk_approval(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        runtime = store.get_runtime()
        runtime.autopilot_enabled = True
        store.save_runtime(runtime)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "PROPOSE_ENTRY",
                    "stock": "HDFCBANK",
                    "strategy": "VWAP pullback",
                    "side": "BUY",
                    "quantity": 1,
                    "entryPrice": 1500,
                    "stopLoss": 1480,
                    "target": 1530,
                    "confidence": 0.72,
                    "reasons": ["Automation paper cycle."],
                    "risks": ["Paper mode only."],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            response = client.post("/api/automation/run-once", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(len(client.get("/api/trades/open", headers=headers).json()), 1)
        self.assertEqual(client.app.state.fake_breeze.place_order_calls, 0)

    def test_scheduler_waits_for_monitor_interval_after_intraday_square_off(self) -> None:
        client, tempdir, store = make_client(
            automation_enabled=True,
            auto_paper_monitor_interval_seconds=30,
            enforce_market_hours=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        runtime = store.get_runtime()
        runtime.autopilot_enabled = True
        store.save_runtime(runtime)
        settings = store.get_settings()
        settings.mode = "intraday"
        store.save_settings(settings)
        store.update_automation_timestamp("last_paper_monitor_at")
        state = store.get_automation_state()

        with patch(
            "backend.app.automation.is_intraday_square_off_time",
            return_value=True,
        ):
            due = client.app.state.automation_runner._scheduled_cycle_due(state)

        self.assertFalse(due)

    def test_agent_paper_cycle_respects_scanner_symbol_cap(self) -> None:
        client, tempdir, store = make_client(
            hermes_enabled=True,
            scanner_max_symbols_per_cycle=3,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        runtime = store.get_runtime()
        runtime.autopilot_enabled = True
        store.save_runtime(runtime)
        draft = parse_hermes_decision(
            json.dumps(
                {
                    "action": "SKIP",
                    "confidence": 0.1,
                    "reasons": ["Scanner cap test."],
                    "risks": ["No entry."],
                }
            )
        )

        with patch("backend.app.agent.HermesClient.decide", return_value=draft):
            client.app.state.fake_breeze.quote_calls = 0
            client.app.state.fake_breeze.historical_calls = 0
            response = client.post("/api/automation/run-once", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")
        self.assertLessEqual(client.app.state.fake_breeze.quote_calls, 3)
        self.assertLessEqual(client.app.state.fake_breeze.historical_calls, 3)

    def test_paper_validation_requires_days_trades_and_profit_factor(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)

        initial = client.get("/api/paper/validation", headers=headers)
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()["eligible"])

        with store._lock, store._conn:
            for day in range(1, 6):
                for trade in range(2):
                    trade_id = f"paper-{day}-{trade}"
                    closed_at = f"2026-06-{day:02d}T10:00:00+00:00"
                    store._conn.execute(
                        """
                        INSERT INTO trades (
                            id, stock, side, quantity, entry_price, stop_loss, target, live_pnl,
                            status, mode, strategy, strategy_version, exit_price, pnl,
                            exit_reason, opened_at, closed_at, paper
                        )
                        VALUES (?, 'HDFCBANK', 'BUY', 1, 100, 98, 103, 2,
                                'target_hit', 'intraday', 'VWAP pullback', 'v1',
                                102, 2, 'Target hit', ?, ?, 1)
                        """,
                        (trade_id, closed_at, closed_at),
                    )

        passed = client.get("/api/paper/validation", headers=headers)
        self.assertEqual(passed.status_code, 200)
        self.assertTrue(passed.json()["eligible"])
        self.assertEqual(passed.json()["days"], 5)
        self.assertEqual(passed.json()["completedTrades"], 10)

    def test_paper_validation_treats_later_config_event_as_error_resolution(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        store.insert_automation_event(
            event_type="automation.error",
            severity="error",
            message="Breeze API minute limit would be exceeded.",
        )
        store.insert_automation_event(
            event_type="automation.config",
            severity="info",
            message="Scanner batch capped.",
        )

        response = client.get("/api/paper/validation", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unresolvedAutomationErrors"], 0)
        self.assertNotIn("Automation errors are present today.", response.json()["reason"])

    def test_paper_monitor_continues_when_one_trade_quote_fails(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        store.insert_trade(
            stock="HDFCBANK",
            side="BUY",
            quantity=1,
            entry_price=1500,
            stop_loss=1400,
            target=1700,
            mode="intraday",
            strategy="EMA crossover",
            strategy_version="v1",
            paper=True,
        )
        store.insert_trade(
            stock="RELIANCE",
            side="BUY",
            quantity=1,
            entry_price=1000,
            stop_loss=900,
            target=1200,
            mode="intraday",
            strategy="EMA crossover",
            strategy_version="v1",
            paper=True,
        )
        fake_breeze = client.app.state.fake_breeze
        original_get_quote = fake_breeze.get_quote
        fake_breeze.quote_prices["RELIANCE"] = 1010

        def mixed_quote(session_token: str, stock_code: str):
            if stock_code == "HDFCBANK":
                raise BreezeClientError(
                    "Breeze GET /quotes failed with status 503.",
                    endpoint="/quotes",
                    status_code=503,
                    retryable=True,
                )
            return original_get_quote(session_token, stock_code)

        with patch.object(fake_breeze, "get_quote", side_effect=mixed_quote):
            response = client.post("/api/paper/monitor", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        trades = {trade["stock"]: trade for trade in response.json()}
        self.assertEqual(trades["HDFCBANK"]["livePnl"], 0)
        self.assertEqual(trades["RELIANCE"]["livePnl"], 10)

    def test_failed_monitor_cycle_waits_for_normal_interval(self) -> None:
        client, tempdir, store = make_client(
            automation_enabled=True,
            auto_paper_scan_interval_seconds=300,
            auto_paper_monitor_interval_seconds=30,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        runtime = store.get_runtime()
        runtime.autopilot_enabled = True
        store.save_runtime(runtime)
        store.update_automation_timestamp("last_paper_scan_at")
        store.insert_trade(
            stock="HDFCBANK",
            side="BUY",
            quantity=1,
            entry_price=1500,
            stop_loss=1400,
            target=1700,
            mode="intraday",
            strategy="EMA crossover",
            strategy_version="v1",
            paper=True,
        )
        failure = BreezeClientError(
            "Breeze GET /quotes failed with status 503.",
            endpoint="/quotes",
            status_code=503,
            retryable=True,
        )
        fake_breeze = client.app.state.fake_breeze

        with patch.object(fake_breeze, "get_quote", side_effect=failure) as quote_mock:
            first = client.post("/api/automation/run-once", headers=headers)
            second = client.post("/api/automation/run-once", headers=headers)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(quote_mock.call_count, 1)
        status = client.get("/api/automation/status", headers=headers).json()
        self.assertEqual(status["brokerHealth"], "degraded")
        self.assertEqual(status["consecutiveBrokerFailures"], 1)

    def test_three_failed_broker_cycles_escalate_and_success_clears(self) -> None:
        client, tempdir, store = make_client(
            automation_enabled=True,
            auto_paper_scan_interval_seconds=300,
            auto_paper_monitor_interval_seconds=0,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        runtime = store.get_runtime()
        runtime.autopilot_enabled = True
        store.save_runtime(runtime)
        store.update_automation_timestamp("last_paper_scan_at")
        store.insert_trade(
            stock="HDFCBANK",
            side="BUY",
            quantity=1,
            entry_price=1500,
            stop_loss=1400,
            target=1700,
            mode="intraday",
            strategy="EMA crossover",
            strategy_version="v1",
            paper=True,
        )
        failure = BreezeClientError(
            "Breeze GET /quotes failed with status 503.",
            endpoint="/quotes",
            status_code=503,
            retryable=True,
        )
        fake_breeze = client.app.state.fake_breeze

        with patch.object(fake_breeze, "get_quote", side_effect=failure):
            for _ in range(3):
                response = client.post("/api/automation/run-once", headers=headers)
                self.assertEqual(response.status_code, 200, response.text)

        unavailable = client.get("/api/automation/status", headers=headers).json()
        self.assertEqual(unavailable["brokerHealth"], "unavailable")
        self.assertEqual(unavailable["consecutiveBrokerFailures"], 3)
        validation = client.get("/api/paper/validation", headers=headers).json()
        self.assertEqual(validation["unresolvedAutomationErrors"], 1)

        recovered = client.post("/api/automation/run-once", headers=headers)
        self.assertEqual(recovered.status_code, 200, recovered.text)
        healthy = client.get("/api/automation/status", headers=headers).json()
        self.assertEqual(healthy["brokerHealth"], "healthy")
        self.assertEqual(healthy["consecutiveBrokerFailures"], 0)
        validation = client.get("/api/paper/validation", headers=headers).json()
        self.assertEqual(validation["unresolvedAutomationErrors"], 0)

    def test_systemic_scanner_outage_does_not_call_kimi(self) -> None:
        client, tempdir, store = make_client(
            automation_enabled=True,
            hermes_enabled=True,
            scanner_max_symbols_per_cycle=20,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        runtime = store.get_runtime()
        runtime.autopilot_enabled = True
        store.save_runtime(runtime)
        failure = BreezeClientError(
            "Breeze GET /quotes failed with status 503.",
            endpoint="/quotes",
            status_code=503,
            retryable=True,
        )

        with patch.object(client.app.state.fake_breeze, "get_quote", side_effect=failure):
            with patch("backend.app.agent.HermesClient.decide") as decide_mock:
                response = client.post("/api/automation/run-once", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("scanner paused", response.json()["summary"])
        decide_mock.assert_not_called()
        scanner = client.get("/api/scanner/latest", headers=headers).json()
        self.assertEqual(scanner["brokerStatus"], "unavailable")
        self.assertEqual(scanner["brokerErrorCount"], 3)

    def test_live_automation_does_not_place_entry_when_auto_entries_disabled(self) -> None:
        client, tempdir, store = make_client(
            trading_mode="live",
            static_ip_ready=True,
            hermes_enabled=True,
            automation_enabled=True,
            auto_live_entries_enabled=False,
            auto_live_exits_enabled=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        store.set_live_autopilot(True)

        response = client.post("/api/automation/run-once", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(client.app.state.fake_breeze.place_order_calls, 0)

    def test_account_register_login_logout_and_setup_status(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        status = client.get("/api/setup/status").json()
        self.assertFalse(status["accountExists"])
        self.assertEqual(status["nextStep"], "account")

        register = client.post(
            "/api/account/register",
            json={"username": "local", "password": "password123"},
        )
        self.assertEqual(register.status_code, 200)
        token = register.json()["token"]

        logged_in = client.get("/api/setup/status", headers=auth_headers(token)).json()
        self.assertTrue(logged_in["accountExists"])
        self.assertTrue(logged_in["loggedIn"])

        logged_out = client.get("/api/setup/status").json()
        self.assertFalse(logged_out["loggedIn"])
        self.assertEqual(logged_out["nextStep"], "login")

        logout = client.post("/api/account/logout", headers=auth_headers(token))
        self.assertEqual(logout.status_code, 200)
        self.assertTrue(logout.json()["ok"])

        login = client.post(
            "/api/account/login",
            json={"username": "local", "password": "password123"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("token", login.json())

    def test_auth_required_after_account_exists(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        missing = client.get("/api/settings")
        self.assertEqual(missing.status_code, 401)

        invalid = client.get("/api/settings", headers=auth_headers("bad-token"))
        self.assertEqual(invalid.status_code, 401)

        ok = client.get("/api/settings", headers=headers)
        self.assertEqual(ok.status_code, 200)

    def test_encrypted_breeze_credentials_status_and_delete(self) -> None:
        client, tempdir, store = make_client(with_env_credentials=False)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        initial = client.get("/api/credentials/status", headers=headers)
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()["breezeCredentialsSaved"])

        save = client.put(
            "/api/credentials/breeze",
            json={"appKey": "APP_KEY_SECRET", "secretKey": "SECRET_KEY_VALUE"},
            headers=headers,
        )
        self.assertEqual(save.status_code, 200)
        body = json.dumps(save.json())
        self.assertNotIn("APP_KEY_SECRET", body)
        self.assertNotIn("SECRET_KEY_VALUE", body)
        self.assertTrue(save.json()["breezeCredentialsSaved"])

        encrypted = store.get_breeze_credentials()
        self.assertIsNotNone(encrypted)
        self.assertNotIn("APP_KEY_SECRET", encrypted[0])
        self.assertNotIn("SECRET_KEY_VALUE", encrypted[1])

        deleted = client.delete("/api/credentials/breeze", headers=headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(deleted.json()["breezeCredentialsSaved"])

    def test_setup_status_transitions_to_ready(self) -> None:
        client, tempdir, store = make_client(with_env_credentials=False)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        self.assertEqual(client.get("/api/setup/status").json()["nextStep"], "account")
        headers = register_user(client)
        self.assertEqual(client.get("/api/setup/status", headers=headers).json()["nextStep"], "credentials")

        client.put(
            "/api/credentials/breeze",
            json={"appKey": "APP_KEY_SECRET", "secretKey": "SECRET_KEY_VALUE"},
            headers=headers,
        )
        self.assertEqual(client.get("/api/setup/status", headers=headers).json()["nextStep"], "session")

        client.post("/api/session", json={"sessionKey": "RAW_SESSION_KEY"}, headers=headers)
        ready = client.get("/api/setup/status", headers=headers).json()
        self.assertEqual(ready["nextStep"], "ready")
        self.assertTrue(ready["setupComplete"])

    def test_autopilot_refuses_until_setup_complete(self) -> None:
        client, tempdir, store = make_client(with_env_credentials=False)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        response = client.post("/api/autopilot/start", headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("credentials", response.json()["detail"])

    def test_strategy_list_contains_only_approved_templates(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        response = client.get("/api/strategies", headers=headers)
        self.assertEqual(response.status_code, 200)
        names = {strategy["name"] for strategy in response.json()}
        self.assertEqual(
            names,
            {
                "VWAP pullback",
                "EMA crossover",
                "Momentum breakout",
                "Opening range breakout",
                "Mean reversion",
            },
        )

    def test_scanner_ranks_configured_stocks_and_rejects_low_liquidity(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK", "RELIANCE"],
            },
            headers=headers,
        )
        client.app.state.fake_breeze.quote_volumes["RELIANCE"] = 10

        response = client.post("/api/scanner/run", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([candidate["stockCode"] for candidate in data["candidates"]], ["HDFCBANK", "RELIANCE"])
        self.assertEqual(data["shortlist"][0]["stockCode"], "HDFCBANK")
        rejected = [candidate for candidate in data["candidates"] if candidate["rejected"]]
        self.assertEqual(rejected[0]["stockCode"], "RELIANCE")
        self.assertIn("Liquidity", rejected[0]["rejectionReason"])

    def test_paper_run_opens_from_quote_without_live_order_call(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK"],
            },
            headers=headers,
        )

        response = client.post("/api/paper/run-once", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["riskDecision"], "approved")

        open_trades = client.get("/api/trades/open", headers=headers).json()
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["stock"], "HDFCBANK")
        self.assertEqual(open_trades[0]["entryPrice"], 1500)
        self.assertEqual(open_trades[0]["strategy"], "VWAP pullback")
        self.assertEqual(client.app.state.fake_breeze.place_order_calls, 0)

    def test_paper_monitor_updates_pnl_and_closes_on_target(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK"],
            },
            headers=headers,
        )
        client.post("/api/paper/run-once", headers=headers)
        client.app.state.fake_breeze.quote_prices["HDFCBANK"] = 1600

        monitor = client.post("/api/paper/monitor", headers=headers)
        self.assertEqual(monitor.status_code, 200)
        self.assertEqual(monitor.json(), [])

        history = client.get("/api/trades/history", headers=headers).json()
        self.assertEqual(history[0]["status"], "target_hit")
        self.assertGreater(history[0]["pnl"], 0)
        explanation = client.get("/api/explanations/latest", headers=headers).json()
        self.assertEqual(explanation["exitReason"], "Target hit")

    def test_paper_monitor_closes_intraday_trade_at_square_off_cutoff(self) -> None:
        client, tempdir, store = make_client(enforce_market_hours=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        trade_id = store.insert_trade(
            stock="HDFCBANK",
            side="BUY",
            quantity=2,
            entry_price=1500,
            stop_loss=1477.5,
            target=1545,
            mode="intraday",
            strategy="VWAP pullback",
            strategy_version="v1",
            paper=True,
        )
        client.app.state.fake_breeze.quote_prices["HDFCBANK"] = 1510

        with patch("backend.app.trading.is_intraday_square_off_time", return_value=True):
            monitor = client.post("/api/paper/monitor", headers=headers)

        self.assertEqual(monitor.status_code, 200, monitor.text)
        self.assertEqual(monitor.json(), [])
        history = client.get("/api/trades/history", headers=headers).json()
        closed = next(item for item in history if item["id"] == trade_id)
        self.assertEqual(closed["status"], "exited")
        self.assertEqual(closed["exitReason"], "Intraday square-off")
        self.assertEqual(closed["exitPrice"], 1510)

    def test_risk_engine_rejects_new_intraday_entry_after_cutoff(self) -> None:
        client, tempdir, store = make_client(enforce_market_hours=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK"],
            },
            headers=headers,
        )

        with (
            patch("backend.app.risk.is_market_open", return_value=True),
            patch("backend.app.risk.is_intraday_entry_cutoff_time", return_value=True),
        ):
            response = client.post("/api/paper/run-once", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["riskDecision"], "rejected")
        self.assertIn("Intraday entry cutoff has passed", response.json()["riskReason"])
        self.assertEqual(client.get("/api/trades/open", headers=headers).json(), [])

    def test_duplicate_open_trade_is_risk_rejected_with_xai_context(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK", "RELIANCE"],
            },
            headers=headers,
        )
        first = client.post("/api/paper/run-once", headers=headers)
        self.assertEqual(first.status_code, 200)
        second = client.post("/api/paper/run-once", headers=headers)
        self.assertEqual(second.status_code, 200)
        body = second.json()
        self.assertEqual(body["riskDecision"], "rejected")
        self.assertIn("already has an open trade", body["riskReason"])
        self.assertIn("HDFCBANK", body["selectedCandidates"])
        self.assertTrue(body["rejectedCandidates"])

    def test_backtest_run_stores_metrics_and_sets_strategy_eligibility(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()

        response = client.post(
            "/api/backtests/run",
            json={"strategy": "VWAP pullback", "stockCode": "HDFCBANK"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["passed"])
        self.assertGreaterEqual(data["metrics"]["tradesCount"], 100)
        self.assertGreaterEqual(data["metrics"]["profitFactor"], 1.2)

        listing = client.get("/api/backtests", headers=headers)
        self.assertEqual(len(listing.json()), 1)

        detail = client.get(f"/api/backtests/{data['id']}", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], data["id"])

        eligibility = client.get("/api/strategies/VWAP%20pullback/eligibility", headers=headers)
        self.assertEqual(eligibility.status_code, 200)
        self.assertTrue(eligibility.json()["eligible"])

    def test_backtest_rejects_unapproved_strategy(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        response = client.post(
            "/api/backtests/run",
            json={"strategy": "creative-ai-strategy", "stockCode": "HDFCBANK"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("approved templates", response.json()["detail"])

    def test_live_order_prepare_refuses_in_paper_mode(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        response = client.post(
            "/api/live/orders/prepare",
            json={"stockCode": "HDFCBANK", "strategy": "VWAP pullback"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("TRADING_MODE=live", response.json()["detail"])

    def test_live_order_prepare_respects_allowed_stock_universe(self) -> None:
        client, tempdir, store = make_client(trading_mode="live", static_ip_ready=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.put(
            "/api/settings",
            json={
                "budget": 10000,
                "stopLossPercent": 1.5,
                "dailyMaxLoss": 300,
                "maxTradesPerDay": 3,
                "targetPercent": 3,
                "mode": "intraday",
                "stockPreset": "CUSTOM",
                "allowedStocks": ["HDFCBANK"],
            },
            headers=headers,
        )
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()
        client.post(
            "/api/backtests/run",
            json={"strategy": "VWAP pullback", "stockCode": "HDFCBANK"},
            headers=headers,
        )

        response = client.post(
            "/api/live/orders/prepare",
            json={"stockCode": "RELIANCE", "strategy": "VWAP pullback", "quantity": 1, "price": 1500},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("outside the configured stock universe", response.json()["detail"])

    def test_live_readiness_reports_static_ip_and_mode_blockers(self) -> None:
        client, tempdir, store = make_client(trading_mode="paper", static_ip_ready=False)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        response = client.get("/api/live/readiness", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["readyForManualLiveOrder"])
        self.assertFalse(data["liveMode"])
        self.assertFalse(data["staticIpReady"])
        self.assertIn("TRADING_MODE=live", " ".join(data["blockers"]))
        self.assertIn("registered static IP", " ".join(data["blockers"]))

    def test_manual_live_order_flow_uses_backtest_gate_and_mocked_breeze(self) -> None:
        client, tempdir, store = make_client(trading_mode="live", static_ip_ready=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()
        backtest = client.post(
            "/api/backtests/run",
            json={"strategy": "VWAP pullback", "stockCode": "HDFCBANK"},
            headers=headers,
        )
        self.assertTrue(backtest.json()["passed"])

        prepared = client.post(
            "/api/live/orders/prepare",
            json={"stockCode": "HDFCBANK", "strategy": "VWAP pullback", "quantity": 1, "price": 1500},
            headers=headers,
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
        order_id = prepared.json()["id"]
        self.assertEqual(prepared.json()["status"], "prepared")

        confirmed = client.post(f"/api/live/orders/{order_id}/confirm", headers=headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "submitted")
        self.assertEqual(confirmed.json()["brokerOrderId"], "live-test")
        self.assertEqual(client.app.state.fake_breeze.place_order_calls, 1)

        refreshed = client.post(f"/api/live/orders/{order_id}/refresh", headers=headers)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["status"], "executed")

        squared = client.post(f"/api/live/orders/{order_id}/square-off", headers=headers)
        self.assertEqual(squared.status_code, 200, squared.text)
        self.assertEqual(squared.json()["status"], "square_off_sent")
        self.assertEqual(client.app.state.fake_breeze.square_off_calls, 1)

        orders = client.get("/api/live/orders", headers=headers)
        self.assertEqual(orders.status_code, 200)
        body = json.dumps(orders.json())
        self.assertNotIn("SECRET_SESSION_TOKEN", body)
        self.assertNotIn("APP_KEY_SECRET", body)
        self.assertNotIn("SECRET_KEY_VALUE", body)

    def test_live_autopilot_requires_paper_validation_after_backtest(self) -> None:
        client, tempdir, store = make_client(trading_mode="live", static_ip_ready=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()
        client.post(
            "/api/backtests/run",
            json={"strategy": "VWAP pullback", "stockCode": "HDFCBANK"},
            headers=headers,
        )

        status = client.get("/api/live/autopilot/status", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["eligible"])
        self.assertIn("paper-trading days", status.json()["reason"])

        start = client.post("/api/live/autopilot/start", headers=headers)
        self.assertEqual(start.status_code, 400)
        self.assertIn("paper-trading days", start.json()["detail"])

    def test_improvement_creates_evidence_based_challenger_without_mutating_champion(self) -> None:
        client, tempdir, store = make_client(
            hermes_enabled=True,
            hermes_api_key="KIMI_TEST_KEY",
            self_improvement_enabled=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        client.app.state.fake_breeze.historical_candles["HDFCBANK"] = passing_candles()
        today = current_trading_day()
        with store._lock, store._conn:
            for index, pnl in enumerate((20, -5, 15)):
                store._conn.execute(
                    """
                    INSERT INTO trades (
                        id, stock, side, quantity, entry_price, stop_loss, target,
                        live_pnl, status, mode, strategy, strategy_version,
                        exit_price, pnl, exit_reason, opened_at, closed_at, paper
                    )
                    VALUES (?, 'HDFCBANK', 'BUY', 1, 100, 98.5, 103,
                            ?, 'exited', 'intraday', 'EMA crossover', 'v1',
                            ?, ?, 'Intraday square-off', ?, ?, 1)
                    """,
                    (
                        f"review-trade-{index}",
                        pnl,
                        100 + pnl,
                        pnl,
                        f"{today}T09:30:00+00:00",
                        f"{today}T10:00:00+00:00",
                    ),
                )
        draft = ImprovementReviewDraft(
            summary="EMA entries worked but late exits reduced gains.",
            successes=["Positive EMA trades."],
            mistakes=["Late exits reduced gains."],
            lessons=["Prefer stronger volume confirmation before EMA entries."],
            entryTimingNotes=["Avoid weak-volume entries."],
            exitTimingNotes=["Review exits before forced square-off."],
            challenger=ConstrainedStrategyRule(
                name="EMA volume confirmation",
                description="EMA trend with volume and moderate RSI.",
                conditions=[
                    StrategyRuleCondition(field="liquidity", operator="gt", value=0),
                    StrategyRuleCondition(field="rsi", operator="between", minimum=0, maximum=100),
                ],
                stopLossPercent=1.5,
                targetPercent=3,
            ),
        )
        with patch("backend.app.improvement.is_market_open", return_value=False):
            with patch(
                "backend.app.improvement.SelfImprovementService._request_review",
                return_value=draft,
            ):
                response = client.post("/api/improvement/run-after-market", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "created_challenger")

        versions = client.get("/api/strategy-versions", headers=headers)
        self.assertEqual(versions.status_code, 200)
        self.assertEqual(len(versions.json()), 1)
        champion = client.get("/api/champion", headers=headers)
        self.assertIsNone(champion.json()["champion"])
        self.assertEqual(len(champion.json()["challengers"]), 1)
        lessons = client.get("/api/improvement/lessons", headers=headers)
        self.assertEqual(lessons.status_code, 200)
        self.assertEqual(lessons.json()[0]["evidenceCount"], 1)
        self.assertNotIn("KIMI_TEST_KEY", json.dumps(lessons.json()))

    def test_improvement_failure_creates_no_challenger(self) -> None:
        client, tempdir, store = make_client(
            hermes_enabled=True,
            hermes_api_key="KIMI_TEST_KEY",
            self_improvement_enabled=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        today = current_trading_day()
        with store._lock, store._conn:
            for index in range(3):
                store._conn.execute(
                    """
                    INSERT INTO trades (
                        id, stock, side, quantity, entry_price, stop_loss, target,
                        live_pnl, status, mode, strategy, strategy_version,
                        exit_price, pnl, exit_reason, opened_at, closed_at, paper
                    )
                    VALUES (?, 'HDFCBANK', 'BUY', 1, 100, 98.5, 103,
                            1, 'exited', 'intraday', 'EMA crossover', 'v1',
                            101, 1, 'Target hit', ?, ?, 1)
                    """,
                    (
                        f"failed-review-{index}",
                        f"{today}T09:30:00+00:00",
                        f"{today}T10:00:00+00:00",
                    ),
                )
        with patch("backend.app.improvement.is_market_open", return_value=False):
            with patch(
                "backend.app.improvement.SelfImprovementService._request_review",
                side_effect=ImprovementProviderError("invalid Kimi response"),
            ):
                response = client.post("/api/improvement/run-after-market", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "failed")
        self.assertEqual(client.get("/api/strategy-versions", headers=headers).json(), [])

    def test_improvement_runs_only_once_per_trading_day(self) -> None:
        client, tempdir, store = make_client(
            hermes_enabled=True,
            hermes_api_key="KIMI_TEST_KEY",
            self_improvement_enabled=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        today = current_trading_day()
        with store._lock, store._conn:
            for index in range(3):
                store._conn.execute(
                    """
                    INSERT INTO trades (
                        id, stock, side, quantity, entry_price, stop_loss, target,
                        live_pnl, status, mode, strategy, strategy_version,
                        exit_price, pnl, exit_reason, opened_at, closed_at, paper
                    )
                    VALUES (?, 'HDFCBANK', 'BUY', 1, 100, 98.5, 103,
                            1, 'exited', 'intraday', 'EMA crossover', 'v1',
                            101, 1, 'Target hit', ?, ?, 1)
                    """,
                    (
                        f"once-review-{index}",
                        f"{today}T09:30:00+00:00",
                        f"{today}T10:00:00+00:00",
                    ),
                )
        draft = ImprovementReviewDraft(
            summary="Review completed.",
            lessons=["Require positive trend confirmation."],
        )
        service = client.app.state.improvement_service
        with patch("backend.app.improvement.is_market_open", return_value=False):
            with patch.object(service, "_request_review", return_value=draft) as request_mock:
                first = service.run_daily_review(trading_day=today)
                second = service.run_daily_review(trading_day=today)
        self.assertEqual(first.status, "review_completed")
        self.assertEqual(second.status, "already_completed")
        self.assertEqual(request_mock.call_count, 1)

    def test_improvement_reconciles_stale_state_from_latest_review(self) -> None:
        client, tempdir, store = make_client(self_improvement_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        today = current_trading_day()
        store.save_improvement_review(
            DailyImprovementReview(
                id="failed-review",
                tradingDay=today,
                status="failed",
                summary="Review failed safely.",
                error="Invalid provider response.",
                createdAt=utc_iso(),
            )
        )
        store.update_improvement_state(
            health="running",
            last_review_day=today,
            latest_error=None,
        )

        client.app.state.improvement_service._reconcile_state_from_latest_review()

        state = store.get_improvement_state()
        self.assertEqual(state["health"], "failed")
        self.assertEqual(state["latest_error"], "Invalid provider response.")

    def test_active_lessons_are_supplied_to_kimi_context(self) -> None:
        client, tempdir, store = make_client(hermes_enabled=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = complete_setup(client)
        store.replace_review_lessons(
            "review-id",
            ["Avoid EMA entries without volume confirmation."],
        )
        captured: dict[str, object] = {}

        def decide(context):
            captured.update(context)
            return AgentDecisionDraft(
                action="SKIP",
                confidence=0.4,
                reasons=["No clean setup."],
                risks=["Signals are mixed."],
            )

        with patch("backend.app.agent.HermesClient.decide", side_effect=decide):
            response = client.post("/api/agent/paper-cycle", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            captured["learnedLessons"][0]["text"],
            "Avoid EMA entries without volume confirmation.",
        )

    def test_constrained_strategy_rejects_executable_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ConstrainedStrategyRule.model_validate(
                {
                    "name": "Unsafe generated rule",
                    "description": "Attempts to include executable content.",
                    "conditions": [
                        {"field": "trend", "operator": "gt", "value": 0},
                        {"field": "rsi", "operator": "between", "minimum": 40, "maximum": 60},
                    ],
                    "stopLossPercent": 1,
                    "targetPercent": 2,
                    "code": "place_market_order()",
                }
            )

    def test_improvement_parser_accepts_wrapped_aliases(self) -> None:
        raw = _decode_review_content(
            """
            Review result:
            ```json
            {
              "review": {
                "summary": "Reviewed three trades.",
                "successes": "Risk limits held.",
                "mistakes": ["Late exit."],
                "lessons": "Use volume confirmation.",
                "entry_timing_notes": ["Avoid weak opens."],
                "exit_timing_notes": [],
                "newStrategy": null
              }
            }
            ```
            """
        )
        review = ImprovementReviewDraft.model_validate(raw)
        self.assertEqual(review.successes, ["Risk limits held."])
        self.assertEqual(review.lessons, ["Use volume confirmation."])

    def test_challenger_requires_shadow_gate_before_auto_promotion(self) -> None:
        client, tempdir, store = make_client(
            self_improvement_enabled=True,
            auto_challenger_promotion=True,
        )
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)
        headers = register_user(client)
        version = StrategyVersion(
            id="shadow-candidate",
            strategy="Adaptive: volume trend",
            version="challenger-test",
            parameters={},
            backtestMetrics={
                "profitFactor": 1.4,
                "maxDrawdown": 5,
                "winRate": 52,
                "tradesCount": 120,
            },
            paperMetrics={},
            riskNotes=["Test candidate"],
            promotionStatus="backtested",
            createdAt=utc_iso(),
        )
        store.save_strategy_version(version)
        validation = client.get(
            "/api/strategy-versions/shadow-candidate/validation",
            headers=headers,
        )
        self.assertEqual(validation.status_code, 200)
        self.assertFalse(validation.json()["eligibleForPromotion"])
        client.app.state.improvement_service.evaluate_and_promote("shadow-candidate")
        self.assertIsNone(store.current_champion())

    def test_champion_promotion_and_rollback_require_better_challenger(self) -> None:
        client, tempdir, store = make_client()
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = register_user(client)
        now = utc_iso()
        store.save_strategy_version(
            StrategyVersion(
                id="champion-candidate",
                strategy="VWAP pullback",
                version="v1",
                parameters={},
                backtestMetrics={"profitFactor": 1.3, "maxDrawdown": 5, "winRate": 55, "tradesCount": 120},
                paperMetrics={},
                riskNotes=["Initial candidate"],
                promotionStatus="candidate",
                createdAt=now,
            )
        )
        first = client.post("/api/challengers/champion-candidate/promote", headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["promotionStatus"], "champion")

        store.save_strategy_version(
            StrategyVersion(
                id="better-candidate",
                strategy="VWAP pullback",
                version="v2",
                parameters={},
                backtestMetrics={"profitFactor": 1.45, "maxDrawdown": 4, "winRate": 58, "tradesCount": 130},
                paperMetrics={},
                riskNotes=["Better candidate"],
                promotionStatus="candidate",
                createdAt=utc_iso(),
            )
        )
        second = client.post("/api/challengers/better-candidate/promote", headers=headers)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["promotionStatus"], "champion")

        rollback = client.post("/api/champion/rollback", headers=headers)
        self.assertEqual(rollback.status_code, 200, rollback.text)
        self.assertEqual(rollback.json()["id"], "champion-candidate")

    def test_health_safety_kill_switch_audit_and_report_are_redacted(self) -> None:
        client, tempdir, store = make_client(trading_mode="live", static_ip_ready=True)
        self.addCleanup(store.close)
        self.addCleanup(tempdir.cleanup)

        headers = complete_setup(client)
        health = client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        safety = client.get("/api/safety/status", headers=headers)
        self.assertEqual(safety.status_code, 200)
        self.assertTrue(safety.json()["liveMode"])

        killed = client.post("/api/safety/kill-switch", headers=headers)
        self.assertEqual(killed.status_code, 200)
        self.assertTrue(killed.json()["killSwitchActive"])

        report = client.post("/api/reports/daily/send", headers=headers)
        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.json()["ok"])

        audit = client.get("/api/audit", headers=headers)
        self.assertEqual(audit.status_code, 200)
        body = json.dumps(
            {
                "health": health.json(),
                "safety": killed.json(),
                "report": report.json(),
                "audit": audit.json(),
            }
        )
        self.assertIn("safety.kill_switch", body)
        self.assertNotIn("RAW_SESSION_KEY", body)
        self.assertNotIn("SECRET_SESSION_TOKEN", body)
        self.assertNotIn("APP_KEY_SECRET", body)
        self.assertNotIn("SECRET_KEY_VALUE", body)


class RateLimiterTests(unittest.TestCase):
    def test_rate_limit_guard_blocks_over_limit(self) -> None:
        limiter = RateLimiter(api_per_minute=1, api_per_day=2, order_actions_per_second=1)
        limiter.record_api_call()
        with self.assertRaises(RateLimitError):
            limiter.record_api_call()

        limiter.record_order_action()
        with self.assertRaises(RateLimitError):
            limiter.record_order_action()


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, object],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> dict[str, object]:
        return self.payload


class BreezeClientTests(unittest.TestCase):
    def make_breeze_client(self, *, static_ip_ready: bool = True) -> BreezeClient:
        return BreezeClient(
            AppConfig(
                database_path=":memory:",
                encryption_key_path="/tmp/breezepilot-test-fernet.key",
                trading_mode="live",
                breeze_app_key="APP_KEY_SECRET",
                breeze_secret_key="SECRET_KEY_VALUE",
                static_ip_ready=static_ip_ready,
                enforce_market_hours=False,
            ),
            RateLimiter(),
        )

    def test_signed_request_headers_and_quote_mapping(self) -> None:
        client = self.make_breeze_client()
        captured: dict[str, object] = {}

        def fake_request(method: str, url: str, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            captured["data"] = kwargs["data"]
            return FakeResponse(
                {
                    "Success": [
                        {
                            "stock_code": "HDFCBANK",
                            "exchange_code": "NSE",
                            "ltp": "1500.5",
                            "open": "1490",
                            "high": "1510",
                            "low": "1480",
                            "volume": "10000",
                        }
                    ],
                    "Status": 200,
                    "Error": None,
                }
            )

        with patch("backend.app.breeze.requests.request", side_effect=fake_request):
            quote = client.get_quote("SESSION_TOKEN_SECRET", "hdfcbank")

        self.assertEqual(quote.stock_code, "HDFCBANK")
        self.assertEqual(quote.exchange_code, "NSE")
        self.assertEqual(quote.last_price, 1500.5)
        headers = captured["headers"]
        self.assertEqual(headers["X-AppKey"], "APP_KEY_SECRET")
        self.assertEqual(headers["X-SessionToken"], "SESSION_TOKEN_SECRET")
        self.assertTrue(headers["X-Checksum"].startswith("token "))
        self.assertIn("/quotes", captured["url"])
        self.assertIn('"stock_code":"HDFBAN"', captured["data"])

    def test_read_request_retries_once_after_503_and_records_recovery(self) -> None:
        client = self.make_breeze_client()
        responses = iter(
            [
                FakeResponse({}, status_code=503, headers={"Retry-After": "0"}),
                FakeResponse(
                    {
                        "Success": [
                            {
                                "stock_code": "HDFBAN",
                                "exchange_code": "NSE",
                                "ltp": "1500.5",
                            }
                        ],
                        "Status": 200,
                        "Error": None,
                    }
                ),
            ]
        )

        with patch(
            "backend.app.breeze.requests.request",
            side_effect=lambda *args, **kwargs: next(responses),
        ) as request_mock:
            with patch("backend.app.breeze.time.sleep") as sleep_mock:
                quote = client.get_quote("SESSION_TOKEN_SECRET", "HDFCBANK")

        self.assertEqual(quote.last_price, 1500.5)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once()
        notices = client.consume_recovery_notices()
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].endpoint, "/quotes")

    def test_order_changing_request_is_not_retried_after_503(self) -> None:
        client = self.make_breeze_client(static_ip_ready=True)
        with patch(
            "backend.app.breeze.requests.request",
            return_value=FakeResponse({}, status_code=503),
        ) as request_mock:
            with self.assertRaises(BreezeClientError):
                client.place_order(
                    "SESSION_TOKEN_SECRET",
                    {
                        "stock_code": "HDFCBANK",
                        "exchange_code": "NSE",
                        "product_type": "cash",
                        "quantity": 1,
                        "price": 1500,
                        "action": "buy",
                        "order_type": "limit",
                    },
                )

        self.assertEqual(request_mock.call_count, 1)

    def test_breeze_response_mapping_for_core_methods(self) -> None:
        client = self.make_breeze_client()
        responses = iter(
            [
                {"Success": [{"datetime": "2026-06-15", "open": "1", "high": "2", "low": "1", "close": "2", "volume": "10"}]},
                {
                    "Success": {
                        "total_bank_balance": "1000",
                        "allocated_equity": "500",
                        "block_by_trade_equity": "10",
                        "unallocated_balance": "490",
                    }
                },
                {"Success": [{"stock_code": "HDFBAN", "stock_ISIN": "INE", "quantity": "2"}]},
                {"Success": [{"stock_code": "HDFBAN", "product_type": "cash", "quantity": "2"}]},
                {"Success": [{"order_id": "OID-1", "stock_code": "HDFBAN", "orderStatus": "ordered"}]},
                {"Success": [{"trade_id": "TID-1", "order_id": "OID-1", "stock_code": "HDFBAN"}]},
                {"Success": {"order_id": "SQ-1", "message": "Successfully Placed the order"}},
            ]
        )

        def fake_request(method: str, url: str, **kwargs):
            return FakeResponse(next(responses))

        with patch("backend.app.breeze.requests.request", side_effect=fake_request):
            candles = client.get_historical_candles(
                "SESSION_TOKEN_SECRET",
                stock_code="HDFCBANK",
                from_date="2026-06-10T00:00:00.000Z",
                to_date="2026-06-15T00:00:00.000Z",
            )
            funds = client.get_funds("SESSION_TOKEN_SECRET")
            holdings = client.get_holdings("SESSION_TOKEN_SECRET")
            positions = client.get_positions("SESSION_TOKEN_SECRET")
            orders = client.get_order_list("SESSION_TOKEN_SECRET")
            trades = client.get_trade_list("SESSION_TOKEN_SECRET")
            square_off = client.square_off(
                "SESSION_TOKEN_SECRET",
                {
                    "stock_code": "HDFCBANK",
                    "exchange_code": "NSE",
                    "product_type": "cash",
                    "quantity": 1,
                    "price": 1500,
                    "action": "sell",
                    "order_type": "limit",
                },
            )

        self.assertEqual(candles[0].close, 2)
        self.assertEqual(funds.allocated_equity, 500)
        self.assertEqual(holdings[0].stock_code, "HDFCBANK")
        self.assertEqual(len(holdings), 1)
        self.assertEqual(positions[0].stock_code, "HDFCBANK")
        self.assertEqual(positions[0].product_type, "cash")
        self.assertEqual(orders[0].stock_code, "HDFCBANK")
        self.assertEqual(orders[0].order_id, "OID-1")
        self.assertEqual(trades[0].stock_code, "HDFCBANK")
        self.assertEqual(trades[0].trade_id, "TID-1")
        self.assertEqual(square_off.order_id, "SQ-1")

    def test_live_order_actions_reject_unsafe_inputs_before_http(self) -> None:
        no_static_ip = self.make_breeze_client(static_ip_ready=False)
        with patch("backend.app.breeze.requests.request") as request_mock:
            with self.assertRaises(BreezeClientError):
                no_static_ip.place_order(
                    "SESSION_TOKEN_SECRET",
                    {
                        "stock_code": "HDFCBANK",
                        "exchange_code": "NSE",
                        "product_type": "cash",
                        "quantity": 1,
                        "price": 1500,
                        "action": "buy",
                        "order_type": "limit",
                    },
                )
            request_mock.assert_not_called()

        client = self.make_breeze_client(static_ip_ready=True)
        unsafe_payloads = [
            {"stock_code": "HDFCBANK", "exchange_code": "NSE", "product_type": "cash", "order_type": "market"},
            {"stock_code": "NIFTY25JUNFUT", "exchange_code": "NSE", "product_type": "cash", "order_type": "limit"},
            {"stock_code": "HDFCBANK", "exchange_code": "NFO", "product_type": "cash", "order_type": "limit"},
            {"stock_code": "HDFCBANK", "exchange_code": "NSE", "product_type": "futures", "order_type": "limit"},
        ]
        for payload in unsafe_payloads:
            with patch("backend.app.breeze.requests.request") as request_mock:
                with self.assertRaises(BreezeClientError):
                    client.place_order("SESSION_TOKEN_SECRET", payload)
                request_mock.assert_not_called()

    def test_cash_order_uses_breeze_symbol_and_product_field(self) -> None:
        client = self.make_breeze_client(static_ip_ready=True)
        captured: dict[str, object] = {}

        def fake_request(method: str, url: str, **kwargs):
            captured["body"] = json.loads(kwargs["data"])
            return FakeResponse(
                {
                    "Success": {"order_id": "OID-1", "message": "Successfully Placed the order"},
                    "Status": 200,
                    "Error": None,
                }
            )

        with patch("backend.app.breeze.requests.request", side_effect=fake_request):
            order = client.place_order(
                "SESSION_TOKEN_SECRET",
                {
                    "stock_code": "HDFCBANK",
                    "exchange_code": "NSE",
                    "product_type": "cash",
                    "quantity": 1,
                    "price": 800,
                    "action": "buy",
                    "order_type": "limit",
                },
            )

        self.assertEqual(captured["body"]["stock_code"], "HDFBAN")
        self.assertEqual(captured["body"]["product"], "cash")
        self.assertNotIn("product_type", captured["body"])
        self.assertEqual(order.stock_code, "HDFCBANK")

    def test_empty_broker_collections_are_not_errors(self) -> None:
        client = self.make_breeze_client()
        responses = iter(
            [
                {"Success": None, "Status": 200, "Error": "No Holdings available."},
                {"Success": None, "Status": 200, "Error": "No Positions available."},
                {"Success": None, "Status": 200, "Error": "No Orders available."},
                {"Success": None, "Status": 200, "Error": "No Trades available."},
            ]
        )

        with patch(
            "backend.app.breeze.requests.request",
            side_effect=lambda *args, **kwargs: FakeResponse(next(responses)),
        ):
            self.assertEqual(client.get_holdings("SESSION_TOKEN_SECRET"), [])
            self.assertEqual(client.get_positions("SESSION_TOKEN_SECRET"), [])
            self.assertEqual(client.get_order_list("SESSION_TOKEN_SECRET"), [])
            self.assertEqual(client.get_trade_list("SESSION_TOKEN_SECRET"), [])


if __name__ == "__main__":
    unittest.main()
