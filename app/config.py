import os

from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def env_int(
    name: str,
    default: int,
) -> int:

    value = os.getenv(name)

    if value in (None, ""):
        return default

    return int(value)


def env_float(
    name: str,
    default: float,
) -> float:

    value = os.getenv(name)

    if value in (None, ""):
        return default

    return float(value)


@dataclass(frozen=True)
class Settings:

    chain_id: int = env_int(
        "CHAIN_ID",
        4663,
    )

    rpc_url: str = os.getenv(
        "RPC_URL",
        "https://rpc.mainnet.chain.robinhood.com",
    )

    ws_url: str = os.getenv(
        "WS_URL",
        "wss://feed.mainnet.chain.robinhood.com",
    )

    start_block: int = env_int(
        "START_BLOCK",
        8991118,
    )

    block_chunk: int = env_int(
        "BLOCK_CHUNK",
        100,
    )

    poll_seconds: float = env_float(
        "POLL_SECONDS",
        2,
    )

    confirmations: int = env_int(
        "CONFIRMATIONS",
        0,
    )

    db_path: str = os.getenv(
        "DB_PATH",
        "data/robinhood.db",
    )

    telegram_bot_token: str = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        "",
    )

    telegram_chat_id: str = os.getenv(
        "TELEGRAM_CHAT_ID",
        "",
    )

    explorer_base: str = os.getenv(
        "EXPLORER_BASE",
        "https://robinhoodchain.blockscout.com",
    )

    trend_interval_seconds: int = env_int(
        "TREND_INTERVAL_SECONDS",
        60,
    )

    trend_window_seconds: int = env_int(
        "TREND_WINDOW_SECONDS",
        300,
    )

    trend_alert_score: float = env_float(
        "TREND_ALERT_SCORE",
        75,
    )

    trend_update_score: float = env_float(
        "TREND_UPDATE_SCORE",
        60,
    )

    trend_cooldown_seconds: int = env_int(
        "TREND_COOLDOWN_SECONDS",
        900,
    )

    min_swaps_for_trend: int = env_int(
        "MIN_SWAPS_FOR_TREND",
        10,
    )

    min_buyers_for_trend: int = env_int(
        "MIN_BUYERS_FOR_TREND",
        5,
    )

    request_timeout: int = env_int(
        "REQUEST_TIMEOUT",
        20,
    )

    max_retries: int = env_int(
        "MAX_RETRIES",
        5,
    )

    def validate(self):

        if self.chain_id != 4663:
            raise ValueError(
                "This bot only supports "
                "Robinhood Chain mainnet "
                "chain ID 4663."
            )

        if not self.telegram_bot_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is missing."
            )

        if not self.telegram_chat_id:
            raise ValueError(
                "TELEGRAM_CHAT_ID is missing."
            )
