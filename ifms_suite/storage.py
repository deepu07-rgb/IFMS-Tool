"""Suite records coexist with the retained analyzer tables in one SQLite file."""

import json, sqlite3
from contextlib import contextmanager
from flask import current_app


@contextmanager
def database():
    db = sqlite3.connect(current_app.config["DATABASE"], timeout=30)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with database() as db:
        db.executescript(
            """
        CREATE TABLE IF NOT EXISTS suite_payment_allocations(payment_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_claim_settlements(claim_id INTEGER PRIMARY KEY,payment_id INTEGER UNIQUE NOT NULL,reference TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_rate_audit(id INTEGER PRIMARY KEY,rate_id INTEGER,previous_payload TEXT,new_payload TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_profile_audit(id INTEGER PRIMARY KEY,employee_code TEXT NOT NULL,source TEXT NOT NULL,previous_payload TEXT,new_payload TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_group_reviews(import_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suite_rules(name TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suite_pay_history(id INTEGER PRIMARY KEY,employee_code TEXT NOT NULL,effective_from TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(employee_code,effective_from));
        CREATE TABLE IF NOT EXISTS suite_employees(employee_code TEXT PRIMARY KEY,name TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suite_payments(id INTEGER PRIMARY KEY,import_id INTEGER NOT NULL,employee_code TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(import_id,employee_code,payload));
        CREATE TABLE IF NOT EXISTS suite_group_imports(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_rates(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suite_claims(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,calculation TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',review TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_imports(id INTEGER PRIMARY KEY,sha256 TEXT UNIQUE NOT NULL,filename TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'needs_review',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """
        )
