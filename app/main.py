import json
import logging
import threading
import time

from web3 import Web3

from app.chain import ChainClient

from app.config import Settings

from app.database import Database

from app.models import (
    Launch,
    Trade,
)

from app.scoring import (
    calculate_metrics,
)

from app.telegram import (
    TelegramPublisher,
    launch_message,
    trending_message,
    graduation_message,
)

from app.websocket import (
    ChainWebSocket,
)

from detectors import (
    build_detectors,
)


logging.basicConfig(
    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)


log = logging.getLogger(
    "robinhood-launch-bot"
)


class RobinhoodBot:

    def __init__(self):

        self.settings = Settings()

        self.settings.validate()

        self.chain = ChainClient(
            self.settings.rpc_url,
            self.settings.chain_id,
            self.settings.request_timeout,
        )

        self.db = Database(
            self.settings.db_path
        )

        self.telegram = TelegramPublisher(
            self.settings.telegram_bot_token,
            self.settings.telegram_chat_id,
            self.settings.request_timeout,
        )

        self.detectors = (
            build_detectors()
        )

        self.detectors_by_address = {
            detector.address.lower():
                detector
            for detector in self.detectors
        }

        self.topic_to_detector = {
            detector.topic0.lower():
                detector
            for detector in self.detectors
        }

        self.pool_tokens = {}

        self.pool_info = {}

        self.running = True


    # ========================================================
    # START
    # ========================================================

    def start(self):

        log.info(
            "Robinhood Chain bot starting"
        )

        log.info(
            "Chain ID: %s",
            self.chain.w3.eth.chain_id,
        )

        log.info(
            "Detectors: %s",
            ", ".join(
                detector.name
                for detector in self.detectors
            ),
        )

        self.load_existing_pools()

        self.backfill()

        websocket_client = (
            ChainWebSocket(
                self.settings.ws_url,
                self.on_new_block,
                self.on_live_log,
            )
        )

        ws_thread = threading.Thread(
            target=websocket_client.run,
            daemon=True,
        )

        ws_thread.start()

        trend_thread = threading.Thread(
            target=self.trending_loop,
            daemon=True,
        )

        trend_thread.start()

        graduation_thread = threading.Thread(
            target=self.graduation_loop,
            daemon=True,
        )

        graduation_thread.start()

        log.info(
            "Bot is live"
        )

        try:

            while self.running:

                time.sleep(1)

        except KeyboardInterrupt:

            log.info(
                "Stopping bot"
            )

            self.running = False

            websocket_client.stop()


    # ========================================================
    # LOAD EXISTING POOLS
    # ========================================================

    def load_existing_pools(self):

        rows = self.db.active_tokens()

        for row in rows:

            if not row["pool_address"]:

                continue

            self.pool_tokens[
                row["pool_address"].lower()
            ] = row["token_address"]

            self.pool_info[
                row["pool_address"].lower()
            ] = {
                "token_address":
                    row["token_address"],

                "pair_token":
                    row["pair_token"],

                "is_token0":
                    bool(row["is_token0"]),
            }


    # ========================================================
    # HISTORICAL BACKFILL
    # ========================================================

    def backfill(self):

        state = self.db.get_state(
            "last_scanned_block"
        )

        if state:

            last_block = int(
                state
            )

        else:

            last_block = (
                min(
                    detector.start_block
                    for detector in self.detectors
                )
                - 1
            )


        latest = (
            self.chain.block_number
            - self.settings.confirmations
        )


        log.info(
            "Backfill %s -> %s",
            last_block + 1,
            latest,
        )


        while (
            last_block < latest
        ):

            end = min(
                last_block
                + self.settings.block_chunk,
                latest,
            )


            for detector in self.detectors:

                start = max(
                    last_block + 1,
                    detector.start_block,
                )

                if start > end:

                    continue


                logs = self.chain.retry(
                    lambda:
                        self.chain.get_logs(
                            detector.address,
                            detector.topic0,
                            start,
                            end,
                        ),

                    self.settings.max_retries,
                )


                for raw_log in logs:

                    self.process_launch_log(
                        detector,
                        raw_log,
                    )


            last_block = end

            self.db.set_state(
                "last_scanned_block",
                str(last_block),
            )


            log.info(
                "Backfill at block %s",
                last_block,
            )


    # ========================================================
    # LIVE BLOCK
    # ========================================================

    def on_new_block(
        self,
        header,
    ):

        try:

            block_number = int(
                header["number"],
                16,
            )

        except Exception:

            return


        # We primarily use WebSocket for
        # low-latency notification.
        #
        # The actual launch/trade data is still
        # obtained from canonical RPC logs.

        try:

            self.db.set_state(
                "latest_live_block",
                str(block_number),
            )

        except Exception:

            pass


    # ========================================================
    # LIVE LOG
    # ========================================================

    def on_live_log(
        self,
        raw_log,
    ):

        topics = raw_log.get(
            "topics",
            [],
        )

        if not topics:

            return


        topic0 = (
            topics[0]
            .lower()
        )


        # ----------------------------------------------------
        # Launch detector
        # ----------------------------------------------------

        detector = (
            self.topic_to_detector.get(
                topic0
            )
        )


        if detector:

            self.process_launch_log(
                detector,
                raw_log,
            )

            return


        # ----------------------------------------------------
        # V3 Swap
        # ----------------------------------------------------

        if topic0 == (
            "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
        ):

            self.process_swap(
                raw_log
            )


    # ========================================================
    # LAUNCH
    # ========================================================

    def process_launch_log(
        self,
        detector,
        raw_log,
    ):

        try:

            launch = detector.decode_launch(
                self.chain.w3,
                raw_log,
            )


            metadata = (
                self.chain.token_metadata(
                    launch.token_address
                )
            )


            launch.name = (
                metadata.get(
                    "name"
                )
            )


            launch.symbol = (
                metadata.get(
                    "symbol"
                )
            )


            launch.decimals = (
                metadata.get(
                    "decimals"
                )
            )


            launch.supply = (
                metadata.get(
                    "totalSupply"
                )
            )


            block = self.chain.get_block(
                launch.block_number
            )


            launch.launch_timestamp = (
                int(
                    block["timestamp"]
                )
            )


            # Pons launch state
            if detector.name == "pons":

                state = (
                    self.chain.pons_launch_state(
                        detector.address,
                        launch.token_address,
                    )
                )

                launch.is_token0 = (
                    bool(
                        state["isToken0"]
                    )
                )

                launch.pool_fee = (
                    int(
                        state["poolFee"]
                    )
                )


            inserted = (
                self.db.insert_launch(
                    launch
                )
            )


            if not inserted:

                return


            self.register_pool(
                launch
            )


            row = self.db.get_launch(
                launch.token_address
            )


            message = launch_message(
                dict(row),
                self.settings.explorer_base,
            )


            message_id = (
                self.telegram.send(
                    message
                )
            )


            self.db.update_launch_message(
                launch.token_address,
                message_id,
            )


            log.info(
                "NEW LAUNCH: %s $%s",
                launch.detector,
                launch.symbol,
            )


        except Exception:

            log.exception(
                "Launch processing failed"
            )


    # ========================================================
    # REGISTER POOL
    # ========================================================

    def register_pool(
        self,
        launch,
    ):

        if not launch.pool_address:

            return


        pool = (
            launch.pool_address.lower()
        )


        self.pool_tokens[
            pool
        ] = launch.token_address


        self.pool_info[
            pool
        ] = {

            "token_address":
                launch.token_address,

            "pair_token":
                launch.pair_token,

            "is_token0":
                launch.is_token0,
        }


        log.info(
            "Registered pool %s",
            pool,
        )


    # ========================================================
    # SWAP
    # ========================================================

    def process_swap(
        self,
        raw_log,
    ):

        pool = (
            raw_log.get(
                "address"
            )
        )


        if not pool:

            return


        pool_key = pool.lower()


        if pool_key not in self.pool_tokens:

            return


        token = (
            self.pool_tokens[
                pool_key
            ]
        )


        info = (
            self.pool_info[
                pool_key
            ]
        )


        try:

            trade = (
                self.decode_v3_swap(
                    raw_log,
                    token,
                    pool,
                    info,
                )
            )

            if trade is None:

                return


            if self.db.insert_trade(
                trade
            ):

                log.info(
                    "TRADE %s %s %.4f",
                    trade.side,
                    token,
                    trade.quote_amount,
                )


        except Exception:

            log.exception(
                "Swap processing failed"
            )


    # ========================================================
    # V3 SWAP DECODER
    # ========================================================

    def decode_v3_swap(
        self,
        raw_log,
        token,
        pool,
        info,
    ):

        # Uniswap V3 Swap:
        #
        # event Swap(
        #   address indexed sender,
        #   address indexed recipient,
        #   int256 amount0,
        #   int256 amount1,
        #   uint160 sqrtPriceX96,
        #   uint128 liquidity,
        #   int24 tick
        # )
        #
        # topics:
        #   [0] event signature
        #   [1] sender
        #   [2] recipient
        #
        # data:
        #   amount0
        #   amount1
        #   sqrtPriceX96
        #   liquidity
        #   tick

        topics = (
            raw_log["topics"]
        )


        if len(topics) < 3:

            return None


        sender = (
            "0x"
            + topics[1][-40:]
        )


        data = (
            raw_log["data"]
        )


        if isinstance(
            data,
            str,
        ):

            data = data[2:]


        # amount0 = int256
        amount0 = int.from_bytes(
            bytes.fromhex(
                data[0:64]
            ),
            byteorder="big",
            signed=True,
        )


        # amount1 = int256
        amount1 = int.from_bytes(
            bytes.fromhex(
                data[64:128]
            ),
            byteorder="big",
            signed=True,
        )


        is_token0 = bool(
            info["is_token0"]
        )


        # The pons docs define:
        #
        # tokenIsToken0 = token < pairToken
        #
        # pairSigned =
        #   tokenIsToken0
        #       ? amount1
        #       : amount0
        #
        # pairSigned > 0 = buy
        #
        pair_signed = (
            amount1
            if is_token0
            else amount0
        )


        if pair_signed > 0:

            side = "buy"

        else:

            side = "sell"


        token_signed = (
            amount0
            if is_token0
            else amount1
        )


        token_amount = (
            abs(
                token_signed
            )
            / 1e18
        )


        quote_amount = (
            abs(
                pair_signed
            )
            / 1e18
        )


        block_number = int(
            raw_log[
                "blockNumber"
            ],
            16
        )


        log_index = int(
            raw_log[
                "logIndex"
            ],
            16
        )


        timestamp = int(
            time.time()
        )


        return Trade(

            token_address=token,

            pool_address=pool,

            tx_hash=(
                "0x"
                + raw_log[
                    "transactionHash"
                ][2:]
            ),

            block_number=block_number,

            log_index=log_index,

            trader=sender,

            side=side,

            token_amount=token_amount,

            quote_amount=quote_amount,

            timestamp=timestamp,
        )


    # ========================================================
    # TRENDING
    # ========================================================

    def trending_loop(
        self,
    ):

        while self.running:

            try:

                self.update_trending()

            except Exception:

                log.exception(
                    "Trending engine failed"
                )

            time.sleep(
                self.settings
                .trend_interval_seconds
            )


    def update_trending(
        self,
    ):

        now = int(
            time.time()
        )


        cutoff = (
            now
            - self.settings
            .trend_window_seconds
        )


        for row in (
            self.db.active_tokens()
        ):

            token = (
                row["token_address"]
            )


            trades = (
                self.db.trades_since(
                    token,
                    cutoff,
                )
            )


            metrics = (
                calculate_metrics(
                    token,
                    trades,
                    self.settings
                    .trend_window_seconds,
                )
            )


            if (
                metrics.swap_count
                < self.settings
                .min_swaps_for_trend
            ):

                continue


            if (
                metrics.unique_buyers
                < self.settings
                .min_buyers_for_trend
            ):

                continue


            self.db.set_trend(
                token,
                metrics.score,
                now,
            )


            previous_alert = (
                row["last_trend_alert"]
                or 0
            )


            cooldown = (
                now
                - previous_alert
            )


            if (
                metrics.score
                >= self.settings
                .trend_alert_score
                and cooldown
                >= self.settings
                .trend_cooldown_seconds
            ):

                message = (
                    trending_message(
                        dict(row),
                        metrics,
                    )
                )


                self.telegram.send(
                    message
                )


                self.db.set_trend(
                    token,
                    metrics.score,
                    now,
                )


                log.info(
                    "TRENDING %s %.1f",
                    row["symbol"],
                    metrics.score,
                )


    # ========================================================
    # GRADUATION
    # ========================================================

    def graduation_loop(
        self,
    ):

        while self.running:

            try:

                self.check_graduations()

            except Exception:

                log.exception(
                    "Graduation monitor failed"
                )

            time.sleep(
                30
            )


    def check_graduations(
        self,
    ):

        for row in (
            self.db.active_tokens()
        ):

            if row["detector"] != "pons":

                continue


            if row["graduated"]:

                continue


            try:

                (
                    paired,
                    threshold,
                    graduated,
                ) = (
                    self.chain
                    .pons_graduation(
                        self.detectors_by_address[
                            self._detector_address(
                                row["detector"]
                            )
                        ].address,
                        row["token_address"],
                    )
                )


                if not graduated:

                    continue


                latest_block = (
                    self.chain.block_number
                )


                self.db.mark_graduated(
                    row["token_address"],
                    latest_block,
                )


                fresh = dict(
                    self.db.get_launch(
                        row["token_address"]
                    )
                )


                self.telegram.send(
                    graduation_message(
                        fresh
                    )
                )


                log.info(
                    "GRADUATED %s",
                    row["symbol"],
                )


            except Exception:

                log.exception(
                    "Graduation check failed "
                    "for %s",
                    row["token_address"],
                )


    def _detector_address(
        self,
        detector_name,
    ):

        for detector in self.detectors:

            if detector.name == detector_name:

                return detector.address

        raise ValueError(
            f"Unknown detector: "
            f"{detector_name}"
        )


def main():

    bot = RobinhoodBot()

    bot.start()


if __name__ == "__main__":

    main()
