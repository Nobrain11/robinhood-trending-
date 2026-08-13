import html

import requests


class TelegramPublisher:

    def __init__(
        self,
        bot_token,
        chat_id,
        timeout=15,
    ):
        self.chat_id = chat_id
        self.timeout = timeout

        self.base = (
            f"https://api.telegram.org/"
            f"bot{bot_token}"
        )

    def send(
        self,
        text,
    ):
        response = requests.post(
            f"{self.base}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(data)

        return int(
            data["result"]["message_id"]
        )


def esc(value):
    if value is None:
        return "—"

    return html.escape(
        str(value)
    )


def short_address(value):
    if not value:
        return "—"

    return (
        f"{value[:6]}"
        f"…"
        f"{value[-4:]}"
    )


def build_launch_message(
    launch,
    explorer_base,
):
    token = launch["token_address"]

    tx = launch["tx_hash"]

    name = (
        launch.get("name")
        or "Unknown Token"
    )

    symbol = (
        launch.get("symbol")
        or "UNKNOWN"
    )

    deployer = launch.get(
        "deployer"
    )

    pool = launch.get(
        "pool_address"
    )

    pair = launch.get(
        "pair_token"
    )

    initial_buy = launch.get(
        "initial_buy_amount"
    )

    return (
        "🚨 <b>"
        "NEW ROBINHOOD CHAIN LAUNCH"
        "</b>\n\n"

        f"🪙 <b>${esc(symbol)}</b>"
        f" — {esc(name)}\n"

        f"🚀 <b>Launchpad:</b> "
        f"{esc(launch['detector'])}\n"

        f"📦 <b>Block:</b> "
        f"{launch['block_number']}\n"

        f"💰 <b>Initial buy:</b> "
        f"{esc(initial_buy)}\n\n"

        f"📜 <b>Contract:</b> "
        f"<code>{esc(token)}</code>\n"

        f"👤 <b>Deployer:</b> "
        f"<code>{esc(short_address(deployer))}"
        f"</code>\n"

        f"💧 <b>Pool:</b> "
        f"<code>{esc(short_address(pool))}"
        f"</code>\n"

        f"🪙 <b>Pair:</b> "
        f"<code>{esc(short_address(pair))}"
        f"</code>\n\n"

        f'<a href="{explorer_base}'
        f'/address/{token}">'
        f'Contract</a> · '

        f'<a href="{explorer_base}'
        f'/tx/{tx}">'
        f'TX</a> · '

        f'<a href="{explorer_base}'
        f'/address/{pool}">'
        f'Pool</a>'
    )
