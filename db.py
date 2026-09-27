import os
import sqlite3
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import DictCursor

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cashback_app.db"
load_dotenv(BASE_DIR / ".env")


def get_database_url():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    return f"sqlite:///{DB_PATH}"


def is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgresql://", "postgres://"))


def get_connection():
    database_url = get_database_url()
    if is_postgres_url(database_url):
        try:
            return psycopg2.connect(database_url)
        except psycopg2.OperationalError as exc:
            raise RuntimeError(
                "PostgreSQL connection failed. Check your DATABASE_URL in .env and the PostgreSQL password/user. "
                f"Current URL is configured for user '{database_url.split('@')[0].split('/')[-1]}' on host '{database_url.split('@')[1].split('/')[0]}'."
            ) from exc

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _postgres_row_to_dict(row):
    if row is None:
        return None
    if hasattr(row, "_asdict"):
        return row._asdict()
    return dict(row)


def _create_postgres_schema(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            order_number TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            upi_id TEXT NOT NULL,
            cashback_amount NUMERIC(10, 2) NOT NULL DEFAULT 10,
            submission_date TIMESTAMP NOT NULL DEFAULT NOW(),
            status TEXT NOT NULL DEFAULT 'unpaid',
            paid_at TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS valid_orders (
            id SERIAL PRIMARY KEY,
            order_number TEXT NOT NULL UNIQUE,
            purchase_date TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cashback_amount NUMERIC(10, 2) NOT NULL DEFAULT 10,
            order_validation_enabled BOOLEAN NOT NULL DEFAULT TRUE
        )
        """
    )

    cur.execute(
        "INSERT INTO app_settings (id, cashback_amount, order_validation_enabled) "
        "VALUES (1, 10, TRUE) ON CONFLICT (id) DO NOTHING"
    )


def _ensure_sqlite_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            upi_id TEXT NOT NULL,
            cashback_amount REAL NOT NULL DEFAULT 10,
            submission_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unpaid',
            paid_at TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS valid_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL UNIQUE,
            purchase_date TEXT NOT NULL
        )
        """
    )

    submission_columns = {row[1] for row in conn.execute("PRAGMA table_info(submissions)")}
    if "cashback_amount" not in submission_columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN cashback_amount REAL NOT NULL DEFAULT 10"
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cashback_amount REAL NOT NULL DEFAULT 10,
            order_validation_enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")


def sync_postgres_sequences(conn=None):
    connection = conn or get_connection()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT setval(pg_get_serial_sequence('submissions', 'id'), COALESCE((SELECT MAX(id) FROM submissions), 0), true)"
            )
            cur.execute(
                "SELECT setval(pg_get_serial_sequence('valid_orders', 'id'), COALESCE((SELECT MAX(id) FROM valid_orders), 0), true)"
            )
        if conn is None:
            connection.commit()
    finally:
        if conn is None:
            connection.close()


def init_db():
    database_url = get_database_url()
    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                _create_postgres_schema(cur)
            conn.commit()
        with get_connection() as conn:
            sync_postgres_sequences(conn)
            conn.commit()
        return

    with get_connection() as conn:
        _ensure_sqlite_schema(conn)
        conn.commit()


def seed_demo_orders():
    database_url = get_database_url()
    demo_orders = [
        ("ORD1001", "2026-09-20"),
        ("ORD1002", "2026-09-21"),
        ("ORD1003", "2026-09-22"),
        ("ORD1004", "2026-09-23"),
        ("ORD1005", "2026-09-24"),
    ]

    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM valid_orders")
                if cur.fetchone()[0] == 0:
                    cur.executemany(
                        "INSERT INTO valid_orders (order_number, purchase_date) VALUES (%s, %s)",
                        demo_orders,
                    )
            conn.commit()
        return

    with get_connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM valid_orders").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO valid_orders (order_number, purchase_date) VALUES (?, ?)",
                demo_orders,
            )
            conn.commit()


def validate_order(order_number: str) -> bool:
    if not order_number:
        return False
    normalized_order = order_number.strip()
    database_url = get_database_url()

    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM valid_orders WHERE order_number = %s",
                    (normalized_order,),
                )
                row = cur.fetchone()
        return row is not None

    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM valid_orders WHERE order_number = ?",
            (normalized_order,),
        ).fetchone()
    return row is not None


