"""python -m trading_system.cli {public,account,all,stream}"""

import argparse
import logging
from collections.abc import Callable

from trading_system.binance.account import MISSING_CREDENTIALS, AccountAPI
from trading_system.binance.client import BinanceClient, BinanceError
from trading_system.binance.public import PublicAPI
from trading_system.config import SYMBOLS, ConfigError, load_config
from trading_system.logging_config import configure_logging

logger = logging.getLogger("trading_system.cli")


def run_public(client: BinanceClient) -> bool:
    public = PublicAPI(client)
    success = True

    def check(operation: Callable[[], None]) -> None:
        nonlocal success
        try:
            operation()
        except BinanceError as error:
            print(f"Public API check failed: {error}")
            logger.error("public check failure exception=%s", error)
            success = False

    def ticker(symbol: str) -> None:
        result = public.ticker(symbol)
        print(f"{result.symbol} : {result.price:f} USDT (REST Latency: {result.latency_ms:.1f} ms)")

    def candles() -> None:
        print("\nBTCUSDT 4H candles × 10 (UTC; latest candle may still be open)")
        for candle in public.candles():
            print(
                f"open_time={candle.open_time.isoformat()} open={candle.open:f} "
                f"high={candle.high:f} low={candle.low:f} close={candle.close:f} "
                f"volume={candle.volume:f} close_time={candle.close_time.isoformat()}"
            )

    def order_book() -> None:
        book = public.order_book()
        print(f"\n{book.symbol} Order Book")
        print(f"best_bid: {book.best_bid:f}\nbest_ask: {book.best_ask:f}")
        print(f"spread: {book.spread:f} USDT\nspread_percent: {book.spread_percent:.8f}%")
        for label, levels in (("Bids", book.bids), ("Asks", book.asks)):
            print(f"{label} (up to 10; price USDT / quantity BTC):")
            for level in levels:
                print(f"  {level.price:f} / {level.quantity:f}")
        print(f"REST Latency: {book.latency_ms:.1f} ms (application round-trip)")

    for symbol in SYMBOLS:
        check(lambda symbol=symbol: ticker(symbol))
    check(candles)
    check(order_book)
    return success


def run_account(client: BinanceClient) -> bool:
    try:
        balances = AccountAPI(client).balances()
    except BinanceError as error:
        print(f"Binance authentication status: FAILED ({error})")
        return False
    if balances is None:
        print(MISSING_CREDENTIALS)
        return True
    print("Binance authentication status: SUCCESS (read-only account query)")
    for balance in balances:
        print(
            f"\n{balance.asset}\nfree: {balance.free:f}\nlocked: {balance.locked:f}"
            f"\ntotal: {balance.total:f}"
        )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Binance Spot REST and WebSocket data")
    parser.add_argument(
        "command",
        choices=(
            "public",
            "account",
            "all",
            "stream",
            "db-init",
            "collect",
            "db-status",
            "db-verify",
            "db-backup",
            "db-restore",
            "strategy-audit",
            "strategy-replay",
            "observe",
            "observer-status",
        ),
    )
    parser.add_argument("--duration", type=float)
    parser.add_argument("--ws-base-url", default="wss://data-stream.binance.vision")
    parser.add_argument("--report-file")
    parser.add_argument("--db-path", default="data/market_data.sqlite")
    parser.add_argument("--bootstrap-days", type=int, default=7)
    parser.add_argument("--snapshot-seconds", type=int, default=60)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--recovery-max-days", type=int, default=365)
    parser.add_argument("--backup-path")
    parser.add_argument("--observer-db", default="data/observer.sqlite")
    parser.add_argument("--start-ms", type=int)
    parser.add_argument("--end-ms", type=int)
    args = parser.parse_args(argv)
    if args.command in ("strategy-audit", "strategy-replay", "observe", "observer-status"):
        from trading_system.observer.cli import run_observer_cli

        return run_observer_cli(args)
    if args.command in ("db-init", "collect", "db-status", "db-verify", "db-backup", "db-restore"):
        from trading_system.persistence.cli import run_database_cli

        try:
            configure_logging()
        except OSError:
            print("Cannot initialize logs/app.log. Check directory permissions.")
            return 2
        logger.info("program start command=%s", args.command)
        code = run_database_cli(args)
        logger.info("program exit code=%d", code)
        return code
    if args.command == "stream":
        # Do not load .env or account credentials for public WebSocket operation.
        from trading_system.binance.websocket import run_stream_cli

        try:
            configure_logging()
        except OSError:
            print("Cannot initialize logs/app.log. Check directory permissions.")
            return 2
        logger.info("program start command=stream")
        code = run_stream_cli(
            120 if args.duration is None else args.duration, args.ws_base_url, args.report_file
        )
        logger.info("program exit code=%d", code)
        return code
    try:
        config = load_config(include_credentials=args.command != "public")
        configure_logging(secrets=(config.api_key, config.api_secret))
    except ConfigError as error:
        print(f"Configuration error: {error}")
        return 2
    except OSError:
        print("Cannot initialize logs/app.log. Check directory permissions.")
        return 2
    logger.info("program start command=%s", args.command)
    exit_code = 1
    try:
        with BinanceClient(config) as client:
            public_ok = run_public(client) if args.command in ("public", "all") else True
            account_ok = run_account(client) if args.command in ("account", "all") else True
            exit_code = 0 if public_ok and account_ok else 1
    except KeyboardInterrupt:
        logger.warning("program interrupted")
        exit_code = 130
    except Exception as error:
        # Never print raw exception strings or tracebacks from dependency code.
        logger.error("unexpected exception type=%s", type(error).__name__)
        print("Unexpected internal error. See logs/app.log for the safe error category.")
    finally:
        logger.info("program exit code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
