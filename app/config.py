import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    rpc_url: str = os.getenv(
        "RPC_URL",
        "https://rpc.mainnet.chain.robinhood.com",
    )

    chain_id: int = env_int("CHAIN_ID", 4663)

    start_block: int = env_int(
        "START_BLOCK",
        8991118,
    )

    poll_seconds: float = float(
        os.getenv("POLL_SECONDS", "2")
    )

    block_chunk: int = env_int(
        "BLOCK_CHUNK",
        100,
    )

    confirmations: int = env_int(
        "CONFIRMATIONS",
        0,
    )

    db_path: str = os.getenv(
        "DB_PATH",
        "data/launches.db",
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

    max_retries: int = env_int(
        "MAX_RETRIES",
        5,
    )

    request_timeout: int = env_int(
        "REQUEST_TIMEOUT",
        15,
    )

    def validate(self):
        if self.chain_id != 4663:
            raise ValueError(
                "This bot is configured for "
                "Robinhood Chain mainnet (4663)."
            )

        if not self.telegram_bot_token:
            raise ValueError(
                "Set TELEGRAM_BOT_TOKEN in .env."
            )

        if not self.telegram_chat_id:
            raise ValueError(
                "Set TELEGRAM_CHAT_ID in .env."
            )
