"""Explicit opt-in only: public network, no .env or account credentials."""

import asyncio

import pytest

from trading_system.binance.websocket import WebSocketMonitor, print_summary

pytestmark = pytest.mark.integration


def test_live_public_websocket(request):
    if not request.config.getoption("--live-stream"):
        pytest.skip("Enable --live-stream for a real 120s public WebSocket check")
    monitor = WebSocketMonitor()
    result = asyncio.run(monitor.run(120, on_summary=print_summary))
    print_summary(monitor)
    print(f"Live WebSocket result: {result['live_status']}")
    if not result["success"]:
        pytest.fail(
            f"{result['live_status']}: category={result['error_category']} "
            f"HTTP={result['http_status']}",
            pytrace=False,
        )
    assert result["normal_shutdown"]
    assert not result["data_loss"]
    # An x=true live claim is intentionally conditional; a 4h close may not occur in 120s.