def get_app_settings():
    database_url = get_database_url()
    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT cashback_amount, order_validation_enabled FROM app_settings WHERE id = 1"
                )
                row = cur.fetchone()
        if row is None:
            return {"cashback_amount": 10.0, "order_validation_enabled": True}
        return {
            "cashback_amount": float(row[0]),
            "order_validation_enabled": bool(row[1]),
        }

    with get_connection() as conn:
        row = conn.execute(
            "SELECT cashback_amount, order_validation_enabled FROM app_settings WHERE id = 1"
        ).fetchone()
    return {
        "cashback_amount": float(row["cashback_amount"]),
        "order_validation_enabled": bool(row["order_validation_enabled"]),
    }


def update_app_settings(cashback_amount: float, order_validation_enabled: bool):
    if cashback_amount < 0:
        raise ValueError("Cashback amount cannot be negative.")
    database_url = get_database_url()

    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE app_settings SET cashback_amount = %s, order_validation_enabled = %s WHERE id = 1",
                    (cashback_amount, bool(order_validation_enabled)),
                )
            conn.commit()
        return

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE app_settings
            SET cashback_amount = ?, order_validation_enabled = ?
            WHERE id = 1
            """,
            (cashback_amount, int(order_validation_enabled)),
        )
        conn.commit()


def save_submission(order_number: str, phone_number: str, upi_id: str):
    order_number = order_number.strip()
    phone_number = phone_number.strip()
    upi_id = upi_id.strip()
    database_url = get_database_url()

    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cashback_amount FROM app_settings WHERE id = 1"
                )
                settings = cur.fetchone()
                cashback_amount = float(settings[0]) if settings else 10.0
                cur.execute(
                    "SELECT 1 FROM submissions WHERE phone_number = %s OR upi_id = %s LIMIT 1",
                    (phone_number, upi_id),
                )
                duplicate = cur.fetchone()
                if duplicate:
                    return False, (
                        "You have already scanned this QR code.\n\n"
                        "आप यह QR कोड पहले ही स्कैन कर चुके हैं।"
                    )
                cur.execute(
                    """
                    INSERT INTO submissions (
                        order_number, phone_number, upi_id, cashback_amount, submission_date, status
                    )
                    VALUES (%s, %s, %s, %s, NOW(), 'unpaid')
                    """,
                    (order_number, phone_number, upi_id, cashback_amount),
                )
            conn.commit()
        return True, (
            "**English**\n\n"
            f"After you rate and review the product in the Meesho app, ₹{cashback_amount:g} cashback will be "
            "credited to your UPI ID within 12 hours. The payment will appear under the name Dolphin.\n\n"
            "**हिंदी**\n\n"
            f"Meesho ऐप में उत्पाद को रेटिंग और समीक्षा देने के बाद, ₹{cashback_amount:g} कैशबैक 12 घंटे के भीतर "
            "आपके UPI ID में जमा कर दिया जाएगा। भुगतान Dolphin नाम से दिखाई देगा।"
        )

    with get_connection() as conn:
        settings = conn.execute(
            "SELECT cashback_amount FROM app_settings WHERE id = 1"
        ).fetchone()
        cashback_amount = float(settings["cashback_amount"]) if settings else 10.0
        duplicate = conn.execute(
            "SELECT 1 FROM submissions WHERE phone_number = ? OR upi_id = ? LIMIT 1",
            (phone_number, upi_id),
        ).fetchone()
        if duplicate:
            return False, (
                "You have already scanned this QR code.\n\n"
                "आप यह QR कोड पहले ही स्कैन कर चुके हैं।"
            )

        conn.execute(
            """
            INSERT INTO submissions (
                order_number, phone_number, upi_id, cashback_amount, submission_date, status
            )
            VALUES (?, ?, ?, ?, datetime('now'), 'unpaid')
            """,
            (order_number, phone_number, upi_id, cashback_amount),
        )
        conn.commit()
        return True, (
            "**English**\n\n"
            f"After you rate and review the product in the Meesho app, ₹{cashback_amount:g} cashback will be "
            "credited to your UPI ID within 12 hours. The payment will appear under the name Dolphin.\n\n"
            "**हिंदी**\n\n"
            f"Meesho ऐप में उत्पाद को रेटिंग और समीक्षा देने के बाद, ₹{cashback_amount:g} कैशबैक 12 घंटे के भीतर "
            "आपके UPI ID में जमा कर दिया जाएगा। भुगतान Dolphin नाम से दिखाई देगा।"
        )


def list_submissions(status_filter: str = "all"):
    database_url = get_database_url()
    query = "SELECT * FROM submissions"
    params = []
    if status_filter != "all":
        query += " WHERE status = %s" if is_postgres_url(database_url) else " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY id DESC"

    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [_postgres_row_to_dict(row) for row in rows]

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def mark_paid(submission_id: int):
    database_url = get_database_url()
    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE submissions SET status = 'paid', paid_at = NOW() WHERE id = %s AND status = 'unpaid'",
                    (submission_id,),
                )
            conn.commit()
        return cur.rowcount > 0

    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE submissions SET status = 'paid', paid_at = datetime('now') "
            "WHERE id = ? AND status = 'unpaid'",
            (submission_id,),
        )
        conn.commit()
    return cursor.rowcount > 0


def get_submission_count():
    database_url = get_database_url()
    if is_postgres_url(database_url):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM submissions WHERE status = 'unpaid'")
                unpaid = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM submissions WHERE status = 'paid'")
                paid = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM submissions")
                total = cur.fetchone()[0]
                cur.execute(
                    "SELECT COALESCE(SUM(cashback_amount), 0) FROM submissions WHERE status = 'unpaid'"
                )
                unpaid_amount = cur.fetchone()[0]
                cur.execute(
                    "SELECT COALESCE(SUM(cashback_amount), 0) FROM submissions WHERE status = 'paid'"
                )
                paid_amount = cur.fetchone()[0]
        return {
            "total": total,
            "unpaid": unpaid,
            "paid": paid,
            "unpaid_amount": float(unpaid_amount),
            "paid_amount": float(paid_amount),
        }

    with get_connection() as conn:
        unpaid = conn.execute("SELECT COUNT(*) FROM submissions WHERE status = 'unpaid'").fetchone()[0]
        paid = conn.execute("SELECT COUNT(*) FROM submissions WHERE status = 'paid'").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        unpaid_amount = conn.execute(
            "SELECT COALESCE(SUM(cashback_amount), 0) FROM submissions WHERE status = 'unpaid'"
        ).fetchone()[0]
        paid_amount = conn.execute(
            "SELECT COALESCE(SUM(cashback_amount), 0) FROM submissions WHERE status = 'paid'"
        ).fetchone()[0]
    return {
        "total": total,
        "unpaid": unpaid,
        "paid": paid,
        "unpaid_amount": float(unpaid_amount),
        "paid_amount": float(paid_amount),
    }


def migrate_sqlite_to_postgres(sqlite_db_path: str | Path | None = None, postgres_url: str | None = None):
    target_url = (postgres_url or os.environ.get("DATABASE_URL", "")).strip()
    if not target_url or not is_postgres_url(target_url):
        raise ValueError("A PostgreSQL DATABASE_URL must be configured before migrating data.")

    source_path = Path(sqlite_db_path) if sqlite_db_path else DB_PATH
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite source database not found: {source_path}")

    with sqlite3.connect(source_path) as source_conn:
        source_conn.row_factory = sqlite3.Row
        submissions = [dict(row) for row in source_conn.execute("SELECT * FROM submissions ORDER BY id").fetchall()]
        valid_orders = [dict(row) for row in source_conn.execute("SELECT * FROM valid_orders ORDER BY id").fetchall()]
        app_settings_rows = source_conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchall()
        app_settings = dict(app_settings_rows[0]) if app_settings_rows else {"cashback_amount": 10.0, "order_validation_enabled": 1}

    with psycopg2.connect(target_url) as conn:
        with conn.cursor() as cur:
            _create_postgres_schema(cur)
            if submissions:
                cur.executemany(
                    """
                    INSERT INTO submissions (
                        id, order_number, phone_number, upi_id, cashback_amount, submission_date, status, paid_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        (
                            row.get("id"),
                            row.get("order_number"),
                            row.get("phone_number"),
                            row.get("upi_id"),
                            row.get("cashback_amount", 10.0),
                            row.get("submission_date"),
                            row.get("status", "unpaid"),
                            row.get("paid_at"),
                        )
                        for row in submissions
                    ],
                )

            if valid_orders:
                cur.executemany(
                    """
                    INSERT INTO valid_orders (id, order_number, purchase_date)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        (row.get("id"), row.get("order_number"), row.get("purchase_date"))
                        for row in valid_orders
                    ],
                )

            cur.execute(
                """
                INSERT INTO app_settings (id, cashback_amount, order_validation_enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    cashback_amount = EXCLUDED.cashback_amount,
                    order_validation_enabled = EXCLUDED.order_validation_enabled
                """,
                (
                    1,
                    float(app_settings.get("cashback_amount", 10.0)),
                    bool(app_settings.get("order_validation_enabled", 1)),
                ),
            )
        conn.commit()

    with psycopg2.connect(target_url) as conn:
        sync_postgres_sequences(conn)
        conn.commit()

    return {
        "submissions": len(submissions),
        "valid_orders": len(valid_orders),
        "app_settings": {"cashback_amount": float(app_settings.get("cashback_amount", 10.0)), "order_validation_enabled": bool(app_settings.get("order_validation_enabled", 1))},
    }
