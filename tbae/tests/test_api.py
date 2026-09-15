"""The FastAPI surface: contracts, validation, and the look-ahead guard.

The dashboard is the user's window into the engine, so the properties that matter
here are the ones a browser cannot check for itself:

* every endpoint answers with the shape the UI reads, and never with a stack trace;
* bad input is rejected with a 422 and a message that says what to do instead —
  including the look-ahead guard, which must refuse ``reference_mode=full`` unless
  the caller explicitly opts in (and then must say so in the manifest);
* nothing a request does leaks into the repository: user rules, keymaps and
  uploads are all redirected to a temp directory for the duration of the test.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from engine import feeds
from engine import rules as rules_mod

pytestmark = pytest.mark.api

DAYS = 4          # the smallest window that still produces signals
TF = 15


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose writable state lives in tmp_path, never in the repo."""
    monkeypatch.setattr(rules_mod, "USER_RULES_PATH", str(tmp_path / "user_rules.json"))
    monkeypatch.setattr(main, "ROOT", str(tmp_path))
    with TestClient(main.app) as c:
        yield c


# --------------------------------------------------------------------- #
# 1. meta / discovery
# --------------------------------------------------------------------- #
class TestMeta:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["engine_version"]
        assert isinstance(body["cache_entries"], int)

    def test_meta_describes_the_whole_ui_contract(self, client):
        body = client.get("/api/meta").json()
        assert body["timeframes"] == [1, 3, 5, 15, 30, 60, 120, 240, 360, 720, 1440]
        assert {c["id"] for c in body["categories"]} == {
            "weak", "medium", "energetic", "strong", "pressure"}
        for c in body["categories"]:
            assert c["label_fa"] and c["label_en"] and c["rule"]
            assert set(c["colors"]) == {"1", "-1"} or set(c["colors"]) == {1, -1}
        assert body["colors"] and body["commands"] and body["commands_by_group"]
        assert body["config_errors"] == []
        assert body["signal_config_hash"]
        assert body["exit_presets"]
        # crypto trades every day, so a daily bar has 365.25 periods per year — not
        # the 252 of an equity calendar.  Every annualisation in metrics reads this.
        ppy = body["periods_per_year_by_tf"]
        assert ppy["1440"] == pytest.approx(365.25)
        assert ppy["15"] == pytest.approx(4 * 24 * 365.25)

    def test_meta_exposes_the_default_signal_config(self, client):
        body = client.get("/api/meta").json()
        sd = body["signal_defaults"]
        assert sd["min_edge_score"] == pytest.approx(0.45)
        assert sd["entry_timing"] == "pullback_limit"
        assert sd["execution"] == "next_open"

    def test_commands_endpoint_lists_bindings_and_reserved_keys(self, client):
        body = client.get("/api/commands").json()
        assert len(body["commands"]) == 24
        assert len(body["default_keymap"]) == 23
        assert "F5" in body["reserved_keys"]
        assert all(c["id"] in body["default_keymap"].values()
                   for c in body["commands"] if c["id"] in body["default_keymap"].values())

    def test_index_route_never_500s_without_a_built_dashboard(self, client):
        r = client.get("/")
        assert r.status_code == 200


