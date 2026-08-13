import time

from web3 import Web3


TOKEN_ABI = [

    {
        "name": "name",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {
                "type": "string",
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
            }
        ],
    },

    {
        "name": "totalSupply",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {
                "type": "uint256",
            }
        ],
    },

    {
        "name": "liquidityPool",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {
                "type": "address",
            }
        ],
    },
]


PONS_FACTORY_ABI = [

    {
        "name": "getLaunchedToken",
        "type": "function",
        "stateMutability": "view",

        "inputs": [
            {
                "name": "token",
                "type": "address",
            }
        ],

        "outputs": [
            {
                "name": "launched",
                "type": "tuple",

                "components": [

                    {
                        "name": "token",
                        "type": "address",
                    },

                    {
                        "name": "deployer",
                        "type": "address",
                    },

                    {
                        "name": "pairedToken",
                        "type": "address",
                    },

                    {
                        "name": "positionManager",
                        "type": "address",
                    },

                    {
                        "name": "positionId",
                        "type": "uint256",
                    },

                    {
                        "name": "dexId",
                        "type": "uint256",
                    },

                    {
                        "name": "launchConfigId",
                        "type": "uint256",
                    },

                    {
                        "name": "restrictionsEndBlock",
                        "type": "uint256",
                    },

                    {
                        "name": "supply",
                        "type": "uint256",
                    },

                    {
                        "name": "isToken0",
                        "type": "bool",
                    },

                    {
                        "name": "poolFee",
                        "type": "uint24",
                    },

                    {
                        "name": "exists",
                        "type": "bool",
                    },

                    {
                        "name": "initialBuyAmount",
                        "type": "uint256",
                    },
                ],
            }
        ],
    },

    {
        "name": "graduationStatus",
        "type": "function",
        "stateMutability": "view",

        "inputs": [
            {
                "name": "token",
                "type": "address",
            }
        ],

        "outputs": [

            {
                "name": "pairedPrincipal",
                "type": "uint256",
            },

            {
                "name": "threshold",
                "type": "uint256",
            },

            {
                "name": "graduated",
                "type": "bool",
            },
        ],
    },
]


class ChainClient:

    def __init__(
        self,
        rpc_url,
        chain_id,
        timeout=20,
    ):

        self.w3 = Web3(
            Web3.HTTPProvider(
                rpc_url,
                request_kwargs={
                    "timeout": timeout,
                },
            )
        )

        actual = self.w3.eth.chain_id

        if actual != chain_id:

            raise RuntimeError(
                f"Wrong chain. "
                f"Got {actual}; "
                f"expected {chain_id}."
            )


    @property
    def block_number(self):

        return self.w3.eth.block_number


    def get_block(
        self,
        block_number,
    ):

        return self.w3.eth.get_block(
            block_number
        )


    def get_logs(
        self,
        address,
        topic0,
        from_block,
        to_block,
    ):

        return self.w3.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,

                "address":
                    Web3.to_checksum_address(
                        address
                    ),

                "topics": [
                    topic0
                ],
            }
        )


    def get_logs_by_topic(
        self,
        topic0,
        from_block,
        to_block,
    ):

        return self.w3.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,

                "topics": [
                    topic0
                ],
            }
        )


    def retry(
        self,
        function,
        retries=5,
    ):

        delay = 1

        last_error = None

        for _ in range(retries):

            try:

                return function()

            except Exception as exc:

                last_error = exc

                time.sleep(delay)

                delay = min(
                    delay * 2,
                    10,
                )

        raise last_error


    def token_metadata(
        self,
        token,
    ):

        token = Web3.to_checksum_address(
            token
        )

        contract = self.w3.eth.contract(
            address=token,
            abi=TOKEN_ABI,
        )

        result = {}

        for function_name in (
            "name",
            "symbol",
            "decimals",
            "totalSupply",
        ):

            try:

                result[function_name] = (
                    getattr(
                        contract.functions,
                        function_name,
                    )().call()
                )

            except Exception:

                result[function_name] = None

        try:

            result["liquidityPool"] = (
                contract.functions
                .liquidityPool()
                .call()
            )

        except Exception:

            result["liquidityPool"] = None

        return result


    def pons_launch_state(
        self,
        factory,
        token,
    ):

        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(
                factory
            ),
            abi=PONS_FACTORY_ABI,
        )

        result = contract.functions \
            .getLaunchedToken(
                Web3.to_checksum_address(
                    token
                )
            ) \
            .call()

        return result


    def pons_graduation(
        self,
        factory,
        token,
    ):

        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(
                factory
            ),
            abi=PONS_FACTORY_ABI,
        )

        return contract.functions \
            .graduationStatus(
                Web3.to_checksum_address(
                    token
                )
            ) \
            .call()
