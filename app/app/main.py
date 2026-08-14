from __future__ import annotations

import logging
import os
import signal
import sys
import time
from typing import Any

import requests
from web3 import Web3
from web3.providers.rpc import HTTPProvider

from app.config import Settings
from app.database import Database
from detectors.pons import PonsDetector


# ============================================================================
# LOGGING
# ============================================================================

logger = logging.getLogger("robinhood-launch-bot")


# ============================================================================
# CONSTANTS
# ============================================================================

PONS_ACTIVE_FACTORY = Web3.to_checksum_address(
    "0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB"
)

PONS_LEGACY_FACTORY = Web3.to_checksum_address(
    "0x0c37a24F5D23A486FA692d1500881d698B1F77a4"
)

WETH_ADDRESS = Web3.to_checksum_address(
    "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
)

# pons / Uniswap V3 Swap event
V3_SWAP_TOPIC = (
    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
)

# pons active factory TokenLaunched event
TOKEN_LAUNCHED_TOPIC = (
    "0xdb51ea9ad51ab453a65a4cb7e60c3cb378c9501bb002609f8f97778fb6c4235a"
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# ============================================================================
# ENVIRONMENT HELPERS
# ============================================================================

def env_int(
    name: str,
    default: int,
) -> int:

    value = os.getenv(name)

    if not value:
        return default

    try:
        return int(value)

    except ValueError:

        logger.warning(
            "Invalid %s=%r. Using %s.",
            name,
            value,
            default,
        )

        return default


def env_float(
    name: str,
    default: float,
) -> float:

    value = os.getenv(name)

    if not value:
        return default

    try:
        return float(value)

    except ValueError:

        logger.warning(
            "Invalid %s=%r. Using %s.",
            name,
            value,
            default,
        )

        return default


# ============================================================================
# SAFE VALUE HELPERS
# ============================================================================

def get_value(
    obj: Any,
    *names: str,
    default: Any = None,
) -> Any:

    if obj is None:
        return default

    if isinstance(obj, dict):

        for name in names:

            if name in obj:
                return obj[name]

        return default

    for name in names:

        if hasattr(obj, name):

            try:

                return getattr(
                    obj,
                    name,
                )

            except Exception:
                pass

    if isinstance(
        obj,
        (tuple, list),
    ):

        for item in obj:

            result = get_value(
                item,
                *names,
                default=None,
            )

            if result is not None:
                return result

    return default


def normalize_address(
    value: Any,
) -> str | None:

    if value is None:
        return None

    if isinstance(
        value,
        bytes,
    ):

        if len(value) == 20:

            return Web3.to_checksum_address(
                "0x" + value.hex()
            )

        return "0x" + value.hex()

    value = str(value)

    if (
        value.startswith("0x")
        and len(value) == 42
    ):

        try:

            return Web3.to_checksum_address(
                value
            )

        except Exception:

            return value

    return value


def short_address(
    value: str | None,
) -> str:

    if not value:
        return "Unknown"

    value = str(value)

    if len(value) <= 12:
        return value

    return (
        value[:6]
        + "..."
        + value[-4:]
    )


def format_usd(
    value: Any,
) -> str:

    try:

        number = float(value)

    except (
        TypeError,
        ValueError,
    ):

        return "$0.00"

    if number >= 1_000_000_000:

        return f"${number / 1_000_000_000:.2f}B"

    if number >= 1_000_000:

        return f"${number / 1_000_000:.2f}M"

    if number >= 1_000:

        return f"${number / 1_000:.2f}k"

    return f"${number:,.2f}"


def format_price(
    value: Any,
) -> str:

    try:

        number = float(value)

    except (
        TypeError,
        ValueError,
    ):

        return "$0"

    if number == 0:
        return "$0"

    if number >= 1:

        return f"${number:.4f}"

    if number >= 0.01:

        return f"${number:.6f}"

    if number >= 0.000001:

        return f"${number:.8f}"

    return f"${number:.10f}"


def format_token_amount(
    value: Any,
) -> str:

    try:

        number = float(value)

    except (
        TypeError,
        ValueError,
    ):

        return "0"

    if number >= 1_000_000_000:

        return f"{number / 1_000_000_000:.2f}B"

    if number >= 1_000_000:

        return f"{number / 1_000_000:.2f}M"

    if number >= 1_000:

        return f"{number / 1_000:.2f}k"

    if number >= 1:

        return f"{number:,.0f}"

    return f"{number:.6f}"


# ============================================================================
# URL HELPERS
# ============================================================================

def normalize_url(
    value: str | None,
) -> str | None:

    if not value:
        return None

    value = str(value).strip()

    if not value:
        return None

    if value.startswith(
        "ipfs://"
    ):

        return (
            "https://ipfs.io/ipfs/"
            + value[7:]
        )

    if value.startswith(
        "ar://"
    ):

        return (
            "https://arweave.net/"
            + value[5:]
        )

    return value


# ============================================================================
# CHAIN CLIENT
# ============================================================================

class ChainClient:

    def __init__(
        self,
        rpc_url: str,
        chain_id: int,
        request_timeout: int = 30,
    ):

        self.rpc_url = rpc_url

        self.expected_chain_id = chain_id

        self.request_timeout = request_timeout

        logger.info(
            "Connecting to RPC: %s",
            rpc_url,
        )

        self.w3 = Web3(
            HTTPProvider(
                rpc_url,
                request_kwargs={
                    "timeout": request_timeout,
                },
            )
        )

        if not self.w3.is_connected():

            raise RuntimeError(
                "Could not connect to RPC"
            )

        actual_chain_id = (
            self.w3.eth.chain_id
        )

        logger.info(
            "Chain ID: %s",
            actual_chain_id,
        )

        if actual_chain_id != chain_id:

            raise RuntimeError(
                "Wrong chain ID: "
                f"expected {chain_id}, "
                f"got {actual_chain_id}"
            )

    @property
    def latest_block(self) -> int:

        return self.w3.eth.block_number

    # ------------------------------------------------------------------------
    # Robust getLogs
    # ------------------------------------------------------------------------

    def get_logs(
        self,
        from_block: int,
        to_block: int,
        address: str | None = None,
        topics: list | None = None,
    ) -> list:

        if to_block < from_block:

            return []

        pending_ranges = [
            (
                from_block,
                to_block,
            )
        ]

        results = []

        max_retries = env_int(
            "RPC_RETRIES",
            4,
        )

        minimum_range = env_int(
            "RPC_MIN_BLOCK_RANGE",
            10,
        )

        while pending_ranges:

            current_from, current_to = (
                pending_ranges.pop(0)
            )

            params = {
                "fromBlock": current_from,
                "toBlock": current_to,
            }

            if address:

                params["address"] = address

            if topics:

                params["topics"] = topics

            success = False

            last_error = None

            for attempt in range(
                1,
                max_retries + 1,
            ):

                try:

                    logs = (
                        self.w3.eth.get_logs(
                            params
                        )
                    )

                    results.extend(
                        logs
                    )

                    success = True

                    break

                except Exception as exc:

                    last_error = exc

                    logger.warning(
                        "RPC getLogs failed "
                        "(attempt %s/%s) "
                        "for blocks %s -> %s: %s",
                        attempt,
                        max_retries,
                        current_from,
                        current_to,
                        exc,
                    )

                    if attempt < max_retries:

                        delay = min(
                            2 ** (
                                attempt - 1
                            ),
                            8,
                        )

                        time.sleep(
                            delay
                        )

            if success:

                continue

            range_size = (
                current_to
                - current_from
                + 1
            )

            if (
                range_size
                <= minimum_range
            ):

                logger.error(
                    "RPC failed after "
                    "range reduction: "
                    "%s -> %s",
                    current_from,
                    current_to,
                )

                if last_error:

                    raise last_error

                raise RuntimeError(
                    "RPC getLogs failed"
                )

            midpoint = (
                current_from
                + (
                    range_size // 2
                )
                - 1
            )

            left = (
                current_from,
                midpoint,
            )

            right = (
                midpoint + 1,
                current_to,
            )

            logger.warning(
                "Splitting RPC range "
                "%s -> %s into "
                "%s -> %s and %s -> %s",
                current_from,
                current_to,
                left[0],
                left[1],
                right[0],
                right[1],
            )

            pending_ranges.insert(
                0,
                right,
            )

            pending_ranges.insert(
                0,
                left,
            )

        results.sort(
            key=lambda item: (
                int(
                    item.get(
                        "blockNumber",
                        0,
                    )
                ),
                int(
                    item.get(
                        "transactionIndex",
                        0,
                    )
                ),
                int(
                    item.get(
                        "logIndex",
                        0,
                    )
                ),
            )
        )

        return results


# ============================================================================
# TELEGRAM
# ============================================================================

class TelegramClient:

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
    ):

        self.bot_token = bot_token

        self.chat_id = chat_id

        self.enabled = bool(
            bot_token
            and chat_id
        )

        if self.enabled:

            logger.info(
                "Telegram alerts enabled"
            )

        else:

            logger.warning(
                "Telegram alerts disabled"
            )

    def _url(
        self,
        method: str,
    ) -> str:

        return (
            "https://api.telegram.org/"
            f"bot{self.bot_token}/"
            f"{method}"
        )

    def send_message(
        self,
        text: str,
    ) -> int | None:

        if not self.enabled:

            return None

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        try:

            response = requests.post(
                self._url(
                    "sendMessage"
                ),
                json=payload,
                timeout=20,
            )

            if not response.ok:

                logger.error(
                    "Telegram sendMessage failed "
                    "HTTP %s: %s",
                    response.status_code,
                    response.text,
                )

                return None

            data = response.json()

            if not data.get("ok"):

                logger.error(
                    "Telegram API error: %s",
                    data,
                )

                return None

            result = data.get(
                "result"
            )

            if not result:

                return None

            return result.get(
                "message_id"
            )

        except Exception:

            logger.exception(
                "Telegram send failed"
            )

            return None

    def send_photo(
        self,
        photo_url: str | None,
        caption: str,
    ) -> int | None:

        if not self.enabled:

            return None

        if not photo_url:

            return self.send_message(
                caption
            )

        payload = {
            "chat_id": self.chat_id,
            "photo": photo_url,
            "caption": caption,
        }

        try:

            response = requests.post(
                self._url(
                    "sendPhoto"
                ),
                json=payload,
                timeout=30,
            )

            if not response.ok:

                logger.warning(
                    "Telegram sendPhoto failed "
                    "HTTP %s: %s",
                    response.status_code,
                    response.text,
                )

                return self.send_message(
                    caption
                )

            data = response.json()

            if not data.get("ok"):

                logger.warning(
                    "Telegram sendPhoto API error: %s",
                    data,
                )

                return self.send_message(
                    caption
                )

            result = data.get(
                "result"
            )

            if not result:

                return self.send_message(
                    caption
                )

            return result.get(
                "message_id"
            )

        except Exception:

            logger.exception(
                "Telegram photo send failed"
            )

            return self.send_message(
                caption
            )