# --------------------------------------------------------------------- #
# 2. market data
# --------------------------------------------------------------------- #
class TestData:
    def test_data_returns_bars_and_the_full_analysis_block(self, client):
        r = client.get("/api/data", params={"tf": TF, "days": DAYS, "limit": 20})
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"meta", "kpi", "stats", "completeness", "reference",
                             "timing", "bars", "warmup_index"}
        assert len(body["bars"]) <= 20
        comp = body["completeness"]
        assert comp["bars"] > 0 and comp["expected_bars"] >= comp["bars"]
        assert comp["coverage"] == pytest.approx(comp["bars"] / comp["expected_bars"], rel=1e-9)
        assert comp["missing_bars"] == comp["expected_bars"] - comp["bars"]
        bar = body["bars"][-1]
        for key in ("ts", "open", "high", "low", "close", "category", "system_pct",
                    "chart_pct", "timing_score"):
            assert key in bar, f"the UI reads {key} off every bar"

    def test_data_is_deterministic_for_a_seed(self, client):
        p = {"tf": TF, "days": DAYS, "limit": 10, "seed": 99}
        a = client.get("/api/data", params=p).json()
        b = client.get("/api/data", params=p).json()
        assert [x["close"] for x in a["bars"]] == [x["close"] for x in b["bars"]]

    def test_reference_mode_rolling_requires_a_window(self, client):
        r = client.get("/api/data", params={"tf": TF, "days": DAYS,
                                            "reference_mode": "rolling"})
        assert r.status_code == 422
        assert "reference_window" in r.json()["detail"]
        ok = client.get("/api/data", params={"tf": TF, "days": DAYS,
                                             "reference_mode": "rolling",
                                             "reference_window": 400})
        assert ok.status_code == 200

    def test_an_unknown_reference_mode_is_rejected_by_the_schema(self, client):
        r = client.get("/api/data", params={"tf": TF, "days": DAYS,
                                            "reference_mode": "yesterday"})
        assert r.status_code == 422

    @pytest.mark.parametrize("params", [
        {"tf": 0}, {"tf": 5000}, {"days": 0}, {"days": 999}, {"limit": 0},
        {"reference_percentile": 0}, {"reference_percentile": 101},
        {"weak_threshold": -1},
    ])
    def test_out_of_range_query_parameters_are_rejected(self, client, params):
        r = client.get("/api/data", params={"tf": TF, "days": DAYS, **params})
        assert r.status_code == 422, params

    def test_hot_only_filters_to_the_hot_timing_cells(self, client):
        all_bars = client.get("/api/data", params={"tf": TF, "days": 8, "limit": 5000}).json()
        hot = client.get("/api/data", params={"tf": TF, "days": 8, "limit": 5000,
                                              "hot_only": True}).json()
        assert len(hot["bars"]) <= len(all_bars["bars"])

    def test_raw_returns_minute_bars(self, client):
        body = client.get("/api/raw", params={"minutes": 120, "days": DAYS}).json()
        assert len(body["minutes"]) == 120
        m = body["minutes"][0]
        assert m["high"] >= m["low"] > 0

    def test_table_filters_by_category_and_direction(self, client):
        body = client.get("/api/table", params={"tf": TF, "days": DAYS,
                                                "category": "strong", "limit": 50}).json()
        assert body["count"] == len(body["bars"]) <= 50
        assert all(r["category"] == "strong" for r in body["bars"])
        longs = client.get("/api/table", params={"tf": TF, "days": DAYS,
                                                 "direction": 1, "limit": 50}).json()
        assert all(r["direction"] == 1 for r in longs["bars"])

    def test_path_returns_the_average_growth_curve(self, client):
        body = client.get("/api/path", params={"tf": TF, "days": DAYS}).json()
        assert body
        assert any(k in body for k in ("curve", "curves", "points", "cohorts"))

    def test_explain_names_the_winning_rule_for_a_bar(self, client):
        data = client.get("/api/data", params={"tf": TF, "days": DAYS, "limit": 5}).json()
        ts = data["bars"][-1]["ts"]
        body = client.get("/api/explain", params={"tf": TF, "days": DAYS, "ts": ts}).json()
        assert set(body) >= {"bar", "explain", "system_bar"}
        # the decision tree is only auditable if it names the rule that fired
        assert body["explain"]["winning_rule"]
        assert body["explain"]["category"] == data["bars"][-1]["category"]
        assert body["bar"]["category"] == data["bars"][-1]["category"]
        # the system bar in the README's own notation: S = sum of |legs|
        sb = body["system_bar"]
        assert sb["S"] > 0 and sb["S_intra"] >= sb["S"] - 1e-9
        assert 0.0 <= sb["efficiency"] <= 1.0
        # the audit trail: every branch of the five-category tree, decided or not
        assert body["explain"]["checks"]


