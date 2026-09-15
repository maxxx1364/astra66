"""The user-facing rule language: it must be expressive, safe, and persistent.

These rules are compiled from strings a user types into a dashboard, so the
interesting properties are not "does a valid expression work" but:

* an invalid or hostile expression is rejected with a message that names the
  problem (a rule that silently never matches is indistinguishable from a market
  that never sets up);
* nothing but arithmetic on whitelisted bar fields can be evaluated — no imports,
  no builtins, no attribute access, no file handles;
* priority, enable/disable and id-replacement behave the way the UI claims;
* what is saved is what is loaded back, and a corrupt file degrades to the
  defaults with the errors reported instead of crashing the app.
"""
from __future__ import annotations

import json
import os

import pytest

from engine import rules as R
from engine.models import Bar, Category


@pytest.fixture
def bar() -> Bar:
    b = Bar(ts=1_767_225_600_000, open=100.0, high=140.0, low=99.0, close=138.0,
            volume=10.0, tf=15)
    b.chart_pct = 190.0
    b.system_pct = 160.0
    b.efficiency = 0.85
    b.vol_regime = 1.2
    b.category = Category.STRONG
    return b                                    # direction is a derived property


@pytest.fixture
def tmp_rules(tmp_path, monkeypatch):
    """Point the user-rules file at a temp dir so tests never touch the repo."""
    p = str(tmp_path / "user_rules.json")
    monkeypatch.setattr(R, "USER_RULES_PATH", p)
    return p


