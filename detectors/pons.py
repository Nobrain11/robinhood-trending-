from __future__ import annotations

import logging

from web3 import Web3
from web3._utils.events import get_event_data

from detectors.base import Detector
from app.models import Launch


logger = logging.getLogger(
    "robinhood-launch-bot.pons"
)


# ---------------------------------------------------------------------------
# Pons
# ---------------------------------------------------------------------------

PONS_FACTORY = Web3.to_checksum_address(
    "0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB"
)

PONS_START_BLOCK = 8991118

PONS_TOKEN_LAUNCHED_TOPIC = (
    "0xdb51ea9ad51ab453a65a4cb7e60c3cb378c9501bb002609f8f97778fb6c4235a"
)

PONS_SWAP_TOPIC = (
    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
)

PONS_WETH = Web3.to_checksum_address(
    "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
)


# ---------------------------------------------------------------------------
# ABI
# ---------------------------------------------------------------------------

TOKEN_LAUNCHED_ABI = {
    "anonymous": False,
    "inputs": [
        {
            "indexed": True,
            "name": "token",
            "type": "address",
        },
        {
            "indexed": True,
            "name": "deployer",
            "type": "address",
        },
        {
            "indexed": True,
            "name": "dexFactory",
            "type": "address",
        },
        {
            "indexed": False,
            "name": "pairToken",
            "type": "address",
        },
        {
            "indexed": False,
            "name": "pool",
            "type": "address",
        },
        {
            "indexed": False,
            "name": "dexId",
            "type": "uint256",
        },
        {
            "indexed": False,
            "name": "launchConfigId",
            "type": "uint256",
        },
        {
            "indexed": False,
            "name": "positionId",
            "type": "uint256",
        },
        {
            "indexed": False,
            "name": "restrictionsEndBlock",
            "type": "uint256",
        },
        {
            "indexed": False,
            "name": "initialBuyAmount",
            "type": "uint256",
        },
    ],
    "name": "TokenLaunched",
    "type": "event",
}


class PonsDetector(Detector):

    name = "pons"

    address = PONS_FACTORY

    topic0 = PONS_TOKEN_LAUNCHED_TOPIC

    start_block = PONS_START_BLOCK

    def detect(
        self,
        log,
    ):
        """
        Main detector entry point.

        The main application calls:

            detector.detect(log)

        We only attempt to decode logs emitted by the Pons factory
        and carrying the TokenLaunched topic.
        """

        if not log:
            return None

        # ---------------------------------------------------------------
        # Verify emitting contract
        # ---------------------------------------------------------------

        log_address = log.get(
            "address"
        )

        if log_address:

            try:

                log_address = Web3.to_checksum_address(
                    log_address
                )

            except Exception:

                return None

            if log_address != self.address:

                return None

        # ---------------------------------------------------------------
        # Verify event topic
        # ---------------------------------------------------------------

        topics = log.get(
            "topics",
            []
        )

        if not topics:
            return None

        topic0 = topics[0]

        if hasattr(
            topic0,
            "hex",
        ):

            topic0 = topic0.hex()

        topic0 = str(
            topic0
        ).lower()

        if topic0 != self.topic0.lower():

            return None

        try:

            return self.decode_launch(
                log
            )

        except Exception:

            logger.exception(
                "Failed to decode Pons TokenLaunched event"
            )

            return None

    def process_log(
        self,
        log,
    ):
        """
        Compatibility alias for older detector code.
        """

        return self.detect(
            log
        )

    def decode_launch(
        self,
        log,
    ):
        """
        Decode a Pons TokenLaunched event.

        Note:
        Web3's event decoder needs a codec, so the caller can provide
        a Web3 instance through set_web3(), or we can use the codec
        supplied during initialization.
        """

        if not hasattr(
            self,
            "_w3",
        ):

            raise RuntimeError(
                "PonsDetector Web3 instance has not been configured"
            )

        decoded = get_event_data(
            self._w3.codec,
            TOKEN_LAUNCHED_ABI,
            log,
        )

        args = decoded["args"]

        token = Web3.to_checksum_address(
            args["token"]
        )

        deployer = Web3.to_checksum_address(
            args["deployer"]
        )

        pool = Web3.to_checksum_address(
            args["pool"]
        )

        pair_token = Web3.to_checksum_address(
            args["pairToken"]
        )

        return Launch(
            detector=self.name,

            token_address=token,

            deployer=deployer,

            pool_address=pool,

            pair_token=pair_token,

            tx_hash=(
                log["transactionHash"].hex()
                if hasattr(
                    log["transactionHash"],
                    "hex",
                )
                else str(
                    log["transactionHash"]
                )
            ),

            block_number=int(
                log["blockNumber"]
            ),

            log_index=int(
                log["logIndex"]
            ),

            initial_buy_amount=int(
                args["initialBuyAmount"]
            ),
        )

    def set_web3(
        self,
        w3,
    ):
        """
        Give the detector access to the Web3 codec used by the
        event decoder.
        """

        self._w3 = w3

        return self