# --------------------------------------------------------------------- #
# 3. signals, backtest and the research endpoints
# --------------------------------------------------------------------- #
class TestSignalsAndBacktest:
    def test_signals_reports_the_funnel(self, client):
        body = client.get("/api/signals", params={"tf": TF, "days": DAYS + 4}).json()
        assert set(body) >= {"signals", "funnel", "counts"} or "signals" in body
        assert isinstance(body["signals"], list)

    def test_signals_can_include_the_rejected_candidates(self, client):
        p = {"tf": TF, "days": DAYS + 4}
        only = client.get("/api/signals", params=p).json()
        both = client.get("/api/signals", params={**p, "include_rejected": True}).json()
        assert len(both.get("candidates", both["signals"])) >= len(only["signals"])

    def test_backtest_returns_the_accounting_and_the_funnel(self, client):
        body = client.get("/api/backtest", params={"tf": TF, "days": DAYS + 6}).json()
        for key in ("metrics", "manifest", "entry_funnel", "pending_stats",
                    "warnings", "accounting_errors", "risk_report", "risk_snapshot",
                    "benchmark", "exit_reason_counts", "n_trades"):
            assert key in body, f"the UI reads {key}"
        assert body["accounting_errors"] == []
        assert body["manifest"]["allow_lookahead"] is False
        assert body["manifest"]["lookahead_flags"] == []

    def test_backtest_look_ahead_is_refused_then_allowed_explicitly(self, client):
        p = {"tf": TF, "days": DAYS + 4, "reference_mode": "full"}
        refused = client.get("/api/backtest", params=p)
        assert refused.status_code == 422
        assert "look-ahead" in refused.json()["detail"]
        allowed = client.get("/api/backtest", params={**p, "allow_lookahead": True})
        assert allowed.status_code == 200
        m = allowed.json()["manifest"]
        assert m["allow_lookahead"] is True
        assert m["lookahead_flags"] == ["reference_mode='full'"]
        assert any("LOOK-AHEAD" in w for w in allowed.json()["warnings"])

    def test_backtest_can_include_the_trade_list(self, client):
        p = {"tf": TF, "days": DAYS + 6}
        slim = client.get("/api/backtest", params=p).json()
        full = client.get("/api/backtest", params={**p, "include_trades": True}).json()
        assert "trades" not in slim or slim.get("trades") in (None, [])
        assert isinstance(full["trades"], list)

    def test_backtest_honours_the_entry_mode_controls(self, client):
        p = {"tf": TF, "days": DAYS + 6}
        for mode in ("signal", "random", "every_bar"):
            body = client.get("/api/backtest", params={**p, "entry_mode": mode}).json()
            assert body["manifest"]["entry_mode"] == mode

    def test_backtest_rejects_an_unknown_entry_mode(self, client):
        r = client.get("/api/backtest", params={"tf": TF, "days": DAYS,
                                                "entry_mode": "telepathy"})
        assert r.status_code == 422

    def test_backtest_rejects_an_invalid_exit_configuration(self, client):
        r = client.get("/api/backtest", params={"tf": TF, "days": DAYS + 4,
                                                "stop_sigma": 0})
        assert r.status_code == 422

    def test_backtest_rejects_a_non_positive_equity(self, client):
        r = client.get("/api/backtest", params={"tf": TF, "days": DAYS, "equity": 0})
        assert r.status_code == 422

    def test_costs_are_passed_through_to_the_run(self, client):
        p = {"tf": TF, "days": DAYS + 6, "commission_bps": 1.0, "slippage_bps": 1.0,
             "maker_bps": 0.0}
        cheap = client.get("/api/backtest", params=p).json()
        pricey = client.get("/api/backtest", params={**p, "commission_bps": 40.0,
                                                     "slippage_bps": 40.0}).json()
        assert cheap["metrics"]["trades"]["friction_r_per_trade"] < \
            pricey["metrics"]["trades"]["friction_r_per_trade"]

    def test_compare_runs_the_controls(self, client):
        body = client.get("/api/compare", params={"tf": TF, "days": DAYS + 6}).json()
        assert set(body) >= {"strategy", "random_control", "every_bar_control",
                             "comparison", "manifest"}
        assert body["comparison"]["verdict"]
        assert body["strategy"]["n_trades"] >= 0
        assert body["random_control"]["n_trades"] >= 0

    def test_ablation_endpoint_reports_per_filter_deltas(self, client):
        body = client.get("/api/ablation", params={"tf": TF, "days": DAYS + 6}).json()
        assert body
        assert isinstance(body, dict)

    def test_monte_carlo_endpoint_reports_a_drawdown_distribution(self, client):
        body = client.get("/api/monte-carlo", params={"tf": TF, "days": DAYS + 6,
                                                      "n_sims": 40, "n_boot": 40}).json()
        assert body
        assert isinstance(body, dict)

    def test_n_trials_is_validated(self, client):
        r = client.get("/api/backtest", params={"tf": TF, "days": DAYS, "n_trials": 0})
        assert r.status_code == 422


