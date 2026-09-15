"""User-defined colour rules, plus the command and keymap registries.

Three separate concerns that share one persistence file (``data/user_rules.json``):

* **colour rules** — the user overrides the built-in decision tree with their own
  predicates.  Rules are evaluated *before* the tree, first match wins, so a user
  rule can only ever add specificity, never remove coverage: anything unmatched
  falls through to ``classify.classify``.
* **commands** — the registry the dashboard binds keys to.  Every command is a
  ``(group, key, label_fa, label_en)`` tuple so the UI can render a palette without
  hardcoding strings.
* **keymap** — key -> command, user-editable, validated against the registry.

The expression language is deliberately tiny and side-effect free: a whitelist of
bar fields, comparison operators, ``and``/``or``/``not``, numeric literals,
quoted strings and bare category names.  Strings are inert values — they can only
be compared, never called — so ``category == "strong"`` and the shorthand
``strong`` are equivalent.  Expressions are compiled to a closure by
:func:`compile_expr`; ``eval`` is never called on user input.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .models import COLORS, Bar, Category

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
USER_RULES_PATH = os.path.join(DATA_DIR, "user_rules.json")

#: fields a user rule may read.  Anything else is rejected at parse time.
ALLOWED_FIELDS: frozenset[str] = frozenset({
    "chart_pct", "system_pct", "efficiency", "leg_skew", "chart_abs", "chart_range",
    "s_total", "s_up", "s_down", "s_intra", "atr", "atr_pct", "sigma", "sigma_atr",
    "vol_regime", "rv", "gk", "true_range", "open", "high", "low", "close", "volume",
    "quote_volume", "trades", "n_minutes", "direction", "body", "range", "upper_wick",
    "lower_wick", "wick_ratio", "vwap", "session_open", "timing_score", "hour",
    "weekday", "is_max_bar", "category",
})

_ALLOWED_COLORS = frozenset(COLORS.keys())


@dataclass(slots=True)
class ColorRule:
    """One user rule: a predicate, a colour key, and a bilingual label."""

    id: str
    expr: str
    color_key: str
    label_fa: str = ""
    label_en: str = ""
    enabled: bool = True
    priority: int = 100
    predicate: Callable[[Bar], bool] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "expr": self.expr, "color_key": self.color_key,
                "label_fa": self.label_fa, "label_en": self.label_en,
                "enabled": self.enabled, "priority": self.priority}


# --------------------------------------------------------------------------- #
# expression compiler (no eval)
# --------------------------------------------------------------------------- #
_TOKEN = re.compile(
    r"""
    \s*(?:
        (?P<str>"[^"\n]*"|'[^'\n]*')
      | (?P<num>\d+\.\d+|\.\d+|\d+)
      | (?P<and>\band\b)
      | (?P<or>\bor\b)
      | (?P<not>\bnot\b)
      | (?P<op><=|>=|==|!=|<|>)
      | (?P<lp>\()
      | (?P<rp>\))
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.VERBOSE,
)

_CATEGORY_VALUES = {c.value for c in Category}


