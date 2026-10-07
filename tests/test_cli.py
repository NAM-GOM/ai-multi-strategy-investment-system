import logging

import httpx

from trading_system import cli
from trading_system.binance.account import MISSING_CREDENTIALS
from trading_system.config import Config
from trading_system.logging_config import configure_logging


def test_account_cli_missing_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BINANCE_API_KEY", "")
    monkeypatch.setenv("BINANCE_API_SECRET", "")
    assert cli.main(["account"]) == 0
    assert MISSING_CREDENTIALS in capsys.readouterr().out
    log = (tmp_path / "logs/app.log").read_text()
    assert "program start" in log
    assert "authentication skipped" in log
    assert "program exit code=0" in log


def test_public_cli_and_log_output(
    client_factory, candle_rows, book_data, tmp_path, monkeypatch, capsys
):
    def handler(request):
        path = request.url.path
        if path == "/api/v3/ticker/price":
            data = {"symbol": request.url.params["symbol"], "price": "123.45"}
        elif path == "/api/v3/klines":
            data = candle_rows
        else:
            data = book_data
        return httpx.Response(200, json=data)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "BinanceClient", lambda _: client_factory(handler))
    assert cli.main(["public"]) == 0
    output = capsys.readouterr().out
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert f"{symbol} : 123.45 USDT" in output
    assert output.count("open_time=") == 10
    assert len([line for line in output.splitlines() if line.startswith("  ")]) == 20
    assert "spread_percent: 1.00000000%" in output
    assert "REST Latency:" in output
    log = (tmp_path / "logs/app.log").read_text()
    assert log.count("request success") == 5
    assert "symbol=BTCUSDT" in log
    assert "endpoint=/api/v3/depth" in log
    assert "latency_ms=" in log


def test_all_runs_account_after_public_failure(client_factory, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda **_: Config())
    monkeypatch.setattr(
        cli,
        "BinanceClient",
        lambda _: client_factory(
            lambda request: httpx.Response(429, json={"code": -1003, "msg": "rate limit"}),
        ),
    )
    assert cli.main(["all"]) == 1
    output = capsys.readouterr().out
    assert "rate_limit" in output
    assert MISSING_CREDENTIALS in output
    assert "program exit code=1" in (tmp_path / "logs/app.log").read_text()


def test_account_cli_prints_all_four_assets(client_factory, tmp_path, monkeypatch, capsys):
    def handler(request):
        data = (
            {"serverTime": 1_700_000_000_000}
            if request.url.path == "/api/v3/time"
            else {
                "balances": [{"asset": "BTC", "free": "1", "locked": "2"}],
            }
        )
        return httpx.Response(200, json=data)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda **_: Config(
            api_key="test-only-key",
            api_secret="test-only-secret",
        ),
    )
    monkeypatch.setattr(cli, "BinanceClient", lambda config: client_factory(handler, config))
    assert cli.main(["account"]) == 0
    output = capsys.readouterr().out
    assert "Binance authentication status: SUCCESS" in output
    assert "BTC\nfree: 1\nlocked: 2\ntotal: 3" in output
    for asset in ("USDT", "ETH", "SOL"):
        assert f"{asset}\nfree: 0\nlocked: 0\ntotal: 0" in output
    assert "test-only-key" not in output
    assert "test-only-secret" not in output


def test_redaction_in_console_and_file(tmp_path, capsys):
    path = tmp_path / "app.log"
    configure_logging(log_file=path, secrets=("test-only-key", "test-only-secret"))
    logging.getLogger("trading_system").error(
        "test-only-key test-only-secret signature=mock-signature",
    )
    text = capsys.readouterr().err + path.read_text()
    for value in ("test-only-key", "test-only-secret", "mock-signature"):
        assert value not in text
    assert "[REDACTED]" in text