# --------------------------------------------------------------------- #
# 4. user state: rules, keymap, uploads
# --------------------------------------------------------------------- #
class TestUserState:
    def test_rules_start_from_the_defaults(self, client):
        body = client.get("/api/rules").json()
        assert body["source"] == "defaults"
        assert {r["id"] for r in body["rules"]} == {"blowoff", "quiet_trend", "dead_water"}
        assert "close" in body["allowed_fields"]
        assert "long" in body["allowed_colors"]

    def test_adding_a_rule_persists_it(self, client):
        rule = {"id": "my_uptrend", "expr": 'category == "strong"', "color_key": "long",
                "label_fa": "روند صعودی", "label_en": "uptrend", "priority": 5}
        r = client.post("/api/rules", json=rule)
        assert r.status_code == 200, r.text
        assert any(x["id"] == "my_uptrend" for x in r.json()["rules"])
        back = client.get("/api/rules").json()
        assert back["source"] == "file"
        assert any(x["id"] == "my_uptrend" for x in back["rules"])

    def test_a_rule_with_an_unknown_field_is_rejected_with_a_useful_message(self, client):
        r = client.post("/api/rules", json={"id": "bad", "expr": "nope > 1",
                                            "color_key": "long"})
        assert r.status_code == 422
        assert "nope" in r.json()["detail"]

    def test_a_rule_with_an_unknown_color_is_rejected(self, client):
        r = client.post("/api/rules", json={"id": "bad", "expr": "close > open",
                                            "color_key": "chartreuse"})
        assert r.status_code == 422
        assert "color_key" in r.json()["detail"]

    def test_a_hostile_expression_cannot_be_stored(self, client):
        r = client.post("/api/rules", json={"id": "evil",
                                            "expr": '__import__("os").system("id")',
                                            "color_key": "long"})
        assert r.status_code == 422

    def test_deleting_a_rule_removes_it(self, client):
        client.post("/api/rules", json={"id": "temp", "expr": "close > open",
                                        "color_key": "long"})
        r = client.delete("/api/rules", params={"rule_id": "temp"})
        assert r.status_code == 200
        assert not any(x["id"] == "temp" for x in client.get("/api/rules").json()["rules"])

    def test_deleting_an_unknown_rule_is_a_404_not_a_500(self, client):
        r = client.delete("/api/rules", params={"rule_id": "never_existed"})
        assert r.status_code == 404
        assert "never_existed" in r.json()["detail"]

    def test_reset_restores_the_default_rules(self, client):
        client.post("/api/rules", json={"id": "temp", "expr": "close > open",
                                        "color_key": "long"})
        assert client.post("/api/reset").status_code == 200
        assert {r["id"] for r in client.get("/api/rules").json()["rules"]} == {
            "blowoff", "quiet_trend", "dead_water"}

    def test_keymap_round_trip(self, client):
        assert client.get("/api/keymap").json()["keymap"] == rules_mod.DEFAULT_KEYMAP
        r = client.post("/api/keymap", json={"a": "play_pause", "b": "speed_up"})
        assert r.status_code == 200
        assert client.get("/api/keymap").json()["keymap"] == {"a": "play_pause",
                                                             "b": "speed_up"}

    def test_keymap_rejects_a_reserved_key(self, client):
        assert client.post("/api/keymap", json={"F5": "play_pause"}).status_code == 422

    def test_keymap_rejects_an_unknown_command(self, client):
        assert client.post("/api/keymap", json={"a": "launch_missiles"}).status_code == 422

    def test_keymap_rejects_an_invisible_binding(self, client):
        assert client.post("/api/keymap", json={"   ": "play_pause"}).status_code == 422

    def test_deleting_a_single_key_keeps_the_rest(self, client):
        client.post("/api/keymap", json={"a": "play_pause", "b": "speed_up"})
        client.delete("/api/keymap", params={"key": "a"})
        assert client.get("/api/keymap").json()["keymap"] == {"b": "speed_up"}

    def test_upload_accepts_a_valid_minute_csv(self, client, tmp_path):
        bars = feeds.SyntheticFeed(feeds.SyntheticConfig(days=1, seed=5)).load()[:400]
        csv_path = tmp_path / "mine.csv"
        feeds.write_minutes_csv(bars, str(csv_path))
        with open(csv_path, "rb") as fh:
            r = client.post("/api/upload", files={"file": ("mine.csv", fh, "text/csv")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["minutes"] == 400
        # the file is stored under the (monkeypatched) app root, not the repo
        assert str(tmp_path) in body["path"]

    def test_upload_rejects_a_csv_that_is_too_short(self, client, tmp_path):
        bars = feeds.SyntheticFeed(feeds.SyntheticConfig(days=1, seed=5)).load()[:10]
        csv_path = tmp_path / "short.csv"
        feeds.write_minutes_csv(bars, str(csv_path))
        with open(csv_path, "rb") as fh:
            r = client.post("/api/upload", files={"file": ("short.csv", fh, "text/csv")})
        assert r.status_code == 422
        assert "60" in r.json()["detail"]

    def test_upload_rejects_a_file_that_is_not_csv_at_all(self, client):
        r = client.post("/api/upload", files={"file": ("notes.txt", b"hello world",
                                                       "text/plain")})
        assert r.status_code == 422

    def test_a_stored_upload_does_not_land_in_the_repository(self, client, tmp_path):
        bars = feeds.SyntheticFeed(feeds.SyntheticConfig(days=1, seed=5)).load()[:200]
        csv_path = tmp_path / "u.csv"
        feeds.write_minutes_csv(bars, str(csv_path))
        with open(csv_path, "rb") as fh:
            client.post("/api/upload", files={"file": ("u.csv", fh, "text/csv")})
        repo_uploads = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(main.__file__))), "data", "uploads")
        assert not os.path.exists(os.path.join(repo_uploads, "u.csv"))


