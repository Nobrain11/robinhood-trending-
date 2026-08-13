import json
import logging
import threading
import time

import websocket


log = logging.getLogger(
    "robinhood-websocket"
)


class ChainWebSocket:

    def __init__(
        self,
        url,
        on_block,
        on_log,
    ):

        self.url = url

        self.on_block = on_block

        self.on_log = on_log

        self.running = True

        self.ws = None


    def run(self):

        while self.running:

            try:

                self._connect()

            except Exception:

                log.exception(
                    "WebSocket failed"
                )

                time.sleep(5)


    def stop(self):

        self.running = False

        if self.ws:

            try:

                self.ws.close()

            except Exception:

                pass


    def _connect(self):

        log.info(
            "Connecting to %s",
            self.url,
        )

        self.ws = websocket.create_connection(
            self.url,
            timeout=30,
        )

        # Subscribe to new blocks.
        self._send(
            {
                "jsonrpc": "2.0",

                "id": 1,

                "method": "eth_subscribe",

                "params": [
                    "newHeads"
                ],
            }
        )

        # Subscribe globally to logs.
        #
        # The application filters the logs by
        # known topics/pools after receiving them.
        self._send(
            {
                "jsonrpc": "2.0",

                "id": 2,

                "method": "eth_subscribe",

                "params": [
                    "logs",
                    {},
                ],
            }
        )

        log.info(
            "WebSocket subscriptions active"
        )

        while self.running:

            raw = self.ws.recv()

            if not raw:

                raise RuntimeError(
                    "WebSocket closed"
                )

            message = json.loads(
                raw
            )

            self._handle(
                message
            )


    def _send(
        self,
        payload,
    ):

        self.ws.send(
            json.dumps(
                payload
            )
        )


    def _handle(
        self,
        message,
    ):

        if (
            message.get("method")
            != "eth_subscription"
        ):

            return

        params = message.get(
            "params",
            {},
        )

        result = params.get(
            "result"
        )

        subscription = params.get(
            "subscription"
        )

        if not result:

            return

        # newHeads
        if "number" in result:

            self.on_block(
                result
            )

            return

        # logs
        if "topics" in result:

            self.on_log(
                result
            )
