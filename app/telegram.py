import html

import requests


class TelegramPublisher:

    def __init__(
        self,
        bot_token,
        chat_id,
        timeout=20,
    ):

        self.chat_id = chat_id

        self.timeout = timeout

        self.base = (
            "https://api.telegram.org/"
            f"bot{bot_token}"
        )


    def _request(
        self,
        method,
        payload,
    ):

        response = requests.post(
            f"{self.base}/{method}",
            json=payload,
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):

            raise RuntimeError(
                data
            )

        return data["result"]


    def send(
        self,
        text,
    ):

        result = self._request(
            "sendMessage",
            {
                "chat_id": self.chat_id,

                "text": text,

                "parse_mode": "HTML",

                "disable_web_page_preview": True,
            },
        )

        return int(
            result["message_id"]
        )


    def edit(
        self,
        message_id,
        text,
    ):

        self._request(
            "editMessageText",
            {
                "chat_id": self.chat_id,

                "message_id": message_id,

                "text": text,

                "parse_mode": "HTML",

                "disable_web_page_preview": True,
            },
        )


def esc(value):

    if value is None:

        return "—"

    return html.escape(
        str(value)
    )


def short_address(
    address,
):

    if not address:

        return "—"

    return (
        address[:6]
        + "…"
        + address[-4:]
    )


def launch_message(
    launch,
    explorer_base,
):

    return (
        "🚨 <b>"
        "NEW ROBINHOOD CHAIN LAUNCH"
        "</b>\n\n"

        f"🪙 <b>${esc(launch['symbol'])}"
        f"</b> — "
        f"{esc(launch['name'])}\n\n"

        f"🚀 <b>Launchpad:</b> "
        f"{esc(launch['detector'])}\n"

        f"📦 <b>Block:</b> "
        f"{launch['block_number']}\n"

        f"💧 <b>Pool:</b> "
        f"<code>"
        f"{esc(short_address(launch['pool_address']))}"
        f"</code>\n\n"

        f"📜 <b>Contract</b>\n"
        f"<code>{esc(launch['token_address'])}"
        f"</code>\n\n"

        f"👤 <b>Deployer:</b> "
        f"<code>"
        f"{esc(short_address(launch['deployer']))}"
        f"</code>\n\n"

        f'<a href="{explorer_base}'
        f'/address/{launch["token_address"]}">'
        f'Explorer</a> · '

        f'<a href="{explorer_base}'
        f'/tx/{launch["tx_hash"]}">'
        f'Transaction</a>'
    )


def trending_message(
    launch,
    metrics,
):

    return (
        "🔥 <b>"
        "TRENDING ON ROBINHOOD CHAIN"
        "</b>\n\n"

        f"🪙 <b>${esc(launch['symbol'])}"
        f"</b> — "
        f"{esc(launch['name'])}\n\n"

        f"⚡ <b>Score:</b> "
        f"{metrics.score:.0f}/100\n\n"

        f"💰 <b>Volume:</b> "
        f"{metrics.volume_quote:.4f} WETH\n"

        f"🟢 <b>Buys:</b> "
        f"{metrics.buys}\n"

        f"🔴 <b>Sells:</b> "
        f"{metrics.sells}\n"

        f"👥 <b>Buyers:</b> "
        f"{metrics.unique_buyers}\n"

        f"📊 <b>Swaps:</b> "
        f"{metrics.swap_count}\n"

        f"📈 <b>Buy pressure:</b> "
        f"{metrics.buy_ratio * 100:.1f}%\n\n"

        f"🚀 <b>{esc(launch['detector'])}</b>"
    )


def graduation_message(
    launch,
):

    return (
        "🎓 <b>"
        "GRADUATED"
        "</b>\n\n"

        f"🪙 <b>${esc(launch['symbol'])}"
        f"</b> — "
        f"{esc(launch['name'])}\n\n"

        f"🚀 <b>Launchpad:</b> "
        f"{esc(launch['detector'])}\n"

        f"📜 <b>Contract:</b>\n"
        f"<code>{esc(launch['token_address'])}"
        f"</code>\n\n"

        "Trading continues in the same pool."
    )