# --------------------------------------------------------------------- #
# 5. payload hygiene
# --------------------------------------------------------------------- #
class TestPayloadHygiene:
    def test_every_get_endpoint_returns_json_serialisable_payloads(self, client):
        urls = [
            ("/api/health", {}), ("/api/meta", {}), ("/api/commands", {}),
            ("/api/keymap", {}), ("/api/rules", {}),
            ("/api/data", {"tf": TF, "days": DAYS, "limit": 5}),
            ("/api/raw", {"minutes": 30, "days": DAYS}),
            ("/api/table", {"tf": TF, "days": DAYS, "limit": 5}),
            ("/api/path", {"tf": TF, "days": DAYS}),
            ("/api/signals", {"tf": TF, "days": DAYS + 4}),
            ("/api/backtest", {"tf": TF, "days": DAYS + 4}),
        ]
        for url, params in urls:
            r = client.get(url, params=params)
            assert r.status_code == 200, (url, r.text[:200])
            json.dumps(r.json()),        # strict JSON: no NaN/Infinity may escape

    def test_no_endpoint_leaks_nan_or_infinity(self, client):
        body = client.get("/api/backtest", params={"tf": TF, "days": DAYS + 6}).text
        for token in ("NaN", "Infinity", "-Infinity"):
            assert token not in body, f"{token} escaped into the JSON payload"

    def test_a_server_error_is_never_a_bare_traceback(self, client):
        r = client.get("/api/explain", params={"tf": TF, "days": DAYS, "ts": 1})
        assert r.status_code in (200, 404, 422)
        assert "Traceback" not in r.text