def _tokenize(expr: str) -> list[tuple[str, Any]]:
    pos = 0
    toks: list[tuple[str, Any]] = []
    while pos < len(expr):
        if expr[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(expr, pos)
        if not m:
            hint = ""
            if expr[pos] in "`´“”‘’":
                hint = ' (smart quotes are not supported; use straight " or \')'
            elif expr[pos] in "+-*/%^":
                hint = (" (arithmetic is not supported; this language has "
                        "comparisons, and/or/not and parentheses only)")
            raise ValueError(
                f"cannot parse rule expression at {expr[pos:]!r}{hint}")
        pos = m.end()
        if m.group("str") is not None:
            toks.append(("str", m.group("str")[1:-1]))
        elif m.group("num") is not None:
            toks.append(("num", float(m.group("num"))))
        elif m.group("and"):
            toks.append(("and", None))
        elif m.group("or"):
            toks.append(("or", None))
        elif m.group("not"):
            toks.append(("not", None))
        elif m.group("op"):
            toks.append(("op", m.group("op")))
        elif m.group("lp"):
            toks.append(("lp", None))
        elif m.group("rp"):
            toks.append(("rp", None))
        else:
            toks.append(("name", m.group("name")))
    return toks


class _Parser:
    """Recursive-descent parser: or > and > not > comparison > atom."""

    def __init__(self, toks: Sequence[tuple[str, Any]]) -> None:
        self.toks = list(toks)
        self.i = 0

    def peek(self) -> tuple[str, Any] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> tuple[str, Any]:
        t = self.peek()
        if t is None:
            raise ValueError("unexpected end of rule expression")
        self.i += 1
        return t

    def parse(self) -> Callable[[Bar], bool]:
        fn = self.parse_or()
        if self.peek() is not None:
            raise ValueError(f"trailing tokens in rule expression at position {self.i}")
        return fn

    def parse_or(self) -> Callable[[Bar], bool]:
        left = self.parse_and()
        while (t := self.peek()) and t[0] == "or":
            self.next()
            right = self.parse_and()
            l, r = left, right
            left = lambda b, l=l, r=r: bool(l(b) or r(b))
        return left

    def parse_and(self) -> Callable[[Bar], bool]:
        left = self.parse_not()
        while (t := self.peek()) and t[0] == "and":
            self.next()
            right = self.parse_not()
            l, r = left, right
            left = lambda b, l=l, r=r: bool(l(b) and r(b))
        return left

    def parse_not(self) -> Callable[[Bar], bool]:
        if (t := self.peek()) and t[0] == "not":
            self.next()
            inner = self.parse_not()
            return lambda b, inner=inner: not inner(b)
        return self.parse_cmp()

    def parse_cmp(self) -> Callable[[Bar], bool]:
        left = self.parse_atom()
        t = self.peek()
        if t and t[0] == "op":
            op = self.next()[1]
            right = self.parse_atom()
            return _cmp_fn(left, op, right)
        # a bare boolean atom (e.g. ``is_max_bar``) is its own predicate
        return lambda b, left=left: bool(left(b))

    def parse_atom(self) -> Callable[[Bar], Any]:
        t = self.next()
        if t[0] == "lp":
            inner = self.parse_or()
            nxt = self.peek()
            if not nxt or nxt[0] != "rp":
                raise ValueError("missing closing parenthesis in rule expression")
            self.next()
            return lambda b, inner=inner: bool(inner(b))
        if t[0] == "num":
            v = t[1]
            return lambda b, v=v: v
        if t[0] == "str":
            v = t[1]
            return lambda b, v=v: v
        if t[0] == "name":
            name = t[1]
            if name in ("true", "false"):
                v = name == "true"
                return lambda b, v=v: v
            if name in _CATEGORY_VALUES:
                # ``strong`` as a value: true when the bar is in that category
                cat = Category(name)
                return lambda b, cat=cat: b.category is cat
            if name not in ALLOWED_FIELDS:
                raise ValueError(
                    f"unknown field {name!r} in rule expression; allowed: "
                    f"{sorted(ALLOWED_FIELDS)}")
            return lambda b, name=name: _field(b, name)
        raise ValueError(f"unexpected token {t!r} in rule expression")


def _field(b: Bar, name: str) -> Any:
    if name == "category":
        c = getattr(b, "category", None)
        return getattr(c, "value", c)
    if name == "body":
        return b.body
    if name == "range":
        return b.rng
    if name == "is_max_bar":
        return bool(b.is_max_bar)
    return getattr(b, name)


def _cmp_fn(left: Callable[[Bar], Any], op: str,
            right: Callable[[Bar], Any]) -> Callable[[Bar], bool]:
    def fn(b: Bar) -> bool:
        a, c = left(b), right(b)
        try:
            if op == "<":
                return a < c
            if op == ">":
                return a > c
            if op == "<=":
                return a <= c
            if op == ">=":
                return a >= c
            if op == "==":
                return a == c
            if op == "!=":
                return a != c
        except TypeError:
            return False
        return False
    return fn


def compile_expr(expr: str) -> Callable[[Bar], bool]:
    """Compile a rule expression to a predicate.  Raises on anything unwhitelisted."""
    if not expr or not expr.strip():
        raise ValueError("empty rule expression")
    if len(expr) > 500:
        raise ValueError("rule expression too long (max 500 chars)")
    return _Parser(_tokenize(expr)).parse()


# --------------------------------------------------------------------------- #
# rule set
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class RuleSet:
    rules: list[ColorRule] = field(default_factory=list)

    def add(self, rule: ColorRule) -> ColorRule:
        rule.predicate = compile_expr(rule.expr)
        if rule.color_key not in _ALLOWED_COLORS:
            raise ValueError(
                f"color_key {rule.color_key!r} not in {sorted(_ALLOWED_COLORS)}")
        self.rules = [r for r in self.rules if r.id != rule.id]
        self.rules.append(rule)
        self.rules.sort(key=lambda r: (r.priority, r.id))
        return rule

    def remove(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) != before

    def match(self, bar: Bar) -> ColorRule | None:
        for r in self.rules:
            if not r.enabled or r.predicate is None:
                continue
            try:
                if r.predicate(bar):
                    return r
            except Exception:                       # a bad rule must not kill the run
                continue
        return None

    def compile_all(self) -> "RuleSet":
        for r in self.rules:
            if r.predicate is None:
                r.predicate = compile_expr(r.expr)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"rules": [r.to_dict() for r in self.rules]}


