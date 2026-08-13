import time

from web3 import Web3


class ChainClient:

    def __init__(
        self,
        rpc_url: str,
        chain_id: int,
    ):
        self.w3 = Web3(
            Web3.HTTPProvider(
                rpc_url,
                request_kwargs={
                    "timeout": 20,
                },
            )
        )

        actual_chain_id = self.w3.eth.chain_id

        if actual_chain_id != chain_id:
            raise RuntimeError(
                f"Wrong chain: RPC reports "
                f"{actual_chain_id}, expected {chain_id}"
            )

    @property
    def block_number(self):
        return self.w3.eth.block_number

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
                "address": Web3.to_checksum_address(
                    address
                ),
                "topics": [topic0],
            }
        )

    def retry_logs(
        self,
        address,
        topic0,
        from_block,
        to_block,
        retries=5,
    ):
        delay = 1
        last_error = None

        for _ in range(retries):
            try:
                return self.get_logs(
                    address,
                    topic0,
                    from_block,
                    to_block,
                )

            except Exception as exc:
                last_error = exc

                time.sleep(delay)

                delay = min(
                    delay * 2,
                    8,
                )

        raise last_error

    def read_token_metadata(
        self,
        token,
    ):
        token = Web3.to_checksum_address(
            token
        )

        abi = [
            {
                "name": "name",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {
                        "type": "string"
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
                        "type": "string"
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
                        "type": "uint8"
                    }
                ],
            },
        ]

        contract = self.w3.eth.contract(
            address=token,
            abi=abi,
        )

        result = {}

        for function_name in (
            "name",
            "symbol",
            "decimals",
        ):
            try:
                result[function_name] = getattr(
                    contract.functions,
                    function_name,
                )().call()

            except Exception:
                result[function_name] = None

        return result
