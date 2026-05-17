import sqlite3
import time

db = "nexusguard.db"


def connect():
    return sqlite3.connect(db)


def init_db():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_service TEXT,
            to_service TEXT,
            timestamp REAL,
            latency_ms REAL,
            simulated_cost REAL,
            cache_status TEXT DEFAULT 'miss'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS volume_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start REAL,
            user_profile INTEGER DEFAULT 0,
            recommend INTEGER DEFAULT 0,
            order_svc INTEGER DEFAULT 0,
            payment INTEGER DEFAULT 0,
            notification INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pre_baked_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service TEXT,
            confidence REAL,
            timestamp REAL
        )
    """)
    conn.commit()
    conn.close()


def insert_call(from_, to_, latency_ms, cache_status='miss'):
    conn = connect()
    cursor = conn.cursor()
    cost = latency_ms * 0.000002 if cache_status == 'miss' else 0.0
    cursor.execute(
        "INSERT INTO call_logs (from_service, to_service, timestamp, latency_ms, simulated_cost, cache_status) VALUES (?,?,?,?,?,?)",
        (from_, to_, time.time(), latency_ms, cost, cache_status)
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def snapshot_window(window_start: float):
    conn = connect()
    cursor = conn.cursor()
    window_end = window_start + 5.0
    counts = {}

    for s in ["user-profile", "recommend", "order", "payment", "notification"]:
        cursor.execute(
            "SELECT COUNT(*) FROM call_logs WHERE to_service=? AND timestamp>=? AND timestamp<?",
            (s, window_start, window_end)
        )
        counts[s] = cursor.fetchone()[0]

    cursor.execute("""
        INSERT INTO volume_windows (window_start, user_profile, recommend, order_svc, payment, notification)
        VALUES (?,?,?,?,?,?)
    """, (
        window_start,
        counts["user-profile"],
        counts["recommend"],
        counts["order"],
        counts["payment"],
        counts["notification"],
    ))
    conn.commit()
    conn.close()


def get_last_windows(n=12):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_profile, recommend, order_svc, payment, notification FROM volume_windows ORDER BY window_start DESC LIMIT ?",
        (n,)
    )
    rows = cursor.fetchall()
    conn.close()
    return list(reversed(rows))
