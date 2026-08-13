import math

from collections import defaultdict

from app.models import Metrics


def clamp(
    value,
    minimum,
    maximum,
):

    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def calculate_metrics(
    token_address,
    trades,
    window_seconds,
):

    if not trades:

        return Metrics(
            token_address=token_address,
            volume_quote=0,
            buys=0,
            sells=0,
            unique_buyers=0,
            unique_sellers=0,
            swap_count=0,
            buy_ratio=0,
            volume_velocity=0,
            buyer_velocity=0,
            score=0,
        )


    buys = [
        trade
        for trade in trades
        if trade["side"] == "buy"
    ]


    sells = [
        trade
        for trade in trades
        if trade["side"] == "sell"
    ]


    volume = sum(
        abs(
            trade["quote_amount"]
        )
        for trade in trades
    )


    buy_volume = sum(
        abs(
            trade["quote_amount"]
        )
        for trade in buys
    )


    unique_buyers = {
        trade["trader"]
        for trade in buys
        if trade["trader"]
    }


    unique_sellers = {
        trade["trader"]
        for trade in sells
        if trade["trader"]
    }


    swap_count = len(
        trades
    )


    buy_ratio = (
        buy_volume / volume
        if volume > 0
        else 0
    )


    volume_velocity = (
        volume
        / max(
            window_seconds / 60,
            1,
        )
    )


    buyer_velocity = (
        len(unique_buyers)
        / max(
            window_seconds / 60,
            1,
        )
    )


    # ---------------------------------------------------------
    # Score
    # ---------------------------------------------------------
    #
    # 25 points: volume
    # 20 points: buy pressure
    # 20 points: unique buyers
    # 15 points: transaction velocity
    # 20 points: buy/sell imbalance
    #
    # This is a heuristic, not financial advice.
    # ---------------------------------------------------------


    volume_score = clamp(
        math.log10(
            volume + 1
        )
        * 5,
        0,
        25,
    )


    buy_pressure_score = (
        buy_ratio * 20
    )


    buyer_score = clamp(
        math.log10(
            len(unique_buyers) + 1
        )
        * 12,
        0,
        20,
    )


    velocity_score = clamp(
        math.log10(
            swap_count + 1
        )
        * 8,
        0,
        15,
    )


    imbalance = (
        abs(
            len(buys)
            - len(sells)
        )
        / max(
            swap_count,
            1,
        )
    )


    imbalance_score = (
        imbalance * 20
    )


    score = (
        volume_score
        + buy_pressure_score
        + buyer_score
        + velocity_score
        + imbalance_score
    )


    score = clamp(
        score,
        0,
        100,
    )


    return Metrics(

        token_address=token_address,

        volume_quote=volume,

        buys=len(buys),

        sells=len(sells),

        unique_buyers=len(
            unique_buyers
        ),

        unique_sellers=len(
            unique_sellers
        ),

        swap_count=swap_count,

        buy_ratio=buy_ratio,

        volume_velocity=volume_velocity,

        buyer_velocity=buyer_velocity,

        score=score,
    )
