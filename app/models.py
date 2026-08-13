from dataclasses import dataclass
from typing import Optional


@dataclass
class Launch:

    detector: str

    token_address: str

    deployer: Optional[str]

    pool_address: Optional[str]

    pair_token: Optional[str]

    tx_hash: str

    block_number: int

    log_index: int

    initial_buy_amount: Optional[int] = None

    name: Optional[str] = None

    symbol: Optional[str] = None

    decimals: Optional[int] = None

    supply: Optional[int] = None

    is_token0: Optional[bool] = None

    pool_fee: Optional[int] = None

    launch_timestamp: Optional[int] = None

    telegram_message_id: Optional[int] = None


@dataclass
class Trade:

    token_address: str

    pool_address: str

    tx_hash: str

    block_number: int

    log_index: int

    trader: Optional[str]

    side: str

    token_amount: float

    quote_amount: float

    timestamp: int


@dataclass
class Metrics:

    token_address: str

    volume_quote: float

    buys: int

    sells: int

    unique_buyers: int

    unique_sellers: int

    swap_count: int

    buy_ratio: float

    volume_velocity: float

    buyer_velocity: float

    score: float
