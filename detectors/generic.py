import json

from web3 import Web3
from web3._utils.events import get_event_data

from detectors.base import Launch


class GenericEventDetector:

    """
    Generic detector adapter.

    Use this only after verifying the launchpad's
    factory address and event ABI.
    """

    def __init__(
        self,
        name,
        address,
        topic0,
        event_abi,
        start_block,
    ):
        self.name = name

        self.address = (
            Web3.to_checksum_address(
                address
            )
        )

        self.topic0 = topic0

        self.event_abi = event_abi

        self.start_block = start_block

    @classmethod
    def from_json(
        cls,
        name,
        address,
        topic0,
        abi_json,
        start_block,
    ):
        return cls(
            name,
            address,
            topic0,
            json.loads(abi_json),
            start_block,
        )

    def decode(
        self,
        w3,
        log,
    ):
        decoded = get_event_data(
            w3.codec,
            self.event_abi,
            log,
        )

        args = decoded["args"]

        def first(*names):
            for name in names:
                if name in args:
                    return args[name]

            return None

        token = first(
            "token",
            "tokenAddress",
            "launchToken",
            "newToken",
        )

        if not token:
            raise ValueError(
                f"{self.name}: event has "
                "no recognized token field"
            )

        return Launch(
            detector=self.name,

            token_address=Web3.to_checksum_address(
                token
            ),

            deployer=first(
                "deployer",
                "creator",
                "owner",
            ),

            pool_address=first(
                "pool",
                "poolAddress",
                "pair",
                "pairAddress",
            ),

            pair_token=first(
                "pairToken",
                "pairedToken",
                "quoteToken",
                "currency",
            ),

            tx_hash=log[
                "transactionHash"
            ].hex(),

            block_number=log[
                "blockNumber"
            ],

            log_index=log[
                "logIndex"
            ],
        )
