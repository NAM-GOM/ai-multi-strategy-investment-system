import pytest

from trading_system.config import Config, ConfigError, load_config


def test_environment_loading_and_private_repr():
    config = load_config(
        env_file=None,
        environ={
            "BINANCE_API_KEY": "test-only-key",
            "BINANCE_API_SECRET": "test-only-secret",
            "BINANCE_TIMEOUT_SECONDS": "8",
            "BINANCE_RECV_WINDOW_MS": "4000",
        },
    )
    assert config.has_credentials
    assert config.timeout_seconds == 8
    assert config.recv_window_ms == 4000
    assert "test-only-key" not in repr(config)
    assert "test-only-secret" not in repr(config)


def test_dotenv_and_environment_precedence(tmp_path):
    path = tmp_path / ".env"
    path.write_text("BINANCE_API_KEY=test-only-key\nBINANCE_API_SECRET=test-only-secret\n")
    assert load_config(env_file=path, environ={}).has_credentials
    assert not load_config(env_file=path, environ={"BINANCE_API_KEY": ""}).has_credentials


def test_public_configuration_discards_credentials():
    config = load_config(
        include_credentials=False,
        env_file=None,
        environ={
            "BINANCE_API_KEY": "test-only-key",
            "BINANCE_API_SECRET": "test-only-secret",
        },
    )
    assert not config.has_credentials


@pytest.mark.parametrize(
    "variable,value",
    [
        ("BINANCE_TIMEOUT_SECONDS", "0"),
        ("BINANCE_TIMEOUT_SECONDS", "nan"),
        ("BINANCE_TIMEOUT_SECONDS", "61"),
        ("BINANCE_RECV_WINDOW_MS", "5001"),
        ("BINANCE_RECV_WINDOW_MS", "-1"),
        ("BINANCE_RECV_WINDOW_MS", "1.5"),
        ("BINANCE_PUBLIC_BASE_URL", "http://api.binance.com"),
        ("BINANCE_PUBLIC_BASE_URL", "https://untrusted.example"),
    ],
)
def test_invalid_settings_do_not_echo_input(variable, value):
    with pytest.raises(ConfigError) as caught:
        load_config(env_file=None, environ={variable: value})
    assert str(caught.value) == "Invalid Binance configuration; check the documented settings."


def test_public_host_and_conservative_defaults():
    config = load_config(
        env_file=None,
        environ={
            "BINANCE_PUBLIC_BASE_URL": "https://data-api.binance.vision/",
        },
    )
    assert config.public_base_url == "https://data-api.binance.vision"
    assert config.recv_window_ms == 5000
    assert not Config().has_credentials