def default_rules() -> RuleSet:
    """Shipped example rules.  They are *examples*: each one encodes a hypothesis
    that should be validated before it is trusted, not a recommendation."""
    rs = RuleSet()
    rs.add(ColorRule(
        id="blowoff", expr="chart_pct > 180 and system_pct > 150",
        color_key="timing_hot", label_fa="انفجاری", label_en="Blow-off",
        priority=10))
    rs.add(ColorRule(
        id="quiet_trend", expr="efficiency > 0.7 and chart_pct >= 55",
        color_key="strong", label_fa="روند روان", label_en="Clean trend",
        priority=20))
    rs.add(ColorRule(
        id="dead_water", expr="vol_regime < 0.5 and chart_pct < 10",
        color_key="timing_dead", label_fa="راکد", label_en="Dead water",
        priority=30))
    return rs


# --------------------------------------------------------------------------- #
# commands + keymap
# --------------------------------------------------------------------------- #
#: (id, group, label_fa, label_en)
COMMANDS: tuple[tuple[str, str, str, str], ...] = (
    ("play_pause", "playback", "پخش/توقف", "Play/Pause"),
    ("speed_up", "playback", "افزایش سرعت", "Speed up"),
    ("speed_down", "playback", "کاهش سرعت", "Slow down"),
    ("step_forward", "playback", "یک گام به جلو", "Step forward"),
    ("reset_playback", "playback", "بازنشانی بازپخش", "Reset playback"),
    ("filter_weak", "filter", "فیلتر میله ضعیف", "Filter weak"),
    ("filter_pressure", "filter", "فیلتر میله پرفشار", "Filter pressure"),
    ("filter_energetic", "filter", "فیلتر میله پرانرژی", "Filter energetic"),
    ("filter_strong", "filter", "فیلتر میله قوی", "Filter strong"),
    ("filter_medium", "filter", "فیلتر میله متوسط", "Filter medium"),
    ("clear_filters", "filter", "پاک کردن فیلترها", "Clear filters"),
    ("hot_only", "filter", "فقط ساعات پرانرژی", "Hot hours only"),
    ("next_strong", "navigate", "میله قوی بعدی", "Next strong bar"),
    ("next_pressure", "navigate", "میله پرفشار بعدی", "Next pressure bar"),
    ("next_signal", "navigate", "سیگنال بعدی", "Next signal"),
    ("prev_signal", "navigate", "سیگنال قبلی", "Previous signal"),
    ("tf_down", "timeframe", "تایم‌فریم کوچک‌تر", "Smaller timeframe"),
    ("tf_up", "timeframe", "تایم‌فریم بزرگ‌تر", "Larger timeframe"),
    ("toggle_system_bar", "view", "نمایش میله سیستمی", "Toggle system bar"),
    ("toggle_volume", "view", "نمایش حجم", "Toggle volume"),
    ("toggle_signals", "view", "نمایش سیگنال‌ها", "Toggle signals"),
    ("export_csv", "io", "خروجی CSV", "Export CSV"),
    ("toggle_theme", "ui", "حالت تاریک/روشن", "Toggle theme"),
    ("toggle_lang", "ui", "تغییر زبان", "Toggle language"),
)

DEFAULT_KEYMAP: dict[str, str] = {
    " ": "play_pause", "+": "speed_up", "=": "speed_up", "-": "speed_down",
    "ArrowRight": "step_forward", "r": "reset_playback",
    "1": "filter_weak", "2": "filter_pressure", "3": "filter_energetic",
    "4": "filter_strong", "5": "filter_medium", "0": "clear_filters",
    "h": "hot_only", "n": "next_strong", "p": "next_pressure",
    "[": "tf_down", "]": "tf_up",
    "s": "toggle_system_bar", "v": "toggle_volume", "g": "toggle_signals",
    "e": "export_csv", "d": "toggle_theme", "l": "toggle_lang",
}

