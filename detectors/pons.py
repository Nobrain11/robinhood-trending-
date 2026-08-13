from web3 import Web3

from web3._utils.events import (
    get_event_data,
)

from detectors.base import Detector

from app.models import Launch


PONS_FACTORY = (
    "0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB"
)


PONS_START_BLOCK = 8991118


PONS_TOKEN_LAUNCHED_TOPIC = (
    "0xdb51ea9ad51ab453a65a4cb7e60c3cb378c9501bb002609f8f97778fb6c4235a"
)


PONS_SWAP_TOPIC = (
    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
)


PONS_WETH = (
    "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
)


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

    address = Web3.to_checksum_address(
        PONS_FACTORY
    )

    topic0 = PONS_TOKEN_LAUNCHED_TOPIC

    start_block = PONS_START_BLOCK


    def decode_launch(
        self,
        w3,
        log,
    ):

        decoded = get_event_data(
            w3.codec,
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

            tx_hash=log[
                "transactionHash"
            ].hex(),

            block_number=log[
                "blockNumber"
            ],

            log_index=log[
                "logIndex"
            ],

            initial_buy_amount=int(
                args["initialBuyAmount"]
            ),
        )