# --------------------------------------------------------------------- #
# 1. the expression compiler
# --------------------------------------------------------------------- #
class TestCompileExpr:
    @pytest.mark.parametrize("expr,expected", [
        ('category == "strong"', True),
        ('category != "strong"', False),
        ("system_pct > 150", True),
        ("system_pct >= 160", True),
        ("system_pct < 150", False),
        ("close > open", True),
        ("efficiency > 0.7 and chart_pct >= 55", True),
        ("efficiency > 0.9 or chart_pct > 180", True),
        ("not efficiency > 0.9", True),
        ("direction == 1", True),
        ("vol_regime >= 0.5 and vol_regime <= 2.0", True),
    ])
    def test_valid_expressions_evaluate(self, bar, expr, expected):
        assert R.compile_expr(expr)(bar) is expected

    @pytest.mark.parametrize("expr", ["(high - low) / close > 0.1", "close - open > 30",
                                      "close * 2 > 200", "high + low > 0"])
    def test_arithmetic_is_rejected_and_says_what_is_supported(self, expr):
        """The language is comparisons + and/or/not + parentheses on purpose: a
        user-typed formula that evaluates to something nobody intended is worse
        than one that is refused."""
        with pytest.raises(ValueError) as ei:
            R.compile_expr(expr)
        assert "arithmetic is not supported" in str(ei.value)
        assert "and/or/not" in str(ei.value)

    def test_derived_fields_replace_the_need_for_arithmetic(self, bar):
        # the bar already carries range/body/wick_ratio, so rules stay declarative
        assert R.compile_expr("range > 30")(bar)          # aliased to Bar.rng
        assert R.compile_expr("body > 30")(bar)
        assert R.compile_expr("wick_ratio >= 0")(bar)

    def test_parentheses_and_precedence(self, bar):
        # and binds tighter than or: A=True, B=False, C=False separates the two
        assert R.compile_expr("(efficiency > 0.9 or chart_pct > 180) and direction == 1")(bar)
        assert R.compile_expr(
            "efficiency > 0.7 or chart_pct > 500 and vol_regime < 0.5")(bar)
        assert not R.compile_expr(
            "(efficiency > 0.7 or chart_pct > 500) and vol_regime < 0.5")(bar)

    def test_decimal_literals_are_supported(self, bar):
        assert R.compile_expr("system_pct > 159.5")(bar)
        assert R.compile_expr("efficiency > 0.8")(bar)
        assert not R.compile_expr("efficiency > 0.9")(bar)

    def test_negative_literals_are_not_part_of_the_language(self, bar):
        """Documented, not accidental: the untagged hour/weekday sentinel is -1 and
        cannot be matched.  If that ever becomes a requirement, the tokenizer has to
        learn unary minus — silently accepting `-1` as a field name would be worse."""
        with pytest.raises(ValueError, match="arithmetic"):
            R.compile_expr("hour == -1")

    def test_hour_and_weekday_are_available(self, bar):
        bar.hour = 14
        bar.weekday = 2
        assert R.compile_expr("hour >= 9 and hour <= 17")(bar)
        assert R.compile_expr("weekday < 5")(bar)
        assert not R.compile_expr("hour >= 9 and hour <= 12")(bar)

    @pytest.mark.parametrize("expr", [
        '__import__("os").system("echo pwned")',
        'open("/etc/passwd").read()',
        "eval('1+1')",
        "exec('x=1')",
        "().__class__.__bases__",
        "bar.close",                      # attribute access is not part of the language
        "close.close()",
        "os.environ",
        "lambda: 1",
        "[x for x in range(10)]",
    ])
    def test_hostile_expressions_are_rejected(self, expr):
        with pytest.raises(ValueError):
            R.compile_expr(expr)

    def test_unknown_fields_are_rejected_with_the_allowed_list(self):
        with pytest.raises(ValueError) as ei:
            R.compile_expr("nosuchfield > 1")
        msg = str(ei.value)
        assert "nosuchfield" in msg and "allowed" in msg
        assert "close" in msg, "the error should tell the user what they can use"

    @pytest.mark.parametrize("expr", ["", "   ", "close >", "and close", "close >> 1",
                                      "category = \"strong\"", "((close > 1)",
                                      "close > 1))", "1 +", "\"str\" > 1 and"])
    def test_malformed_expressions_are_rejected(self, expr):
        with pytest.raises(ValueError):
            R.compile_expr(expr)

    def test_allowed_fields_cover_the_annotated_bar(self):
        fields = R.ALLOWED_FIELDS
        # ts/tf identify a bar rather than describe it, so they are not rule inputs
        assert {"open", "high", "low", "close", "volume"} <= set(fields)
        assert {"category", "direction", "system_pct", "chart_pct", "efficiency"} <= set(fields)
        assert {"hour", "weekday"} <= set(fields)

    def test_every_allowed_field_evaluates_on_a_fully_annotated_bar(self):
        """The invariant that actually matters: a whitelisted field that raises at
        evaluation time makes its rule silently never fire, because match() swallows
        predicate exceptions so one bad rule cannot kill a run.  ``range`` is the
        cautionary case — it is aliased to ``Bar.rng``, so hasattr() would not catch
        it but a rule would still work."""
        from engine import pipeline
        res = pipeline.run(days=10, seed=7, tf=15)
        annotated = res.bars[len(res.bars) // 2]
        broken = []
        for f in sorted(R.ALLOWED_FIELDS):
            try:
                assert R.compile_expr(f"{f} >= {f}")(annotated) in (True, False)
            except Exception as exc:                       # noqa: BLE001
                broken.append((f, type(exc).__name__, str(exc)[:50]))
        assert not broken, f"whitelisted fields that cannot be evaluated: {broken}"


# --------------------------------------------------------------------- #
# 2. rule sets
# --------------------------------------------------------------------- #
class TestRuleSet:
    def test_default_rules_compile_and_are_enabled(self):
        rs = R.default_rules()
        assert rs.rules
        assert all(r.enabled for r in rs.rules)
        assert all(r.predicate is not None for r in rs.rules)
        assert {r.id for r in rs.rules} == {"blowoff", "quiet_trend", "dead_water"}

    def test_default_rules_use_known_colors(self):
        for r in R.default_rules().rules:
            assert r.color_key in R.COLORS

    def test_match_returns_the_highest_priority_hit(self, bar):
        rs = R.RuleSet(rules=[])
        rs.add(R.ColorRule(id="later", expr="close > open", color_key="long", priority=90))
        rs.add(R.ColorRule(id="earlier", expr="close > open", color_key="short", priority=10))
        assert rs.match(bar).id == "earlier"
        assert [r.id for r in rs.rules] == ["earlier", "later"]

    def test_match_returns_none_when_nothing_fires(self, bar):
        rs = R.RuleSet(rules=[])
        rs.add(R.ColorRule(id="nope", expr="close < open", color_key="flat"))
        assert rs.match(bar) is None

    def test_disabled_rules_do_not_match(self, bar):
        rs = R.RuleSet(rules=[])
        rs.add(R.ColorRule(id="off", expr="close > open", color_key="long", enabled=False))
        assert rs.match(bar) is None

    def test_the_blowoff_default_fires_on_an_extended_bar(self, bar):
        assert R.default_rules().match(bar).id == "blowoff"

    def test_adding_a_rule_with_the_same_id_replaces_it(self, bar):
        rs = R.default_rules()
        n = len(rs.rules)
        rs.add(R.ColorRule(id="blowoff", expr="close < open", color_key="flat"))
        assert len(rs.rules) == n, "an id collision must replace, not duplicate"
        assert [r for r in rs.rules if r.id == "blowoff"][0].expr == "close < open"

    def test_add_rejects_an_unknown_color(self):
        rs = R.RuleSet(rules=[])
        with pytest.raises(ValueError, match="color_key"):
            rs.add(R.ColorRule(id="x", expr="close > open", color_key="chartreuse"))

    def test_add_rejects_an_uncompilable_expression(self):
        rs = R.RuleSet(rules=[])
        with pytest.raises(ValueError):
            rs.add(R.ColorRule(id="x", expr="close >>> open", color_key="long"))

    def test_remove_reports_whether_it_removed_anything(self):
        rs = R.default_rules()
        assert rs.remove("blowoff") is True
        assert rs.remove("blowoff") is False
        assert all(r.id != "blowoff" for r in rs.rules)

    def test_a_rule_that_raises_at_evaluation_time_does_not_kill_matching(self, bar):
        rs = R.default_rules()
        broken = R.ColorRule(id="broken", expr="close > open", color_key="long", priority=1)
        broken.predicate = lambda b: (_ for _ in ()).throw(RuntimeError("boom"))
        rs.rules.insert(0, broken)
        assert rs.match(bar).id == "blowoff", "the broken rule should be skipped"

    def test_to_dict_round_trips_through_ruleset_from_payload(self):
        rs = R.default_rules()
        payload = rs.to_dict()
        back = R.ruleset_from_payload(payload)
        assert [r.id for r in back.rules] == [r.id for r in rs.rules]
        assert all(r.predicate is not None for r in back.rules)

    def test_ruleset_from_payload_supplies_defaults_for_missing_keys(self):
        rs = R.ruleset_from_payload({"rules": [{"id": "x", "expr": "close > open",
                                                "color_key": "long"}]})
        r = rs.rules[0]
        assert r.enabled is True and r.priority == 100
        assert r.label_fa == "" and r.label_en == ""

    def test_a_bad_rule_is_skipped_by_default_but_reported_when_asked(self):
        """Loading must survive one hand-edited line, yet a silent skip is how a
        rule ends up saved and never firing — so the skip has to be sayable."""
        bad = {"rules": [{"id": "x", "expr": "nope > 1", "color_key": "long"}]}
        assert R.ruleset_from_payload(bad).rules == []
        errs: list[str] = []
        R.ruleset_from_payload(bad, errors=errs)
        assert errs and "x" in errs[0] and "nope" in errs[0]

    def test_strict_mode_raises_on_a_bad_rule(self):
        with pytest.raises(ValueError, match="rejected"):
            R.ruleset_from_payload(
                {"rules": [{"id": "x", "expr": "nope > 1", "color_key": "long"}]},
                strict=True)

    def test_strict_mode_accepts_a_good_rule(self):
        rs = R.ruleset_from_payload(
            {"rules": [{"id": "x", "expr": "close > open", "color_key": "long"}]},
            strict=True)
        assert [r.id for r in rs.rules] == ["x"]

    def test_a_non_object_rule_entry_is_reported_not_crashed_on(self):
        errs: list[str] = []
        assert R.ruleset_from_payload({"rules": ["not an object"]}, errors=errs).rules == []
        assert errs and "must be an object" in errs[0]


# --------------------------------------------------------------------- #
# 3. persistence
# --------------------------------------------------------------------- #
class TestPersistence:
    def test_load_returns_defaults_when_no_file_exists(self, tmp_rules):
        assert not os.path.exists(tmp_rules)
        payload = R.load()
        assert payload["source"] == "defaults"
        assert payload["errors"] == []
        assert {r["id"] for r in payload["rules"]} == {"blowoff", "quiet_trend", "dead_water"}
        assert payload["keymap"] == R.DEFAULT_KEYMAP

    def test_save_then_load_round_trips(self, tmp_rules):
        payload = R.load()
        payload["rules"].append({"id": "mine", "expr": "close > open", "color_key": "long",
                                 "label_fa": "صعودی", "label_en": "up", "enabled": True,
                                 "priority": 5})
        path = R.save(payload)
        assert path == tmp_rules and os.path.exists(path)
        back = R.load()
        assert back["source"] == "file"
        assert any(r["id"] == "mine" for r in back["rules"])
        assert back["errors"] == []

    def test_saved_file_is_valid_json_with_both_sections(self, tmp_rules):
        R.save(R.load())
        with open(tmp_rules, encoding="utf-8") as fh:
            data = json.load(fh)
        assert "rules" in data and "keymap" in data

    def test_reset_restores_the_defaults(self, tmp_rules):
        payload = R.load()
        payload["rules"] = []
        R.save(payload)
        assert R.load()["rules"] == []
        out = R.reset()
        assert {r["id"] for r in out["rules"]} == {"blowoff", "quiet_trend", "dead_water"}
        # reset() writes the defaults to the user file, so a later load reads it back
        assert R.load()["source"] == "file"

    def test_a_corrupt_file_degrades_to_defaults_with_an_error(self, tmp_rules):
        with open(tmp_rules, "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        payload = R.load()
        assert payload["source"] == "defaults"
        assert payload["errors"], "the user must be told their file is broken"
        assert any("json" in e.lower() or "parse" in e.lower() for e in payload["errors"])

    def test_a_file_with_an_invalid_rule_reports_it_and_keeps_the_rest(self, tmp_rules):
        good = {"id": "ok", "expr": "close > open", "color_key": "long",
                "enabled": True, "priority": 10}
        bad = {"id": "bad", "expr": "__import__('os')", "color_key": "long",
               "enabled": True, "priority": 20}
        with open(tmp_rules, "w", encoding="utf-8") as fh:
            json.dump({"rules": [good, bad], "keymap": {}}, fh)
        payload = R.load()
        assert payload["errors"], "an unloadable rule must be reported"
        assert any(r["id"] == "ok" for r in payload["rules"])
        assert not any(r["id"] == "bad" for r in payload["rules"])

    def test_a_file_with_an_invalid_keymap_is_reported(self, tmp_rules):
        with open(tmp_rules, "w", encoding="utf-8") as fh:
            json.dump({"rules": [], "keymap": {"Escape": "play_pause"}}, fh)
        payload = R.load()
        assert payload["errors"]
        assert payload["keymap"] != {"Escape": "play_pause"}


# --------------------------------------------------------------------- #
# 4. commands and the keymap
# --------------------------------------------------------------------- #
class TestCommandsAndKeymap:
    def test_the_registry_has_the_documented_number_of_commands(self):
        assert len(R.COMMANDS) == 24
        assert len(R.command_registry()) == 24

    def test_every_command_has_an_id_a_group_and_both_labels(self):
        for c in R.command_registry():
            assert c["id"] and c["group"]
            assert c["label_fa"] and c["label_en"]
            assert c["label_fa"] != c["label_en"] or c["id"] in ("play_pause",)

    def test_command_ids_are_unique(self):
        ids = [c[0] for c in R.COMMANDS]
        assert len(ids) == len(set(ids))

    def test_commands_by_group_partitions_the_registry(self):
        groups = R.commands_by_group()
        assert sum(len(v) for v in groups.values()) == len(R.COMMANDS)
        for g, cmds in groups.items():
            assert all(c["group"] == g for c in cmds)

    def test_every_default_binding_names_a_real_command(self):
        ids = {c[0] for c in R.COMMANDS}
        assert len(R.DEFAULT_KEYMAP) == 23
        for key, cmd in R.DEFAULT_KEYMAP.items():
            assert cmd in ids, f"key {key!r} is bound to unknown command {cmd!r}"

    def test_no_default_binding_uses_a_reserved_key(self):
        for key in R.DEFAULT_KEYMAP:
            assert key not in R.RESERVED_KEYS

    def test_reserved_keys_include_the_ones_browsers_own(self):
        assert {"F5", "F11", "F12", "Tab", "Escape"} <= set(R.RESERVED_KEYS)

    def test_validate_keymap_accepts_a_valid_map(self):
        km = {"a": "play_pause", "b": "speed_up"}
        assert R.validate_keymap(km) == km

    def test_validate_keymap_rejects_an_unknown_command(self):
        with pytest.raises(ValueError, match="unknown command"):
            R.validate_keymap({"a": "launch_missiles"})

    def test_validate_keymap_rejects_a_reserved_key(self):
        for key in ("Escape", "F5", "Tab"):
            with pytest.raises(ValueError, match="reserved"):
                R.validate_keymap({key: "play_pause"})

    def test_validate_keymap_rejects_non_string_keys(self):
        with pytest.raises(ValueError):
            R.validate_keymap({1: "play_pause"})

    def test_validate_keymap_rejects_empty_and_invisible_bindings(self):
        with pytest.raises(ValueError, match="non-empty"):
            R.validate_keymap({"": "play_pause"})
        with pytest.raises(ValueError, match="non-empty"):
            R.validate_keymap({"   ": "play_pause"})
        with pytest.raises(ValueError, match="non-empty"):
            R.validate_keymap({"\t": "play_pause"})

    def test_the_spacebar_is_a_valid_binding(self):
        assert R.validate_keymap({" ": "play_pause"}) == {" ": "play_pause"}
        assert R.DEFAULT_KEYMAP[" "] == "play_pause"

    def test_two_keys_may_share_one_command(self):
        # '+' and '=' both mean speed_up in the default map
        assert R.validate_keymap({"+": "speed_up", "=": "speed_up"})