#: keys the browser needs for itself; binding these is refused
RESERVED_KEYS: frozenset[str] = frozenset({
    "F5", "F11", "F12", "Tab", "Escape", "c", "x",
})


def command_registry() -> list[dict[str, str]]:
    return [{"id": i, "group": g, "label_fa": fa, "label_en": en}
            for (i, g, fa, en) in COMMANDS]


def commands_by_group() -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for c in command_registry():
        out.setdefault(c["group"], []).append(c)
    return out


def validate_keymap(km: dict[str, str]) -> dict[str, str]:
    known = {c[0] for c in COMMANDS}
    out: dict[str, str] = {}
    for k, v in km.items():
        # A whitespace-only key is truthy but unusable — the UI would render an
        # invisible binding that can never be pressed, and it survives a save/load
        # round trip forever.  The single space is the exception: it is the
        # spacebar, and DEFAULT_KEYMAP binds it to play/pause.
        if not isinstance(k, str) or not k or (not k.strip() and k != " "):
            raise ValueError("keymap keys must be non-empty strings")
        if k in RESERVED_KEYS:
            raise ValueError(f"key {k!r} is reserved by the browser")
        if v not in known:
            raise ValueError(f"unknown command {v!r} for key {k!r}")
        out[k] = v
    # Two keys bound to one command is intentional (``+`` and ``=`` both speed
    # up), so values are not required to be unique.  Exact key collisions are
    # impossible: the input is a dict.
    return out


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load(path: str | None = None) -> dict[str, Any]:
    """Load user rules + keymap.  Missing or corrupt file -> defaults.

    A corrupt config must never take the dashboard down, so failures degrade to
    defaults and are reported in the returned payload rather than raised.
    """
    path = path or USER_RULES_PATH
    payload: dict[str, Any] = {
        "rules": default_rules().to_dict()["rules"],
        "keymap": dict(DEFAULT_KEYMAP),
        "source": "defaults",
        "errors": [],
    }
    if not os.path.exists(path):
        return payload
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        payload["errors"].append(f"could not read {path}: {e}; using defaults")
        return payload
    try:
        payload["keymap"] = validate_keymap(raw.get("keymap") or DEFAULT_KEYMAP)
    except ValueError as e:
        payload["errors"].append(f"invalid keymap ({e}); using defaults")
        payload["keymap"] = dict(DEFAULT_KEYMAP)
    rs = ruleset_from_payload({"rules": raw.get("rules") or []},
                              errors=payload["errors"])
    payload["rules"] = rs.to_dict()["rules"]
    payload["source"] = "file"
    return payload


_RULE_KEYS = ("id", "expr", "color_key", "label_fa", "label_en", "enabled", "priority")


def ruleset_from_payload(payload: dict[str, Any], *, strict: bool = False,
                         errors: list[str] | None = None) -> RuleSet:
    """Compile a serialised rule list into a :class:`RuleSet`.

    An unloadable rule is *skipped* by default, because the alternative — refusing
    to start the dashboard because one hand-edited line is wrong — is worse.  But a
    silent skip is how a rule the user just typed ends up saved and never firing,
    so every skip is appended to ``errors`` when a list is passed, and
    ``strict=True`` raises instead.  Callers that are about to persist the result
    must surface the skips: saving a ruleset built here rewrites the file *without*
    the rules that failed to compile.
    """
    rs = RuleSet()
    for r in payload.get("rules") or []:
        rid = (r or {}).get("id", "?") if isinstance(r, dict) else "?"
        try:
            if not isinstance(r, dict):
                raise TypeError(f"rule must be an object, got {type(r).__name__}")
            rs.add(ColorRule(**{k: v for k, v in r.items() if k in _RULE_KEYS}))
        except (ValueError, TypeError) as e:
            if strict:
                raise ValueError(f"rule {rid!r} rejected: {e}") from e
            if errors is not None:
                errors.append(f"rule {rid!r} rejected: {e}")
            continue
    return rs


def save(payload: dict[str, Any], path: str | None = None) -> str:
    path = path or USER_RULES_PATH
    _ensure_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"rules": payload.get("rules", []),
                   "keymap": payload.get("keymap", DEFAULT_KEYMAP)},
                  fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)          # atomic: a crash mid-write cannot corrupt it
    return path


def reset(path: str | None = None) -> dict[str, Any]:
    payload = {"rules": default_rules().to_dict()["rules"],
               "keymap": dict(DEFAULT_KEYMAP), "source": "defaults", "errors": []}
    save(payload, path)
    return payload
