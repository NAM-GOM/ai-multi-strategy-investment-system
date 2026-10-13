"""Credential-free preflight for the account host; no private API request."""

from trading_system.binance.client import BinanceClient, BinanceError
from trading_system.config import ACCOUNT_BASE_URL, Config


def main() -> int:
    print("DEV-M01 Account Host Preflight")
    print("Probe endpoint: GET /api/v3/time")
    print("Credentials: NOT USED")
    print("Authentication: NOT_TESTED")
    # Do not read .env or injected credentials. Probe the exact host used for account.
    try:
        with BinanceClient(Config(public_base_url=ACCOUNT_BASE_URL)) as client:
            response = client.get("/api/v3/time")
        if (
            not isinstance(response.data, dict)
            or type(response.data.get("serverTime")) is not int
            or response.data["serverTime"] <= 0
        ):
            raise BinanceError("invalid_response", "/api/v3/time")
    except BinanceError as error:
        print("Account host connectivity: FAIL")
        print(f"Error: {error}")
        if error.status == 451:
            print(f"Access restriction reason: {error.restriction_reason or 'unspecified_451'}")
            print("Binance private API is not reachable from this runner/environment.")
            print(
                "Use an authorized, eligible execution environment. No regional bypass is provided."
            )
        return 1
    except Exception:
        print("Account host connectivity: FAIL")
        print("Error: unexpected_preflight_failure")
        return 1
    print("Account host connectivity: PASS")
    print("Private credentials have not been validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
