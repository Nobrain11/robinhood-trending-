"""
Robinhood Chain Launch Bot
--------------------------

Main application:

- Connects to Robinhood Chain
- Validates chain ID
- Performs bounded backfill
- Persists the last scanned block
- Processes launch detector events
- Stores launches in SQLite
- Sends Telegram alerts
- Switches into live polling mode

This version deliberately keeps detector-specific logic outside
the main application where possible.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from web3 import Web3
from web3.providers.rpc import HTTPProvider

from app.config import Settings
from app.database import Database


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("robinhood-launch-bot")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def env_int(
    name: str,
    default: int,
) -> int:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        return default

    try:
        return int(value)
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r; using %s",
            name,
            value,
            default,
        )
        return default


def env_bool(
    name: str,
    default: bool = False,
) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.lower().strip() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_address(
    value: Any,
) -> str | None:

    if value is None:
        return None

    if isinstance(value, bytes):
        if len(value) == 20:
            return Web3.to_checksum_address(
                "0x" + value.hex()
            )

        return "0x" + value.hex()

    value = str(value)

    if value.startswith("0x") and len(value) == 42:
        try:
            return Web3.to_checksum_address(value)
        except Exception:
            return value

    return value


def get_value(
    obj: Any,
    *names: str,
    default: Any = None,
) -> Any:
    """
    Safely retrieve a value from:

    - dictionaries
    - dataclasses
    - objects
    - tuples/lists containing mappings

    This is important because older detector implementations may
    return tuples while newer implementations return dictionaries.
    """

    if obj is None:
        return default

    # Dictionary
    if isinstance(obj, dict):

        for name in names:
            if name in obj:
                return obj[name]

        # Case-insensitive fallback
        lowered = {
            str(k).lower(): v
            for k, v in obj.items()
        }

        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]

        return default

    # Dataclass
    if is_dataclass(obj):

        data = asdict(obj)

        for name in names:
            if name in data:
                return data[name]

        lowered = {
            str(k).lower(): v
            for k, v in data.items()
        }

        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]

        return default

    # Object attributes
    for name in names:

        if hasattr(obj, name):

            try:
                return getattr(obj, name)
            except Exception:
                pass

    # Tuple/list containing a dictionary/object
    if isinstance(obj, (tuple, list)):

        for item in obj:

            value = get_value(
                item,
                *names,
                default=None,
            )

            if value is not None:
                return value

    return default


# ---------------------------------------------------------------------------
# Chain client
# ---------------------------------------------------------------------------

class ChainClient:
    """
    Lightweight Web3 client.

    This class intentionally doesn't assume that the RPC provider
    supports enormous log queries.
    """

    def __init__(
        self,
        rpc_url: str,
        chain_id: int,
        request_timeout: int = 30,
    ):

        self.rpc_url = rpc_url
        self.expected_chain_id = chain_id

        self.w3 = Web3(
            HTTPProvider(
                rpc_url,
                request_kwargs={
                    "timeout": request_timeout,
                },
            )
        )

        self._validate_connection()

    def _validate_connection(self):

        logger.info(
            "Connecting to RPC: %s",
            self.rpc_url,
        )

        if not self.w3.is_connected():

            raise RuntimeError(
                f"Unable to connect to RPC: {self.rpc_url}"
            )

        actual = self.w3.eth.chain_id

        logger.info(
            "Chain ID: %s",
            actual,
        )

        if actual != self.expected_chain_id:

            raise RuntimeError(
                "Wrong chain ID. "
                f"Expected {self.expected_chain_id}, "
                f"received {actual}"
            )

    @property
    def latest_block(self) -> int:

        return self.w3.eth.block_number

    def get_logs(
        self,
        from_block: int,
        to_block: int,
        address: str | None = None,
        topics: list | None = None,
    ):

        params = {
            "fromBlock": from_block,
            "toBlock": to_block,
        }

        if address:
            params["address"] = address

        if topics:
            params["topics"] = topics

        return self.w3.eth.get_logs(params)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

class TelegramClient:
    """
    Minimal Telegram Bot API client.

    Uses requests rather than a long-running Telegram framework because
    this application is a chain worker.
    """

    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
    ):

        self.token = token
        self.chat_id = chat_id

        self.enabled = bool(
            self.token and self.chat_id
        )

        if not self.enabled:

            logger.warning(
                "Telegram disabled: "
                "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
            )

    def send_message(
        self,
        text: str,
    ) -> int | None:

        if not self.enabled:
            return None

        import requests

        url = (
            f"https://api.telegram.org/"
            f"bot{self.token}/sendMessage"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        try:

            response = requests.post(
                url,
                json=payload,
                timeout=15,
            )

            response.raise_for_status()

            data = response.json()

            if not data.get("ok"):

                logger.error(
                    "Telegram API error: %s",
                    data,
                )

                return None

            result = data.get(
                "result",
                {},
            )

            return result.get(
                "message_id"
            )

        except Exception:

            logger.exception(
                "Telegram send failed"
            )

            return None


# ---------------------------------------------------------------------------
# Main bot
# ---------------------------------------------------------------------------

class RobinhoodBot:

    def __init__(self):

        self.running = True

        self.settings = Settings()

        self.chain = ChainClient(
            self.settings.rpc_url,
            self.settings.chain_id,
            self.settings.request_timeout,
        )

        database_path = getattr(
            self.settings,
            "database_path",
            None,
        )

        if not database_path:

            database_path = os.getenv(
                "DATABASE_PATH",
                "data/robinhood.db",
            )

        self.db = Database(
            database_path
        )

        self.telegram = TelegramClient(
            getattr(
                self.settings,
                "telegram_bot_token",
                None,
            )
            or os.getenv(
                "TELEGRAM_BOT_TOKEN"
            ),

            getattr(
                self.settings,
                "telegram_chat_id",
                None,
            )
            or os.getenv(
                "TELEGRAM_CHAT_ID"
            ),
        )

        self.batch_size = env_int(
            "BACKFILL_BATCH_SIZE",
            100,
        )

        self.backfill_blocks = env_int(
            "BACKFILL_BLOCKS",
            5000,
        )

        self.poll_seconds = env_int(
            "POLL_SECONDS",
            2,
        )

        self.start_block = self._calculate_start_block()

        self.detectors = self._load_detectors()

        logger.info(
            "Detectors: %s",
            ", ".join(
                self.detector_names()
            )
            or "none",
        )

    # ------------------------------------------------------------------
    # Detectors
    # ------------------------------------------------------------------

    def _load_detectors(self):

        detectors = []

        # Pons is optional so the bot can still boot if the detector
        # file is not present yet.

        try:

            from detectors.pons import PonsDetector

            detector = PonsDetector(
                self.chain.w3
            )

            detectors.append(
                detector
            )

        except ImportError as exc:

            logger.warning(
                "Pons detector unavailable: %s",
                exc,
            )

        except Exception:

            logger.exception(
                "Failed to initialize Pons detector"
            )

        return detectors

    def detector_names(self):

        names = []

        for detector in self.detectors:

            name = getattr(
                detector,
                "name",
                None,
            )

            if name:
                names.append(str(name))
            else:
                names.append(
                    detector.__class__.__name__
                )

        return names

    # ------------------------------------------------------------------
    # Block state
    # ------------------------------------------------------------------

    def _calculate_start_block(self) -> int:

        latest = self.chain.latest_block

        saved = self.db.get_state(
            "last_scanned_block"
        )

        if saved is not None:

            try:

                saved_block = int(saved)

                logger.info(
                    "Resuming from block %s",
                    saved_block,
                )

                return saved_block + 1

            except ValueError:

                logger.warning(
                    "Invalid saved block: %r",
                    saved,
                )

        explicit = os.getenv(
            "START_BLOCK"
        )

        if explicit:

            try:

                block = int(explicit)

                logger.info(
                    "Using START_BLOCK=%s",
                    block,
                )

                return block

            except ValueError:

                logger.warning(
                    "Invalid START_BLOCK=%r",
                    explicit,
                )

        start = max(
            0,
            latest - self.backfill_blocks,
        )

        logger.info(
            "No saved block. "
            "Starting %s blocks behind latest: %s",
            self.backfill_blocks,
            start,
        )

        return start

    # ------------------------------------------------------------------
    # Detector execution
    # ------------------------------------------------------------------

    def detect_launches(
        self,
        log: Any,
    ) -> list[Any]:

        launches = []

        for detector in self.detectors:

            try:

                # New detector API
                if hasattr(
                    detector,
                    "detect",
                ):

                    result = detector.detect(
                        log
                    )

                # Compatibility with detectors that use
                # process_log().
                elif hasattr(
                    detector,
                    "process_log",
                ):

                    result = detector.process_log(
                        log
                    )

                else:

                    logger.warning(
                        "Detector %s has no detect/process_log method",
                        detector,
                    )

                    continue

                if result is None:
                    continue

                if isinstance(
                    result,
                    list,
                ):

                    launches.extend(
                        result
                    )

                else:

                    launches.append(
                        result
                    )

            except Exception:

                logger.exception(
                    "Detector %s failed",
                    detector.__class__.__name__,
                )

        return launches

    # ------------------------------------------------------------------
    # Launch processing
    # ------------------------------------------------------------------

    def process_launch_log(
        self,
        log: Any,
    ):

        try:

            launches = self.detect_launches(
                log
            )

            if not launches:
                return

            for launch in launches:

                self.process_launch(
                    launch,
                    log,
                )

        except Exception:

            logger.exception(
                "Launch processing failed"
            )

    def process_launch(
        self,
        launch: Any,
        log: Any,
    ):

        """
        Normalize a detector result.

        The old code directly did:

            state["isToken0"]

        which failed when state was a tuple.

        Everything below uses get_value(), so dictionaries,
        dataclasses, objects and nested tuple/list results are handled.
        """

        tx_hash = get_value(
            launch,
            "tx_hash",
            "txHash",
            "transactionHash",
            default=None,
        )

        block_number = get_value(
            launch,
            "block_number",
            "blockNumber",
            default=None,
        )

        log_index = get_value(
            launch,
            "log_index",
            "logIndex",
            default=0,
        )

        detector_name = get_value(
            launch,
            "detector",
            "detector_name",
            "source",
            default="pons",
        )

        token_address = get_value(
            launch,
            "token_address",
            "tokenAddress",
            "token",
            "address",
            default=None,
        )

        deployer = get_value(
            launch,
            "deployer",
            "creator",
            "owner",
            default=None,
        )

        pool_address = get_value(
            launch,
            "pool_address",
            "poolAddress",
            "pool",
            default=None,
        )

        pair_token = get_value(
            launch,
            "pair_token",
            "pairToken",
            "quote_token",
            default=None,
        )

        name = get_value(
            launch,
            "name",
            "token_name",
            "tokenName",
            default="Unknown",
        )

        symbol = get_value(
            launch,
            "symbol",
            "token_symbol",
            "tokenSymbol",
            default="UNKNOWN",
        )

        decimals = get_value(
            launch,
            "decimals",
            default=18,
        )

        supply = get_value(
            launch,
            "supply",
            "total_supply",
            "totalSupply",
            default=None,
        )

        initial_buy_amount = get_value(
            launch,
            "initial_buy_amount",
            "initialBuyAmount",
            "buy_amount",
            default=None,
        )

        # ----------------------------------------------------------------
        # THIS IS THE FIX FOR YOUR ERROR.
        #
        # Never do:
        #
        #     state["isToken0"]
        #
        # because state may be a tuple.
        # ----------------------------------------------------------------

        is_token0 = get_value(
            launch,
            "isToken0",
            "is_token0",
            "token0",
            default=None,
        )

        pool_fee = get_value(
            launch,
            "pool_fee",
            "poolFee",
            "fee",
            default=None,
        )

        timestamp = get_value(
            launch,
            "launch_timestamp",
            "launchTimestamp",
            "timestamp",
            default=int(time.time()),
        )

        token_address = normalize_address(
            token_address
        )

        deployer = normalize_address(
            deployer
        )

        pool_address = normalize_address(
            pool_address
        )

        pair_token = normalize_address(
            pair_token
        )

        if not token_address:

            logger.warning(
                "Detector returned launch without token address"
            )

            return

        if block_number is None:

            block_number = get_value(
                log,
                "blockNumber",
                "block_number",
                default=self.chain.latest_block,
            )

        if tx_hash is None:

            tx_hash = get_value(
                log,
                "transactionHash",
                "tx_hash",
                default="unknown",
            )

        if hasattr(
            tx_hash,
            "hex",
        ):

            tx_hash = tx_hash.hex()

        # ----------------------------------------------------------------
        # Database-compatible launch object
        # ----------------------------------------------------------------

        normalized = NormalizedLaunch(
            detector=str(
                detector_name
            ),

            token_address=token_address,

            deployer=deployer,

            pool_address=pool_address,

            pair_token=pair_token,

            tx_hash=str(tx_hash),

            block_number=int(
                block_number
            ),

            log_index=int(
                log_index or 0
            ),

            launch_timestamp=int(
                timestamp
            ),

            name=str(
                name or "Unknown"
            ),

            symbol=str(
                symbol or "UNKNOWN"
            ),

            decimals=int(
                decimals or 18
            ),

            supply=supply,

            initial_buy_amount=initial_buy_amount,

            is_token0=(
                bool(is_token0)
                if is_token0 is not None
                else None
            ),

            pool_fee=(
                int(pool_fee)
                if pool_fee is not None
                else None
            ),
        )

        inserted = self.db.insert_launch(
            normalized
        )

        if not inserted:

            logger.debug(
                "Launch already exists: %s",
                token_address,
            )

            return

        logger.info(
            "NEW LAUNCH: %s (%s) [%s]",
            normalized.name,
            normalized.symbol,
            normalized.token_address,
        )

        message = self.format_launch_message(
            normalized
        )

        message_id = self.telegram.send_message(
            message
        )

        if message_id:

            self.db.update_launch_message(
                normalized.token_address,
                message_id,
            )

    # ------------------------------------------------------------------
    # Telegram message
    # ------------------------------------------------------------------

    def format_launch_message(
        self,
        launch: "NormalizedLaunch",
    ) -> str:

        lines = [
            "🚀 NEW ROBINHOOD CHAIN LAUNCH",
            "",
            f"🪙 {launch.name}",
            f"🔹 ${launch.symbol}",
            "",
            f"📍 Token: {launch.token_address}",
            f"🧩 Detector: {launch.detector}",
            f"🧱 Block: {launch.block_number}",
        ]

        if launch.pool_address:

            lines.append(
                f"💧 Pool: {launch.pool_address}"
            )

        if launch.deployer:

            lines.append(
                f"👤 Deployer: {launch.deployer}"
            )

        if launch.tx_hash:

            lines.append(
                f"🔗 TX: {launch.tx_hash}"
            )

        lines.extend(
            [
                "",
                "⚡ Robinhood Chain Launch Monitor",
            ]
        )

        return "\n".join(
            lines
        )

    # ------------------------------------------------------------------
    # Scan range
    # ------------------------------------------------------------------

    def scan_range(
        self,
        from_block: int,
        to_block: int,
    ):

        if to_block < from_block:
            return

        logger.info(
            "Scanning %s -> %s",
            from_block,
            to_block,
        )

        # Some detectors may expose their own log filter.
        # If so, use it. Otherwise get all logs for the range.

        logs = self.chain.get_logs(
            from_block,
            to_block,
        )

        for log in logs:

            self.process_launch_log(
                log
            )

        self.db.set_state(
            "last_scanned_block",
            str(to_block),
        )

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def backfill(self):

        latest = self.chain.latest_block

        start = self.start_block

        if start > latest:

            logger.info(
                "Start block %s is ahead of latest %s",
                start,
                latest,
            )

            return

        logger.info(
            "Backfill %s -> %s",
            start,
            latest,
        )

        current = start

        while (
            current <= latest
            and self.running
        ):

            end = min(
                current + self.batch_size - 1,
                latest,
            )

            try:

                self.scan_range(
                    current,
                    end,
                )

            except Exception:

                logger.exception(
                    "Backfill failed at blocks %s -> %s",
                    current,
                    end,
                )

                # Do not spin at 100% CPU if the RPC rejects
                # a request.

                time.sleep(3)

                continue

            current = end + 1

            logger.info(
                "Backfill at block %s",
                current,
            )

        logger.info(
            "Backfill complete"
        )

    # ------------------------------------------------------------------
    # Live mode
    # ------------------------------------------------------------------

    def live_loop(self):

        logger.info(
            "Entering live monitoring mode"
        )

        next_block = (
            int(
                self.db.get_state(
                    "last_scanned_block"
                )
                or self.chain.latest_block
            )
            + 1
        )

        while self.running:

            try:

                latest = self.chain.latest_block

                if latest < next_block:

                    time.sleep(
                        self.poll_seconds
                    )

                    continue

                end = min(
                    next_block
                    + self.batch_size
                    - 1,
                    latest,
                )

                self.scan_range(
                    next_block,
                    end,
                )

                next_block = end + 1

            except Exception:

                logger.exception(
                    "Live scan failed"
                )

                time.sleep(
                    max(
                        self.poll_seconds,
                        3,
                    )
                )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop(
        self,
        *_args,
    ):

        if not self.running:
            return

        logger.info(
            "Shutdown requested"
        )

        self.running = False

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):

        logger.info(
            "Robinhood Chain bot starting"
        )

        self.backfill()

        if not self.running:
            return

        self.live_loop()


# ---------------------------------------------------------------------------
# Normalized launch model
# ---------------------------------------------------------------------------

class NormalizedLaunch:

    def __init__(
        self,
        detector: str,
        token_address: str,
        deployer: str | None,
        pool_address: str | None,
        pair_token: str | None,
        tx_hash: str,
        block_number: int,
        log_index: int,
        launch_timestamp: int,
        name: str,
        symbol: str,
        decimals: int,
        supply: Any,
        initial_buy_amount: Any,
        is_token0: bool | None,
        pool_fee: int | None,
    ):

        self.detector = detector

        self.token_address = token_address

        self.deployer = deployer

        self.pool_address = pool_address

        self.pair_token = pair_token

        self.tx_hash = tx_hash

        self.block_number = block_number

        self.log_index = log_index

        self.launch_timestamp = launch_timestamp

        self.name = name

        self.symbol = symbol

        self.decimals = decimals

        self.supply = supply

        self.initial_buy_amount = initial_buy_amount

        self.is_token0 = is_token0

        self.pool_fee = pool_fee


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():

    logging.basicConfig(
        level=os.getenv(
            "LOG_LEVEL",
            "INFO",
        ).upper(),

        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )

    bot = None

    def shutdown(
        signum,
        frame,
    ):

        if bot is not None:
            bot.stop(
                signum,
                frame,
            )

    signal.signal(
        signal.SIGTERM,
        shutdown,
    )

    signal.signal(
        signal.SIGINT,
        shutdown,
    )

    try:

        bot = RobinhoodBot()

        bot.run()

    except KeyboardInterrupt:

        logger.info(
            "Interrupted"
        )

    except Exception:

        logger.exception(
            "Fatal bot error"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
