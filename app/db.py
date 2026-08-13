import sqlite3

from pathlib import Path


class Database:

    def __init__(
        self,
        path,
    ):

        Path(path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.conn = sqlite3.connect(
            path,
            check_same_thread=False,
        )

        self.conn.row_factory = (
            sqlite3.Row
        )

        self._create_tables()


    def _create_tables(self):

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state (

                key TEXT PRIMARY KEY,

                value TEXT NOT NULL

            );


            CREATE TABLE IF NOT EXISTS launches (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                detector TEXT NOT NULL,

                token_address TEXT NOT NULL,

                deployer TEXT,

                pool_address TEXT,

                pair_token TEXT,

                tx_hash TEXT NOT NULL,

                block_number INTEGER NOT NULL,

                log_index INTEGER NOT NULL,

                launch_timestamp INTEGER,

                name TEXT,

                symbol TEXT,

                decimals INTEGER,

                supply TEXT,

                initial_buy_amount TEXT,

                is_token0 INTEGER,

                pool_fee INTEGER,

                graduated INTEGER DEFAULT 0,

                graduation_block INTEGER,

                telegram_message_id INTEGER,

                trend_message_id INTEGER,

                last_trend_score REAL DEFAULT 0,

                last_trend_alert INTEGER DEFAULT 0,

                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    detector,
                    token_address
                )

            );


            CREATE TABLE IF NOT EXISTS trades (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                token_address TEXT NOT NULL,

                pool_address TEXT NOT NULL,

                tx_hash TEXT NOT NULL,

                block_number INTEGER NOT NULL,

                log_index INTEGER NOT NULL,

                trader TEXT,

                side TEXT NOT NULL,

                token_amount REAL NOT NULL,

                quote_amount REAL NOT NULL,

                timestamp INTEGER NOT NULL,

                UNIQUE(
                    tx_hash,
                    log_index
                )

            );


            CREATE INDEX IF NOT EXISTS
                idx_trades_token_time

            ON trades(
                token_address,
                timestamp
            );


            CREATE INDEX IF NOT EXISTS
                idx_trades_trader

            ON trades(
                token_address,
                trader
            );


            CREATE INDEX IF NOT EXISTS
                idx_launch_pool

            ON launches(
                pool_address
            );
            """
        )

        self.conn.commit()


    def get_state(
        self,
        key,
    ):

        row = self.conn.execute(
            """
            SELECT value
            FROM state
            WHERE key=?
            """,
            (key,),
        ).fetchone()

        if row is None:
            return None

        return row["value"]


    def set_state(
        self,
        key,
        value,
    ):

        self.conn.execute(
            """
            INSERT INTO state(
                key,
                value
            )
            VALUES(
                ?,
                ?
            )

            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value
            """,
            (
                key,
                value,
            ),
        )

        self.conn.commit()


    def insert_launch(
        self,
        launch,
    ):

        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO launches(

                detector,

                token_address,

                deployer,

                pool_address,

                pair_token,

                tx_hash,

                block_number,

                log_index,

                launch_timestamp,

                name,

                symbol,

                decimals,

                supply,

                initial_buy_amount,

                is_token0,

                pool_fee

            )
            VALUES(
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                launch.detector,
                launch.token_address,
                launch.deployer,
                launch.pool_address,
                launch.pair_token,
                launch.tx_hash,
                launch.block_number,
                launch.log_index,
                launch.launch_timestamp,
                launch.name,
                launch.symbol,
                launch.decimals,
                str(launch.supply)
                    if launch.supply
                    else None,
                str(launch.initial_buy_amount)
                    if launch.initial_buy_amount
                    else None,
                int(launch.is_token0)
                    if launch.is_token0 is not None
                    else None,
                launch.pool_fee,
            ),
        )

        self.conn.commit()

        return cursor.rowcount == 1


    def update_launch_message(
        self,
        token,
        message_id,
    ):

        self.conn.execute(
            """
            UPDATE launches

            SET telegram_message_id=?

            WHERE token_address=?
            """,
            (
                message_id,
                token,
            ),
        )

        self.conn.commit()


    def insert_trade(
        self,
        trade,
    ):

        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO trades(

                token_address,

                pool_address,

                tx_hash,

                block_number,

                log_index,

                trader,

                side,

                token_amount,

                quote_amount,

                timestamp

            )
            VALUES(
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                trade.token_address,
                trade.pool_address,
                trade.tx_hash,
                trade.block_number,
                trade.log_index,
                trade.trader,
                trade.side,
                trade.token_amount,
                trade.quote_amount,
                trade.timestamp,
            ),
        )

        self.conn.commit()

        return cursor.rowcount == 1


    def active_tokens(self):

        return self.conn.execute(
            """
            SELECT *
            FROM launches
            WHERE graduated = 0
               OR last_trend_score >= 1
            """
        ).fetchall()


    def trades_since(
        self,
        token,
        timestamp,
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM trades

            WHERE token_address=?
              AND timestamp>=?

            ORDER BY timestamp ASC
            """,
            (
                token,
                timestamp,
            ),
        ).fetchall()


    def set_trend(
        self,
        token,
        score,
        timestamp,
    ):

        self.conn.execute(
            """
            UPDATE launches

            SET
                last_trend_score=?,
                last_trend_alert=?

            WHERE token_address=?
            """,
            (
                score,
                timestamp,
                token,
            ),
        )

        self.conn.commit()


    def mark_graduated(
        self,
        token,
        block_number,
    ):

        self.conn.execute(
            """
            UPDATE launches

            SET
                graduated=1,
                graduation_block=?

            WHERE token_address=?
            """,
            (
                block_number,
                token,
            ),
        )

        self.conn.commit()


    def get_launch(
        self,
        token,
    ):

        return self.conn.execute(
            """
            SELECT *
            FROM launches
            WHERE token_address=?
            """,
            (
                token,
            ),
        ).fetchone()
