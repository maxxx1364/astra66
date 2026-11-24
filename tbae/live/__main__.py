"""Command line for the live system.

    python3 -m live run [--config live.json] [--dashboard] [--port 8100]
    python3 -m live dashboard [--db data/live.sqlite3] [--port 8100]
    python3 -m live scan-once [--config live.json]       # one pass, print the funnel
    python3 -m live check                                 # connectivity + fee check
    python3 -m live default-config > live.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading


def _serve(app, host: str, port: int, block: bool) -> None:
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    if block:
        server.run()
    else:
        threading.Thread(target=server.run, daemon=True, name="dashboard").start()


def main(argv: list[str] | None = None) -> int:
    from .config import LiveConfig

    p = argparse.ArgumentParser(prog="python3 -m live")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "scan-once", "check"):
        sp = sub.add_parser(name)
        sp.add_argument("--config", default=None)
        if name == "run":
            sp.add_argument("--dashboard", action="store_true")
            sp.add_argument("--host", default="127.0.0.1")
            sp.add_argument("--port", type=int, default=8100)
            sp.add_argument("--no-websocket", action="store_true")
    w = sub.add_parser("wakeup", help="daily scan for coins waking up (Binance public data)")
    w.add_argument("--json", action="store_true")
    d = sub.add_parser("dashboard")
    d.add_argument("--db", default="data/live.sqlite3")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8100)
    sub.add_parser("default-config")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.cmd == "default-config":
        json.dump(LiveConfig().to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0
    if a.cmd == "wakeup":
        from .wakeup import BinanceDaily, scan_today
        rows = scan_today(BinanceDaily())
        if a.json:
            json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
            print()
            return 0
        if not rows:
            print("no wake-up signals on the last closed day")
        for r in rows:
            print(f"{r['symbol']:<14} score={r['score']:<6} rvol={r['rvol']:<6} "
                  f"day={r['day_move']:+.2%} taker_buy={r['taker_buy']:.2f} "
                  f"vs_btc_20d={r['rel_20d']:+.2%}  [{', '.join(r['confirm'])}]")
        return 0
    if a.cmd == "dashboard":
        from .dashboard import create_app
        from .storage import Store
        _serve(create_app(Store(a.db)), a.host, a.port, block=True)
        return 0

    cfg = LiveConfig.load(a.config)
    if a.cmd == "check":
        from .exchange import build_exchange
        ex = build_exchange(cfg.exchange)
        mk = ex.markets()
        print(f"{cfg.exchange}: {len(mk)} markets, "
              f"{sum(m.trading for m in mk)} trading")
        try:
            acc = ex.account()
            print(f"account fees: maker {acc.maker_bps}bp taker {acc.taker_bps}bp, "
                  f"can_trade={acc.can_trade} can_withdraw={acc.can_withdraw}")
            if acc.can_withdraw:
                print("WARNING: this API key can withdraw. Create one without that permission.")
        except Exception as e:  # noqa: BLE001
            print(f"account: not available ({e})")
        return 0

    from .runner import Runner
    r = Runner(cfg)
    if a.cmd == "scan-once":
        r.refresh_universe()
        r.md.sweep(len(r.md.symbols))
        rows = r.scan()
        ranked = r.analyze(rows)
        print(json.dumps(r.funnel, ensure_ascii=False))
        for o in ranked[:20]:
            print(f"{o['rank']:>3} {o['symbol']:<12} score={o['score']:.3f} "
                  f"net={o.get('net_edge_bps', 0):+.0f}bp  {'; '.join(o['notes'])}")
        return 0

    if a.dashboard:
        from .dashboard import create_app
        _serve(create_app(r.store, r), a.host, a.port, block=False)
        logging.info("dashboard on http://%s:%d", a.host, a.port)
    try:
        r.run_forever(websocket=not a.no_websocket)
    except KeyboardInterrupt:
        r.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
