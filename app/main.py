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


# ============================================================================
# SAFE VALUE HELPERS
# ============================================================================

def get_value(
    obj: Any,
    *names: str,
    default: Any = None,
) -> Any:
    """
    Safely read values from dictionaries, objects,
    tuples and lists.
    """

    if obj is None:
        return default

    # Dictionary
    if isinstance(obj, dict):

        for name in names:

            if name in obj:
                return obj[name]

        return default

    # Object attributes
    for name in names:

        if hasattr(obj, name):

            try:

                return getattr(
                    obj,
                    name,
                )

            except Exception:
                pass

    # Tuple/list compatibility
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

            # --------------------------------------------------------------
            # Retry RPC request
            # --------------------------------------------------------------

            for attempt in range(
                1,
                max_retries + 1,
            ):

                try:

                    logs = self.w3.eth.get_logs(
                        params
                    )

                    results.extend(logs)

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
                            2 ** (attempt - 1),
                            8,
                        )

                        time.sleep(delay)

            if success:
                continue

            # --------------------------------------------------------------
            # Split failed range
            # --------------------------------------------------------------

            range_size = (
                current_to
                - current_from
                + 1
            )

            if range_size <= minimum_range:

                logger.error(
                    "RPC failed even after "
                    "reducing range to %s -> %s",
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

        # --------------------------------------------------------------
        # Stable ordering
        # --------------------------------------------------------------

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

    MAX_MESSAGE_LENGTH = 4096

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
    ):

        self.bot_token = (
            str(bot_token).strip()
            if bot_token
            else None
        )

        self.chat_id = (
            str(chat_id).strip()
            if chat_id
            else None
        )

        self.enabled = bool(
            self.bot_token
            and self.chat_id
        )

        if self.enabled:

            # Never log the actual bot token.
            masked_token = (
                self.bot_token[:8]
                + "..."
                if len(self.bot_token) > 8
                else "***"
            )

            logger.info(
                "Telegram alerts enabled "
                "(token=%s, chat_id=%s)",
                masked_token,
                self.chat_id,
            )

        else:

            logger.warning(
                "Telegram alerts disabled: "
                "TELEGRAM_BOT_TOKEN or "
                "TELEGRAM_CHAT_ID missing"
            )

    def send_message(
        self,
        text: str,
    ) -> int | None:

        if not self.enabled:

            logger.debug(
                "Telegram disabled; "
                "message was not sent"
            )

            return None

        if not text:

            logger.warning(
                "Telegram message is empty"
            )

            return None

        # --------------------------------------------------------------
        # Telegram sendMessage has a 4096-character text limit.
        # --------------------------------------------------------------

        if len(text) > self.MAX_MESSAGE_LENGTH:

            logger.warning(
                "Telegram message too long "
                "(%s chars). Truncating to %s.",
                len(text),
                self.MAX_MESSAGE_LENGTH,
            )

            text = text[
                : self.MAX_MESSAGE_LENGTH - 20
            ] + "\n...[truncated]"

        url = (
            "https://api.telegram.org/"
            f"bot{self.bot_token}/sendMessage"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        max_retries = env_int(
            "TELEGRAM_RETRIES",
            3,
        )

        for attempt in range(
            1,
            max_retries + 1,
        ):

            try:

                response = requests.post(
                    url,
                    json=payload,
                    timeout=20,
                )

                # ------------------------------------------------------
                # IMPORTANT:
                #
                # Do NOT call raise_for_status() before reading
                # Telegram's response body.
                #
                # Telegram normally tells us the actual problem in:
                #
                # {"ok":false,"error_code":400,
                #  "description":"..."}
                # ------------------------------------------------------

                if not response.ok:

                    try:

                        error_data = (
                            response.json()
                        )

                    except Exception:

                        error_data = (
                            response.text
                        )

                    logger.error(
                        "Telegram API HTTP error "
                        "(status=%s, attempt=%s/%s): %s",
                        response.status_code,
                        attempt,
                        max_retries,
                        error_data,
                    )

                    # --------------------------------------------------
                    # 400 is normally a permanent configuration/request
                    # problem. Retrying it won't fix a bad chat ID.
                    # --------------------------------------------------

                    if response.status_code == 400:

                        logger.error(
                            "Telegram returned HTTP 400. "
                            "Check TELEGRAM_CHAT_ID, "
                            "make sure the bot has access to the "
                            "chat/channel, and inspect the Telegram "
                            "description above."
                        )

                        return None

                    # --------------------------------------------------
                    # 401 means the bot token is invalid.
                    # --------------------------------------------------

                    if response.status_code == 401:

                        logger.error(
                            "Telegram returned HTTP 401. "
                            "The bot token is invalid/revoked. "
                            "Create a new token and update "
                            "TELEGRAM_BOT_TOKEN."
                        )

                        return None

                    # --------------------------------------------------
                    # Retry temporary server/rate-limit errors.
                    # --------------------------------------------------

                    if attempt < max_retries:

                        delay = min(
                            2 ** (attempt - 1),
                            10,
                        )

                        time.sleep(delay)

                        continue

                    return None

                # ------------------------------------------------------
                # Successful HTTP response
                # ------------------------------------------------------

                try:

                    data = response.json()

                except Exception:

                    logger.error(
                        "Telegram returned invalid JSON: %s",
                        response.text,
                    )

                    return None

                if not data.get("ok"):

                    logger.error(
                        "Telegram API returned ok=false: %s",
                        data,
                    )

                    return None

                result = data.get(
                    "result"
                )

                if not result:

                    logger.error(
                        "Telegram response had no result: %s",
                        data,
                    )

                    return None

                message_id = result.get(
                    "message_id"
                )

                logger.info(
                    "Telegram message sent "
                    "successfully: message_id=%s",
                    message_id,
                )

                return message_id

            except requests.exceptions.Timeout:

                logger.warning(
                    "Telegram request timed out "
                    "(attempt %s/%s)",
                    attempt,
                    max_retries,
                )

                if attempt < max_retries:

                    time.sleep(
                        min(
                            2 ** (attempt - 1),
                            10,
                        )
                    )

                    continue

                return None

            except requests.exceptions.RequestException as exc:

                logger.warning(
                    "Telegram request failed "
                    "(attempt %s/%s): %s",
                    attempt,
                    max_retries,
                    exc,
                )

                if attempt < max_retries:

                    time.sleep(
                        min(
                            2 ** (attempt - 1),
                            10,
                        )
                    )

                    continue

                return None

            except Exception:

                logger.exception(
                    "Unexpected Telegram send failure"
                )

                return None

        return None


# ============================================================================
# ROBINHOOD BOT
# ============================================================================

class RobinhoodBot:

    def __init__(self):

        self.running = True

        # ------------------------------------------------------------------
        # Settings
        # ------------------------------------------------------------------

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
        # Database
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
        # Telegram
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
        # Scanner settings
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
        # Pons detector
        # ------------------------------------------------------------------

        self.pons = PonsDetector()

        # ------------------------------------------------------------------
        # IMPORTANT:
        #
        # Your current PonsDetector.decode_launch(log) expects the
        # detector to already have a Web3 instance configured.
        #
        # Configure it here.
        # ------------------------------------------------------------------

        self.configure_pons_web3()

        logger.info(
            "Detectors: pons"
        )

        # ------------------------------------------------------------------
        # Starting block
        # ------------------------------------------------------------------

        self.start_block = (
            self.get_start_block()
        )

    # ======================================================================
    # PONS WEB3 CONFIGURATION
    # ======================================================================

    def configure_pons_web3(self):

        configured = False

        # --------------------------------------------------------------
        # Support common detector configuration method names.
        # --------------------------------------------------------------

        for method_name in (
            "set_web3",
            "set_w3",
            "configure_web3",
            "configure_w3",
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

                    logger.info(
                        "Configured PonsDetector Web3 "
                        "using %s()",
                        method_name,
                    )

                    configured = True

                    break

                except TypeError:

                    # Some implementations may use
                    # a keyword named w3.
                    try:

                        method(
                            w3=self.chain.w3
                        )

                        logger.info(
                            "Configured PonsDetector Web3 "
                            "using %s(w3=...)",
                            method_name,
                        )

                        configured = True

                        break

                    except Exception:

                        logger.exception(
                            "PonsDetector %s() failed",
                            method_name,
                        )

                except Exception:

                    logger.exception(
                        "PonsDetector %s() failed",
                        method_name,
                    )

        # --------------------------------------------------------------
        # Direct attribute fallback.
        #
        # Your error specifically says:
        #
        # "PonsDetector Web3 instance has not been configured"
        #
        # so the detector almost certainly checks self.w3.
        # --------------------------------------------------------------

        if not configured:

            try:

                self.pons.w3 = self.chain.w3

                configured = (
                    getattr(
                        self.pons,
                        "w3",
                        None,
                    )
                    is self.chain.w3
                )

                if configured:

                    logger.info(
                        "Configured PonsDetector.w3 "
                        "directly"
                    )

            except Exception:

                logger.exception(
                    "Could not configure "
                    "PonsDetector Web3"
                )

        if not configured:

            raise RuntimeError(
                "Could not configure PonsDetector "
                "with the ChainClient Web3 instance"
            )

    # ======================================================================
    # START BLOCK
    # ======================================================================

    def get_start_block(self) -> int:

        # ------------------------------------------------------------------
        # Existing checkpoint
        # ------------------------------------------------------------------

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

                block = int(saved)

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

        # ------------------------------------------------------------------
        # Explicit START_BLOCK
        # ------------------------------------------------------------------

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

        # ------------------------------------------------------------------
        # Pons known deployment start
        # ------------------------------------------------------------------

        pons_start = getattr(
            self.pons,
            "start_block",
            None,
        )

        if pons_start is None:

            pons_start = (
                PonsDetector.start_block
            )

        # ------------------------------------------------------------------
        # Normal bounded backfill
        # ------------------------------------------------------------------

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
    # PROCESS PONS LOG
    # ======================================================================

    def process_pons_log(
        self,
        log: Any,
    ):

        try:

            # --------------------------------------------------------------
            # Your current PonsDetector API is:
            #
            #     decode_launch(log)
            #
            # NOT:
            #
            #     decode_launch(w3, log)
            #
            # Web3 was configured during initialization above.
            # --------------------------------------------------------------

            launch = (
                self.pons.decode_launch(
                    log
                )
            )

            if launch is None:
                return

            # --------------------------------------------------------------
            # Extract basic launch information
            # --------------------------------------------------------------

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
                        raw_tx or ""
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

            # --------------------------------------------------------------
            # DUPLICATE PROTECTION
            # --------------------------------------------------------------

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

                logger.debug(
                    "Launch already processed: %s",
                    unique_key,
                )

                return

            # --------------------------------------------------------------
            # Log launch
            # --------------------------------------------------------------

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

            # --------------------------------------------------------------
            # Save database
            # --------------------------------------------------------------

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

                try:

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

            except Exception:

                logger.exception(
                    "Database insert failed "
                    "for token %s",
                    token_address,
                )

                return

            # --------------------------------------------------------------
            # None means success for some DB implementations.
            # False explicitly means duplicate.
            # --------------------------------------------------------------

            if inserted is False:

                logger.debug(
                    "Database reported existing launch: %s",
                    token_address,
                )

                return

            # --------------------------------------------------------------
            # Telegram
            # --------------------------------------------------------------

            message = (
                self.format_launch_message(
                    launch
                )
            )

            message_id = (
                self.telegram.send_message(
                    message
                )
            )

            if message_id:

                logger.info(
                    "Telegram alert sent "
                    "for %s",
                    token_address,
                )

                try:

                    self.db.update_launch_message(
                        token_address,
                        message_id,
                    )

                except AttributeError:

                    pass

                except Exception:

                    logger.exception(
                        "Could not save "
                        "Telegram message ID"
                    )

            else:

                logger.warning(
                    "Launch saved but Telegram "
                    "alert was not sent: %s",
                    token_address,
                )

        except Exception:

            logger.exception(
                "Pons launch processing failed"
            )

    # ======================================================================
    # TELEGRAM FORMAT
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

        deployer = normalize_address(
            get_value(
                launch,
                "deployer",
                default=None,
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

        pair_token = normalize_address(
            get_value(
                launch,
                "pair_token",
                "pairToken",
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

        block_number = get_value(
            launch,
            "block_number",
            "blockNumber",
            default="?",
        )

        initial_buy = get_value(
            launch,
            "initial_buy_amount",
            "initialBuyAmount",
            default=None,
        )

        lines = [
            "🚀 NEW ROBINHOOD CHAIN LAUNCH",
            "",
            "🪙 Pons Launch",
            "",
            f"📍 Token: {token_address}",
        ]

        if pool_address:

            lines.append(
                f"💧 Pool: {pool_address}"
            )

        if pair_token:

            lines.append(
                f"💱 Pair: {pair_token}"
            )

        if deployer:

            lines.append(
                f"👤 Deployer: {deployer}"
            )

        if initial_buy is not None:

            lines.append(
                f"💰 Initial Buy: {initial_buy}"
            )

        lines.extend(
            [
                f"🧱 Block: {block_number}",
                "",
            ]
        )

        if tx_hash:

            lines.append(
                f"🔗 TX: {tx_hash}"
            )

        lines.extend(
            [
                "",
                "⚡ Robinhood Chain Launch Monitor",
            ]
        )

        return "\n".join(lines)

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
        # Checkpoint only after the RPC scan completed.
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

        current = self.start_block

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

                # ------------------------------------------------------
                # Don't advance the block.
                # Retry the same range.
                # ------------------------------------------------------

                time.sleep(5)

                continue

            current = end + 1

            logger.info(
                "Backfill at block %s",
                current,
            )

        if self.running:

            logger.info(
                "Backfill complete"
            )

    # ======================================================================
    # LIVE MONITOR
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

                time.sleep(5)

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
# MAIN ENTRYPOINT
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
