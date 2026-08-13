import json
import logging
import time

from app.config import Settings
from app.chain import ChainClient
from app.db import Database
from app.telegram import (
    TelegramPublisher,
    build_launch_message,
)

from detectors import build_detectors


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


def enrich(
    chain,
    launch,
):
    metadata = chain.read_token_metadata(
        launch["token_address"]
    )

    launch.update(
        {
            "name": metadata.get(
                "name"
            ),

            "symbol": metadata.get(
                "symbol"
            ),

            "decimals": metadata.get(
                "decimals"
            ),

            "metadata_json": json.dumps(
                metadata
            ),
        }
    )

    return launch


def main():

    settings = Settings()

    settings.validate()

    chain = ChainClient(
        settings.rpc_url,
        settings.chain_id,
    )

    db = Database(
        settings.db_path
    )

    telegram = TelegramPublisher(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        settings.request_timeout,
    )

    detectors = build_detectors()

    log.info(
        "Connected to Robinhood Chain %s",
        chain.w3.eth.chain_id,
    )

    log.info(
        "Enabled detectors: %s",
        ", ".join(
            detector.name
            for detector in detectors
        ),
    )

    state_key = (
        "last_scanned_block"
    )

    saved = db.get_state(
        state_key
    )

    if saved is None:

        last_scanned = (
            min(
                detector.start_block
                for detector in detectors
            )
            - 1
        )

    else:

        last_scanned = int(
            saved
        )

    while True:

        try:

            latest = (
                chain.block_number
                - settings.confirmations
            )

            if latest <= last_scanned:

                time.sleep(
                    settings.poll_seconds
                )

                continue

            target = min(
                latest,
                last_scanned
                + settings.block_chunk,
            )

            log.info(
                "Scanning blocks %s -> %s",
                last_scanned + 1,
                target,
            )

            for detector in detectors:

                start = max(
                    last_scanned + 1,
                    detector.start_block,
                )

                if start > target:
                    continue

                logs = chain.retry_logs(
                    detector.address,
                    detector.topic0,
                    start,
                    target,
                    retries=settings.max_retries,
                )

                for raw_log in logs:

                    try:

                        launch = (
                            detector
                            .decode(
                                chain.w3,
                                raw_log,
                            )
                            .as_dict()
                        )

                        launch = enrich(
                            chain,
                            launch,
                        )

                        inserted = (
                            db.insert_launch(
                                launch
                            )
                        )

                        if not inserted:
                            continue

                        message = (
                            build_launch_message(
                                launch,
                                settings.explorer_base,
                            )
                        )

                        message_id = (
                            telegram.send(
                                message
                            )
                        )

                        db.set_telegram_message_id(
                            launch["detector"],
                            launch[
                                "token_address"
                            ],
                            launch[
                                "tx_hash"
                            ],
                            launch[
                                "log_index"
                            ],
                            message_id,
                        )

                        log.info(
                            "POSTED %s $%s %s",
                            launch[
                                "detector"
                            ],
                            launch.get(
                                "symbol"
                            ) or "?",
                            launch[
                                "token_address"
                            ],
                        )

                    except Exception:

                        log.exception(
                            "Failed processing "
                            "%s log in block %s",
                            detector.name,
                            raw_log[
                                "blockNumber"
                            ],
                        )

            last_scanned = target

            db.set_state(
                state_key,
                str(last_scanned),
            )

        except Exception:

            log.exception(
                "Scanner loop failed; retrying"
            )

        time.sleep(
            settings.poll_seconds
        )


if __name__ == "__main__":
    main()
