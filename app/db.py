import sqlite3
from pathlib import Path


class Database:

    def __init__(self, path: str):
        Path(path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.conn = sqlite3.connect(
            path,
            check_same_thread=False,
        )

        self.conn.row_factory = sqlite3.Row

        self._init()

    def _init(self):
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

                name TEXT,

                symbol TEXT,

                decimals INTEGER,

                initial_buy_amount TEXT,

                metadata_json TEXT,

                telegram_message_id INTEGER,

                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    detector,
                    token_address,
                    tx_hash,
                    log_index
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_launches_token
            ON launches(token_address);

            CREATE INDEX IF NOT EXISTS
                idx_launches_block
            ON launches(block_number);
            """
        )

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

        return row["value"] if row else None

    def set_state(
        self,
        key,
        value,
    ):
        self.conn.execute(
            """
            INSERT INTO state(key, value)
            VALUES (?, ?)

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
                name,
                symbol,
                decimals,
                initial_buy_amount,
                metadata_json
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                launch["detector"],
                launch["token_address"],
                launch.get("deployer"),
                launch.get("pool_address"),
                launch.get("pair_token"),
                launch["tx_hash"],
                launch["block_number"],
                launch["log_index"],
                launch.get("name"),
                launch.get("symbol"),
                launch.get("decimals"),
                launch.get("initial_buy_amount"),
                launch.get("metadata_json"),
            ),
        )

        self.conn.commit()

        return cursor.rowcount == 1

    def set_telegram_message_id(
        self,
        detector,
        token,
        tx_hash,
        log_index,
        message_id,
    ):
        self.conn.execute(
            """
            UPDATE launches
            SET telegram_message_id=?
            WHERE detector=?
              AND token_address=?
              AND tx_hash=?
              AND log_index=?
            """,
            (
                message_id,
                detector,
                token,
                tx_hash,
                log_index,
            ),
        )

        self.conn.commit()
