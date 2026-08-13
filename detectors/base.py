from dataclasses import dataclass
from typing import Protocol


@dataclass
class Launch:

    detector: str

    token_address: str

    deployer: str | None

    pool_address: str | None

    pair_token: str | None

    tx_hash: str

    block_number: int

    log_index: int

    initial_buy_amount: str | None = None

    name: str | None = None

    symbol: str | None = None

    decimals: int | None = None

    metadata_json: str | None = None

    def as_dict(self):
        return self.__dict__.copy()


class Detector(Protocol):

    name: str

    address: str

    topic0: str

    start_block: int

    def decode(
        self,
        w3,
        log,
    ) -> Launch:
        ...