# ============================================================================
# ROBINHOOD BOT
# ============================================================================

class RobinhoodBot:

    def __init__(self):

        self.running = True

        self.settings = Settings()

        # ------------------------------------------------------------------
        # RPC
        # ------------------------------------------------------------------

        self.chain = ChainClient(
            self.settings.rpc_url,
            self.settings.chain_id,
            self.settings.request_timeout,
        )

        # ------------------------------------------------------------------
        # DATABASE
        # ------------------------------------------------------------------

        database_path = (
            getattr(
                self.settings,
                "database_path",
                None,
            )
            or os.getenv(
                "DATABASE_PATH",
                "data/robinhood.db",
            )
        )

        self.db = Database(
            database_path
        )

        # ------------------------------------------------------------------
        # TELEGRAM
        # ------------------------------------------------------------------

        telegram_token = (
            getattr(
                self.settings,
                "telegram_bot_token",
                None,
            )
            or os.getenv(
                "TELEGRAM_BOT_TOKEN"
            )
        )

        telegram_chat_id = (
            getattr(
                self.settings,
                "telegram_chat_id",
                None,
            )
            or os.getenv(
                "TELEGRAM_CHAT_ID"
            )
        )

        self.telegram = TelegramClient(
            telegram_token,
            telegram_chat_id,
        )

        # ------------------------------------------------------------------
        # SCANNER
        # ------------------------------------------------------------------

        self.batch_size = env_int(
            "BACKFILL_BATCH_SIZE",
            100,
        )

        self.backfill_blocks = env_int(
            "BACKFILL_BLOCKS",
            1000,
        )

        self.poll_seconds = env_int(
            "POLL_SECONDS",
            2,
        )

        # ------------------------------------------------------------------
        # BUY ALERT CONFIG
        # ------------------------------------------------------------------

        self.buy_alerts_enabled = (
            os.getenv(
                "BUY_ALERTS_ENABLED",
                "true",
            ).lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

        self.minimum_buy_eth = env_float(
            "MINIMUM_BUY_ETH",
            0.0,
        )

        self.buy_cooldown_seconds = env_int(
            "BUY_ALERT_COOLDOWN",
            0,
        )

        self.last_buy_alert = {}

        # ------------------------------------------------------------------
        # TRACKED TOKENS
        #
        # token -> launch metadata
        # ------------------------------------------------------------------

        self.tracked_tokens: dict[
            str,
            dict[str, Any],
        ] = {}

        # pool -> token
        self.tracked_pools: dict[
            str,
            str,
        ] = {}

        # ------------------------------------------------------------------
        # PONS DETECTOR
        # ------------------------------------------------------------------

        self.pons = PonsDetector()

        # ------------------------------------------------------------------
        # IMPORTANT:
        #
        # Your PonsDetector.decode_launch(log) requires its Web3 instance
        # to be configured.
        #
        # Support several common attribute names so this works with the
        # detector version you already have.
        # ------------------------------------------------------------------

        self.configure_pons_web3()

        logger.info(
            "Detectors: pons"
        )

        # ------------------------------------------------------------------
        # START BLOCK
        # ------------------------------------------------------------------

        self.start_block = (
            self.get_start_block()
        )

    # ======================================================================
    # CONFIGURE PONS WEB3
    # ======================================================================

    def configure_pons_web3(self):

        configured = False

        for attribute in (
            "w3",
            "web3",
            "_w3",
            "_web3",
        ):

            try:

                setattr(
                    self.pons,
                    attribute,
                    self.chain.w3,
                )

                configured = True

            except Exception:

                pass

        # Some detector versions use a setter.
        for method_name in (
            "set_web3",
            "set_w3",
            "configure",
            "configure_web3",
        ):

            method = getattr(
                self.pons,
                method_name,
                None,
            )

            if callable(method):

                try:

                    method(
                        self.chain.w3
                    )

                    configured = True

                    break

                except Exception:

                    pass

        if configured:

            logger.info(
                "Configured PonsDetector with Web3"
            )

        else:

            logger.warning(
                "Could not find a PonsDetector Web3 "
                "configuration attribute/setter"
            )

    # ======================================================================
    # START BLOCK
    # ======================================================================

    def get_start_block(self) -> int:

        try:

            saved = self.db.get_state(
                "last_scanned_block"
            )

        except Exception:

            logger.exception(
                "Could not read last scanned block"
            )

            saved = None

        if saved is not None:

            try:

                block = int(
                    saved
                )

                logger.info(
                    "Resuming from block %s",
                    block + 1,
                )

                return block + 1

            except (
                ValueError,
                TypeError,
            ):

                logger.warning(
                    "Invalid database checkpoint: %r",
                    saved,
                )

        start_block_env = os.getenv(
            "START_BLOCK"
        )

        if start_block_env:

            try:

                block = int(
                    start_block_env
                )

                logger.info(
                    "Using START_BLOCK=%s",
                    block,
                )

                return block

            except ValueError:

                logger.warning(
                    "Invalid START_BLOCK=%r",
                    start_block_env,
                )

        pons_start = getattr(
            self.pons,
            "start_block",
            None,
        )

        if pons_start is None:

            pons_start = getattr(
                PonsDetector,
                "start_block",
                0,
            )

        latest = (
            self.chain.latest_block
        )

        calculated = max(
            int(pons_start),
            latest
            - self.backfill_blocks
            + 1,
        )

        logger.info(
            "Using START_BLOCK=%s",
            calculated,
        )

        return calculated

    # ======================================================================
    # PONS FILTER
    # ======================================================================

    def get_pons_logs(
        self,
        from_block: int,
        to_block: int,
    ) -> list:

        return self.chain.get_logs(
            from_block,
            to_block,
            address=PonsDetector.address,
            topics=[
                PonsDetector.topic0
            ],
        )

    # ======================================================================
    # TOKEN METADATA
    # ======================================================================

    def get_token_contract(
        self,
        token_address: str,
    ):

        abi = [
            {
                "name": "name",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "string",
                        "name": "",
                    }
                ],
            },
            {
                "name": "symbol",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "string",
                        "name": "",
                    }
                ],
            },
            {
                "name": "decimals",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "uint8",
                        "name": "",
                    }
                ],
            },
            {
                "name": "logo",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "string",
                        "name": "",
                    }
                ],
            },
            {
                "name": "socials",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "string",
                        "name": "twitter",
                    },
                    {
                        "type": "string",
                        "name": "telegram",
                    },
                    {
                        "type": "string",
                        "name": "discord",
                    },
                    {
                        "type": "string",
                        "name": "website",
                    },
                    {
                        "type": "string",
                        "name": "farcaster",
                    },
                ],
            },
        ]

        return self.chain.w3.eth.contract(
            address=Web3.to_checksum_address(
                token_address
            ),
            abi=abi,
        )

    def load_token_metadata(
        self,
        token_address: str,
    ) -> dict[str, Any]:

        metadata = {
            "name": None,
            "symbol": None,
            "decimals": 18,
            "logo": None,
            "twitter": None,
            "telegram": None,
            "website": None,
            "discord": None,
            "farcaster": None,
        }

        try:

            contract = (
                self.get_token_contract(
                    token_address
                )
            )

            try:

                metadata["name"] = (
                    contract.functions.name()
                    .call()
                )

            except Exception:
                pass

            try:

                metadata["symbol"] = (
                    contract.functions.symbol()
                    .call()
                )

            except Exception:
                pass

            try:

                metadata["decimals"] = int(
                    contract.functions.decimals()
                    .call()
                )

            except Exception:
                pass

            try:

                metadata["logo"] = normalize_url(
                    contract.functions.logo()
                    .call()
                )

            except Exception:
                pass

            try:

                socials = (
                    contract.functions.socials()
                    .call()
                )

                if socials:

                    metadata["twitter"] = (
                        normalize_url(
                            socials[0]
                        )
                    )

                    metadata["telegram"] = (
                        normalize_url(
                            socials[1]
                        )
                    )

                    metadata["discord"] = (
                        normalize_url(
                            socials[2]
                        )
                    )

                    metadata["website"] = (
                        normalize_url(
                            socials[3]
                        )
                    )

                    metadata["farcaster"] = (
                        normalize_url(
                            socials[4]
                        )
                    )

            except Exception:

                logger.debug(
                    "Could not read token socials "
                    "for %s",
                    token_address,
                    exc_info=True,
                )

        except Exception:

            logger.exception(
                "Token metadata lookup failed: %s",
                token_address,
            )

        return metadata

    # ======================================================================
    # DEXSCREENER METADATA FALLBACK
    # ======================================================================

    def get_dex_metadata(
        self,
        token_address: str,
    ) -> dict[str, Any]:

        result = {}

        try:

            response = requests.get(
                "https://api.dexscreener.com/latest/dex/tokens/"
                + token_address,
                timeout=10,
            )

            if not response.ok:

                return result

            data = response.json()

            pairs = data.get(
                "pairs"
            ) or []

            if not pairs:

                return result

            pair = pairs[0]

            result["price_usd"] = (
                pair.get(
                    "priceUsd"
                )
            )

            result["market_cap"] = (
                pair.get(
                    "marketCap"
                )
                or pair.get(
                    "fdv"
                )
            )

            info = pair.get(
                "info"
            ) or {}

            result["image"] = (
                normalize_url(
                    info.get(
                        "imageUrl"
                    )
                )
            )

            websites = (
                info.get(
                    "websites"
                )
                or []
            )

            if websites:

                result["website"] = (
                    websites[0].get(
                        "url"
                    )
                )

            socials = (
                info.get(
                    "socials"
                )
                or []
            )

            for social in socials:

                social_type = (
                    social.get(
                        "type"
                    )
                )

                social_url = (
                    social.get(
                        "url"
                    )
                )

                if social_type == "twitter":

                    result["twitter"] = (
                        social_url
                    )

                elif social_type == "telegram":

                    result["telegram"] = (
                        social_url
                    )

        except Exception:

            logger.debug(
                "DexScreener lookup failed for %s",
                token_address,
                exc_info=True,
            )

        return result

    # ======================================================================
    # REGISTER TOKEN
    # ======================================================================

    def register_token(
        self,
        launch: Any,
    ):

        token_address = normalize_address(
            get_value(
                launch,
                "token_address",
                "tokenAddress",
                "token",
            )
        )

        if not token_address:

            return

        pool_address = normalize_address(
            get_value(
                launch,
                "pool_address",
                "pool",
            )
        )

        pair_token = normalize_address(
            get_value(
                launch,
                "pair_token",
                "pairToken",
            )
        )

        metadata = (
            self.load_token_metadata(
                token_address
            )
        )

        self.tracked_tokens[
            token_address.lower()
        ] = {
            "token": token_address,
            "pool": pool_address,
            "pair_token": pair_token,
            **metadata,
        }

        if pool_address:

            self.tracked_pools[
                pool_address.lower()
            ] = token_address

        logger.info(
            "Registered token for buy monitoring | "
            "token=%s | pool=%s | pair=%s",
            token_address,
            pool_address,
            pair_token,
        )

    # ======================================================================
    # PROCESS PONS LAUNCH
    # ======================================================================

    def process_pons_log(
        self,
        log: Any,
    ):

        try:

            # IMPORTANT:
            #
            # decode_launch takes ONE argument.
            # The detector was already configured with Web3 above.
            #

            launch = (
                self.pons.decode_launch(
                    log
                )
            )

            if launch is None:

                return

            token_address = normalize_address(
                get_value(
                    launch,
                    "token_address",
                    "tokenAddress",
                    "token",
                )
            )

            if not token_address:

                logger.warning(
                    "Pons launch had no token address"
                )

                return

            detector_name = get_value(
                launch,
                "detector",
                default="pons",
            )

            deployer = normalize_address(
                get_value(
                    launch,
                    "deployer",
                )
            )

            pool_address = normalize_address(
                get_value(
                    launch,
                    "pool_address",
                    "pool",
                )
            )

            pair_token = normalize_address(
                get_value(
                    launch,
                    "pair_token",
                    "pairToken",
                )
            )

            tx_hash = get_value(
                launch,
                "tx_hash",
                "txHash",
            )

            if hasattr(
                tx_hash,
                "hex",
            ):

                tx_hash = tx_hash.hex()

            if not tx_hash:

                raw_tx = get_value(
                    log,
                    "transactionHash",
                )

                if hasattr(
                    raw_tx,
                    "hex",
                ):

                    tx_hash = raw_tx.hex()

                else:

                    tx_hash = str(
                        raw_tx
                        or ""
                    )

            block_number = get_value(
                launch,
                "block_number",
                "blockNumber",
            )

            if block_number is None:

                block_number = get_value(
                    log,
                    "blockNumber",
                    default=0,
                )

            log_index = get_value(
                launch,
                "log_index",
                "logIndex",
            )

            if log_index is None:

                log_index = get_value(
                    log,
                    "logIndex",
                    default=0,
                )

            initial_buy_amount = (
                get_value(
                    launch,
                    "initial_buy_amount",
                    "initialBuyAmount",
                )
            )

            unique_key = (
                f"{tx_hash}:"
                f"{log_index}"
            )

            try:

                existing = (
                    self.db.get_launch_by_key(
                        unique_key
                    )
                )

            except AttributeError:

                existing = None

            except Exception:

                logger.exception(
                    "Database lookup failed"
                )

                existing = None

            if existing:

                self.register_token(
                    launch
                )

                return

            logger.info(
                "NEW LAUNCH DETECTED | "
                "token=%s | "
                "pool=%s | "
                "block=%s | "
                "tx=%s",
                token_address,
                pool_address,
                block_number,
                tx_hash,
            )

            inserted = False

            try:

                inserted = (
                    self.db.insert_launch(
                        launch
                    )
                )

            except TypeError:

                launch_data = {
                    "detector": str(
                        detector_name
                    ),
                    "token_address": (
                        token_address
                    ),
                    "deployer": deployer,
                    "pool_address": (
                        pool_address
                    ),
                    "pair_token": pair_token,
                    "tx_hash": str(
                        tx_hash
                    ),
                    "block_number": int(
                        block_number
                    ),
                    "log_index": int(
                        log_index
                    ),
                    "initial_buy_amount": (
                        initial_buy_amount
                    ),
                }

                inserted = (
                    self.db.insert_launch(
                        launch_data
                    )
                )

            except Exception:

                logger.exception(
                    "Database insert failed "
                    "for token %s",
                    token_address,
                )

                return

            # Register regardless of whether database insert returns None.
            self.register_token(
                launch
            )

            if inserted is False:

                logger.debug(
                    "Database reported existing launch: %s",
                    token_address,
                )

                return

            # --------------------------------------------------------------
            # Launch alert
            # --------------------------------------------------------------

            message = (
                self.format_launch_message(
                    launch
                )
            )

            token_info = (
                self.tracked_tokens.get(
                    token_address.lower(),
                    {},
                )
            )

            photo = (
                token_info.get(
                    "logo"
                )
            )

            message_id = (
                self.telegram.send_photo(
                    photo,
                    message,
                )
            )

            if message_id:

                logger.info(
                    "Launch Telegram alert sent "
                    "for %s",
                    token_address,
                )

                try:

                    self.db.update_launch_message(
                        token_address,
                        message_id,
                    )

                except Exception:

                    pass

        except Exception:

            logger.exception(
                "Pons launch processing failed"
            )

    # ======================================================================
    # LAUNCH MESSAGE
    # ======================================================================

    def format_launch_message(
        self,
        launch: Any,
    ) -> str:

        token_address = normalize_address(
            get_value(
                launch,
                "token_address",
                "tokenAddress",
                "token",
                default="Unknown",
            )
        )

        pool_address = normalize_address(
            get_value(
                launch,
                "pool_address",
                "pool",
                default=None,
            )
        )

        tx_hash = get_value(
            launch,
            "tx_hash",
            "txHash",
            default="",
        )

        if hasattr(
            tx_hash,
            "hex",
        ):

            tx_hash = tx_hash.hex()

        token_info = (
            self.tracked_tokens.get(
                (
                    token_address or ""
                ).lower(),
                {},
            )
        )

        name = (
            token_info.get(
                "name"
            )
            or "New Token"
        )

        symbol = (
            token_info.get(
                "symbol"
            )
            or "TOKEN"
        )

        website = (
            token_info.get(
                "website"
            )
        )

        twitter = (
            token_info.get(
                "twitter"
            )
        )

        telegram = (
            token_info.get(
                "telegram"
            )
        )

        launchpad_url = (
            "https://www.ponsfamily.com/launchpad/"
            f"{token_address}"
        )

        lines = [
            f"🚀 {name} (${symbol}) just launched on Robinhood Chain! 🔥",
            "",
            f"💎 {token_address}",
            "",
        ]

        if website:

            lines.append(
                f"🌐 Website: {website}"
            )

        if telegram:

            lines.append(
                f"💬 Telegram: {telegram}"
            )

        if twitter:

            lines.append(
                f"🔹 X: {twitter}"
            )

        lines.extend(
            [
                "",
                f"🚀 Launchpad: {launchpad_url}",
            ]
        )

        if pool_address:

            lines.append(
                f"💧 Pool: {pool_address}"
            )

        if tx_hash:

            lines.append(
                f"🔗 TX: {tx_hash}"
            )

        return "\n".join(
            lines
        )

    # ======================================================================
    # GET POOL TOKEN ORDER
    # ======================================================================

    def get_pool_token_order(
        self,
        pool_address: str,
    ) -> tuple[
        str | None,
        str | None,
    ]:

        abi = [
            {
                "name": "token0",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "address",
                        "name": "",
                    }
                ],
            },
            {
                "name": "token1",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "address",
                        "name": "",
                    }
                ],
            },
        ]

        try:

            contract = (
                self.chain.w3.eth.contract(
                    address=Web3.to_checksum_address(
                        pool_address
                    ),
                    abi=abi,
                )
            )

            token0 = normalize_address(
                contract.functions.token0()
                .call()
            )

            token1 = normalize_address(
                contract.functions.token1()
                .call()
            )

            return (
                token0,
                token1,
            )

        except Exception:

            logger.exception(
                "Could not read pool token order: %s",
                pool_address,
            )

            return (
                None,
                None,
            )

    # ======================================================================
    # DECODE V3 SWAP
    # ======================================================================

    def decode_v3_swap(
        self,
        log: Any,
        token_info: dict[str, Any],
    ) -> dict[str, Any] | None:

        try:

            topics = list(
                log.get(
                    "topics",
                    [],
                )
            )

            if len(topics) < 3:

                return None

            topic0 = topics[0]

            if hasattr(
                topic0,
                "hex",
            ):

                topic0 = (
                    "0x"
                    + topic0.hex()
                )

            topic0 = str(
                topic0
            ).lower()

            if topic0 != V3_SWAP_TOPIC:

                return None

            pool_address = normalize_address(
                log.get(
                    "address"
                )
            )

            token_address = normalize_address(
                token_info.get(
                    "token"
                )
            )

            pair_token = normalize_address(
                token_info.get(
                    "pair_token"
                )
            )

            if not pool_address:
                return None

            if not token_address:
                return None

            if not pair_token:

                return None

            token0, token1 = (
                self.get_pool_token_order(
                    pool_address
                )
            )

            if not token0 or not token1:

                return None

            # --------------------------------------------------------------
            # Decode:
            #
            # Swap(
            #   address indexed sender,
            #   address indexed recipient,
            #   int256 amount0,
            #   int256 amount1,
            #   uint160 sqrtPriceX96,
            #   uint128 liquidity,
            #   int24 tick
            # )
            # --------------------------------------------------------------

            raw_data = log.get(
                "data"
            )

            if hasattr(
                raw_data,
                "hex",
            ):

                data_hex = raw_data.hex()

            else:

                data_hex = str(
                    raw_data
                    or ""
                )

                if data_hex.startswith(
                    "0x"
                ):

                    data_hex = data_hex[2:]

            if len(data_hex) < 64 * 5:

                return None

            chunks = [
                data_hex[
                    index * 64:
                    (index + 1) * 64
                ]
                for index in range(5)
            ]

            # int256 decoding
            def signed_256(
                chunk: str,
            ) -> int:

                value = int(
                    chunk,
                    16,
                )

                if value >= 2**255:

                    value -= 2**256

                return value

            amount0 = signed_256(
                chunks[0]
            )

            amount1 = signed_256(
                chunks[1]
            )

            sqrt_price_x96 = int(
                chunks[2],
                16,
            )

            sender = normalize_address(
                "0x"
                + bytes(
                    topics[1]
                )[-20:].hex()
                if isinstance(
                    topics[1],
                    bytes,
                )
                else str(
                    topics[1]
                )[-40:]
            )

            recipient = normalize_address(
                "0x"
                + bytes(
                    topics[2]
                )[-20:].hex()
                if isinstance(
                    topics[2],
                    bytes,
                )
                else str(
                    topics[2]
                )[-40:]
            )

            # --------------------------------------------------------------
            # pons buy/sell direction:
            #
            # If token is token0:
            #     pair amount = amount1
            #
            # If token is token1:
            #     pair amount = amount0
            #
            # pair amount > 0 => BUY
            # pair amount < 0 => SELL
            # --------------------------------------------------------------

            token_is_token0 = (
                token0.lower()
                == token_address.lower()
            )

            if token_is_token0:

                pair_signed = amount1

                token_signed = amount0

            else:

                pair_signed = amount0

                token_signed = amount1

            if pair_signed <= 0:

                # SELL
                return None

            if token_signed >= 0:

                return None

            token_amount_raw = (
                abs(
                    token_signed
                )
            )

            pair_amount_raw = (
                abs(
                    pair_signed
                )
            )

            decimals = int(
                token_info.get(
                    "decimals",
                    18,
                )
                or 18
            )

            token_amount = (
                token_amount_raw
                / (
                    10 ** decimals
                )
            )

            eth_amount = (
                pair_amount_raw
                / 10**18
            )

            if (
                eth_amount
                < self.minimum_buy_eth
            ):

                return None

            block_number = int(
                log.get(
                    "blockNumber",
                    0,
                )
            )

            transaction_hash = (
                log.get(
                    "transactionHash"
                )
            )

            if hasattr(
                transaction_hash,
                "hex",
            ):

                transaction_hash = (
                    transaction_hash.hex()
                )

            log_index = int(
                log.get(
                    "logIndex",
                    0,
                )
            )

            return {
                "token": token_address,
                "pool": pool_address,
                "pair_token": pair_token,
                "buyer": recipient,
                "sender": sender,
                "token_amount": token_amount,
                "token_amount_raw": token_amount_raw,
                "eth_amount": eth_amount,
                "amount0": amount0,
                "amount1": amount1,
                "sqrt_price_x96": sqrt_price_x96,
                "block_number": block_number,
                "transaction_hash": str(
                    transaction_hash
                    or ""
                ),
                "log_index": log_index,
            }

        except Exception:

            logger.exception(
                "Could not decode V3 buy"
            )

            return None

    # ======================================================================
    # BUY MARKET DATA
    # ======================================================================

    def get_buy_market_data(
        self,
        buy: dict[str, Any],
    ) -> dict[str, Any]:

        token_address = buy[
            "token"
        ]

        token_info = (
            self.tracked_tokens.get(
                token_address.lower(),
                {},
            )
        )

        data = (
            self.get_dex_metadata(
                token_address
            )
        )

        price_usd = data.get(
            "price_usd"
        )

        market_cap = data.get(
            "market_cap"
        )

        image = (
            token_info.get(
                "logo"
            )
            or data.get(
                "image"
            )
        )

        website = (
            token_info.get(
                "website"
            )
            or data.get(
                "website"
            )
        )

        twitter = (
            token_info.get(
                "twitter"
            )
            or data.get(
                "twitter"
            )
        )

        telegram = (
            token_info.get(
                "telegram"
            )
            or data.get(
                "telegram"
            )
        )

        if price_usd is None:

            # --------------------------------------------------------------
            # Fallback: calculate WETH price from V3 sqrtPriceX96.
            # --------------------------------------------------------------

            try:

                sqrt_price = (
                    buy[
                        "sqrt_price_x96"
                    ]
                )

                ratio = (
                    float(
                        sqrt_price
                    )
                    / 2**96
                )

                token0, token1 = (
                    self.get_pool_token_order(
                        buy["pool"]
                    )
                )

                if (
                    token0
                    and token0.lower()
                    == token_address.lower()
                ):

                    price_in_weth = (
                        ratio * ratio
                    )

                else:

                    price_in_weth = (
                        1
                        / (
                            ratio
                            * ratio
                        )
                    )

                eth_usd = (
                    self.get_eth_usd()
                )

                if eth_usd:

                    price_usd = (
                        price_in_weth
                        * eth_usd
                    )

            except Exception:

                logger.debug(
                    "Could not calculate token price",
                    exc_info=True,
                )

        if market_cap is None:

            try:

                if price_usd:

                    # pons fixed supply = 1B
                    market_cap = (
                        float(
                            price_usd
                        )
                        * 1_000_000_000
                    )

            except Exception:

                pass

        return {
            "price_usd": price_usd,
            "market_cap": market_cap,
            "image": image,
            "website": website,
            "twitter": twitter,
            "telegram": telegram,
        }

    # ======================================================================
    # ETH USD
    # ======================================================================

    def get_eth_usd(
        self,
    ) -> float | None:

        try:

            response = requests.get(
                "https://api.dexscreener.com/latest/dex/tokens/"
                + WETH_ADDRESS,
                timeout=10,
            )

            if not response.ok:

                return None

            data = response.json()

            pairs = (
                data.get(
                    "pairs"
                )
                or []
            )

            if not pairs:

                return None

            # Prefer a WETH pair with USD pricing.
            for pair in pairs:

                price = pair.get(
                    "priceUsd"
                )

                if price:

                    return float(
                        price
                    )

        except Exception:

            logger.debug(
                "ETH/USD lookup failed",
                exc_info=True,
            )

        return None

    # ======================================================================
    # BUY MESSAGE
    # ======================================================================

    def format_buy_message(
        self,
        buy: dict[str, Any],
        market: dict[str, Any],
    ) -> str:

        token_address = buy[
            "token"
        ]

        token_info = (
            self.tracked_tokens.get(
                token_address.lower(),
                {},
            )
        )

        name = (
            token_info.get(
                "name"
            )
            or "Unknown Token"
        )

        symbol = (
            token_info.get(
                "symbol"
            )
            or "TOKEN"
        )

        eth_amount = buy[
            "eth_amount"
        ]

        price_usd = market.get(
            "price_usd"
        )

        market_cap = market.get(
            "market_cap"
        )

        token_amount = buy[
            "token_amount"
        ]

        buyer = buy[
            "buyer"
        ]

        tx_hash = buy[
            "transaction_hash"
        ]

        website = market.get(
            "website"
        )

        twitter = market.get(
            "twitter"
        )

        telegram = market.get(
            "telegram"
        )

        chart_url = (
            "https://dexscreener.com/robinhood/"
            + token_address
        )

        tx_url = (
            "https://robinhoodchain.blockscout.com/tx/"
            + tx_hash
        )

        trending_url = (
            "https://www.ponsfamily.com/launchpad/"
            + token_address
        )

        lines = [
            f"🟢 {name} Buy!",
            "",
            (
                f"💰 {eth_amount:.4f} ETH"
                + (
                    f" ({format_usd("
                        + str(
                            eth_amount
                        )
                        + " * "
                        + str(
                            market.get(
                                "eth_usd",
                                0,
                            )
                        )
                        + ")"
                    )
                    if market.get(
                        "eth_usd"
                    )
                    else ""
                )
            ),
            (
                f"🪙 "
                f"{format_token_amount(token_amount)} "
                f"{symbol}"
            ),
        ]

        if price_usd is not None:

            lines.append(
                f"🏷️ Price: "
                f"{format_price(price_usd)}"
            )

        if market_cap is not None:

            lines.append(
                f"🔼 Mkt Cap: "
                f"{format_usd(market_cap)}"
            )

        lines.extend(
            [
                (
                    f"🔍 "
                    f"{short_address(buyer)}"
                ),
                "",
            ]
        )

        # --------------------------------------------------------------
        # Position calculation
        #
        # This is the immediate buy value as a percentage of market cap.
        # It is a real measurable value rather than inventing a "1000%"
        # signal.
        # --------------------------------------------------------------

        if (
            market_cap
            and market.get(
                "eth_usd"
            )
        ):

            buy_usd = (
                eth_amount
                * market[
                    "eth_usd"
                ]
            )

            position_percent = (
                buy_usd
                / float(
                    market_cap
                )
                * 100
            )

            lines.append(
                "⬆️ Position: "
                f"{position_percent:.2f}% "
                "of Mkt Cap"
            )

        lines.append("")

        buttons = []

        buttons.append(
            f"🔗 Tx: {tx_url}"
        )

        buttons.append(
            f"📈 Chart: {chart_url}"
        )

        if website:

            buttons.append(
                f"🌐 Web: {website}"
            )

        if twitter:

            buttons.append(
                f"🔹 X: {twitter}"
            )

        if telegram:

            buttons.append(
                f"💬 Telegram: {telegram}"
            )

        buttons.append(
            f"🔥 Trending: {trending_url}"
        )

        lines.extend(
            buttons
        )

        return "\n".join(
            lines
        )

    # ======================================================================
    # PROCESS BUY
    # ======================================================================

    def process_buy_log(
        self,
        log: Any,
    ):

        if not self.buy_alerts_enabled:

            return

        pool_address = normalize_address(
            log.get(
                "address"
            )
        )

        if not pool_address:

            return

        token_address = (
            self.tracked_pools.get(
                pool_address.lower()
            )
        )

        if not token_address:

            return

        token_info = (
            self.tracked_tokens.get(
                token_address.lower()
            )
        )

        if not token_info:

            return

        buy = self.decode_v3_swap(
            log,
            token_info,
        )

        if not buy:

            return

        # --------------------------------------------------------------
        # Prevent duplicate alerts.
        # --------------------------------------------------------------

        unique_key = (
            f"{buy['transaction_hash']}:"
            f"{buy['log_index']}"
        )

        now = time.time()

        previous = (
            self.last_buy_alert.get(
                unique_key
            )
        )

        if previous:

            return

        self.last_buy_alert[
            unique_key
        ] = now

        # Cleanup old entries.
        if len(
            self.last_buy_alert
        ) > 10_000:

            cutoff = (
                now
                - 3600
            )

            self.last_buy_alert = {
                key: value
                for key, value
                in self.last_buy_alert.items()
                if value >= cutoff
            }

        # --------------------------------------------------------------
        # Cooldown by wallet/token.
        # --------------------------------------------------------------

        cooldown_key = (
            f"{buy['buyer'].lower()}:"
            f"{buy['token'].lower()}"
        )

        cooldown_seconds = (
            self.buy_cooldown_seconds
        )

        if cooldown_seconds > 0:

            previous_time = (
                self.last_buy_alert.get(
                    cooldown_key
                )
            )

            if (
                previous_time
                and (
                    now
                    - previous_time
                )
                < cooldown_seconds
            ):

                return

            self.last_buy_alert[
                cooldown_key
            ] = now

        # --------------------------------------------------------------
        # Market data.
        # --------------------------------------------------------------

        market = (
            self.get_buy_market_data(
                buy
            )
        )

        market["eth_usd"] = (
            self.get_eth_usd()
        )

        message = (
            self.format_buy_message(
                buy,
                market,
            )
        )

        photo = market.get(
            "image"
        )

        message_id = (
            self.telegram.send_photo(
                photo,
                message,
            )
        )

        logger.info(
            "BUY ALERT | "
            "token=%s | "
            "buyer=%s | "
            "ETH=%.6f | "
            "tokens=%s | "
            "tx=%s | "
            "telegram_message=%s",
            buy["token"],
            buy["buyer"],
            buy["eth_amount"],
            buy["token_amount"],
            buy["transaction_hash"],
            message_id,
        )

    # ======================================================================
    # SCAN BUY LOGS
    # ======================================================================

    def scan_buy_logs(
        self,
        from_block: int,
        to_block: int,
    ):

        if not self.tracked_pools:

            return

        for pool_address in list(
            self.tracked_pools.keys()
        ):

            try:

                logs = self.chain.get_logs(
                    from_block,
                    to_block,
                    address=Web3.to_checksum_address(
                        pool_address
                    ),
                    topics=[
                        V3_SWAP_TOPIC
                    ],
                )

                for log in logs:

                    self.process_buy_log(
                        log
                    )

            except Exception:

                logger.exception(
                    "Buy scan failed for pool %s "
                    "blocks %s -> %s",
                    pool_address,
                    from_block,
                    to_block,
                )

    # ======================================================================
    # SCAN RANGE
    # ======================================================================

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

        # --------------------------------------------------------------
        # FIRST: Pons launches
        # --------------------------------------------------------------

        logs = self.get_pons_logs(
            from_block,
            to_block,
        )

        logger.info(
            "Pons logs found: %s "
            "for blocks %s -> %s",
            len(logs),
            from_block,
            to_block,
        )

        for log in logs:

            self.process_pons_log(
                log
            )

        # --------------------------------------------------------------
        # SECOND: Buys from known Pons pools
        # --------------------------------------------------------------

        self.scan_buy_logs(
            from_block,
            to_block,
        )

        # --------------------------------------------------------------
        # CHECKPOINT
        # --------------------------------------------------------------

        self.db.set_state(
            "last_scanned_block",
            str(to_block),
        )

    # ======================================================================
    # BACKFILL
    # ======================================================================

    def backfill(self):

        latest = (
            self.chain.latest_block
        )

        current = (
            self.start_block
        )

        logger.info(
            "Backfill %s -> %s",
            current,
            latest,
        )

        while (
            current <= latest
            and self.running
        ):

            end = min(
                current
                + self.batch_size
                - 1,
                latest,
            )

            try:

                self.scan_range(
                    current,
                    end,
                )

            except Exception:

                logger.exception(
                    "Backfill failed at "
                    "blocks %s -> %s",
                    current,
                    end,
                )

                time.sleep(
                    5
                )

                continue

            current = (
                end + 1
            )

            logger.info(
                "Backfill at block %s",
                current,
            )

        if self.running:

            logger.info(
                "Backfill complete"
            )

    # ======================================================================
    # LIVE LOOP
    # ======================================================================

    def live_loop(self):

        logger.info(
            "Entering live monitoring mode"
        )

        saved = self.db.get_state(
            "last_scanned_block"
        )

        if saved is not None:

            try:

                next_block = (
                    int(saved)
                    + 1
                )

            except (
                ValueError,
                TypeError,
            ):

                next_block = (
                    self.chain.latest_block
                    + 1
                )

        else:

            next_block = (
                self.chain.latest_block
                + 1
            )

        while self.running:

            try:

                latest = (
                    self.chain.latest_block
                )

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

                next_block = (
                    end + 1
                )

            except Exception:

                logger.exception(
                    "Live monitoring error"
                )

                time.sleep(
                    5
                )

    # ======================================================================
    # SHUTDOWN
    # ======================================================================

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

    # ======================================================================
    # RUN
    # ======================================================================

    def run(self):

        logger.info(
            "Robinhood Chain bot starting"
        )

        self.backfill()

        if not self.running:

            return

        self.live_loop()


# ============================================================================
# MAIN
# ============================================================================

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

    def handle_shutdown(
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
        handle_shutdown,
    )

    signal.signal(
        signal.SIGINT,
        handle_shutdown,
    )

    try:

        bot = RobinhoodBot()

        bot.run()

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped"
        )

    except Exception:

        logger.exception(
            "Fatal bot error"
        )

        sys.exit(1)


# ============================================================================
# DIRECT EXECUTION
# ============================================================================

if __name__ == "__main__":

    main()
