"""FoodClaw migration 001: the catering invoice link table on old installs.

A completed catering event is billed as a sales invoice owned by the selling
module; foodclaw keeps only the link (event, sales invoice, customer, amount,
company — one row per event, one link per sales invoice). Fresh installs
already carry ``foodclaw_catering_invoice`` because ``init_db.py`` declares
it; migration 001 provisions it on installs that predate the declaration,
changes no row, and does nothing on a database without foodclaw.

Every database read-back below goes through PyPika (``erpclaw_lib.query``)
over a connection from ``erpclaw_lib.db.get_connection``; catalog questions
go to ``erpclaw_lib.seam``. Money compares exact strings, never float. Each
test fails before the fix: the migration file does not exist, so tests 1-5
cannot load it, and test 6 fails with no such table.
"""
import importlib.util
import os
import sys
import uuid

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import food_helpers  # noqa: F401,E402 — binds erpclaw_lib to the tree under test

from erpclaw_lib import seam  # noqa: E402
from erpclaw_lib.db import get_connection  # noqa: E402
from erpclaw_lib.query import P, Q, Table, insert_row  # noqa: E402

MODULE_DIR = os.path.dirname(os.path.dirname(_TESTS_DIR))
SRC_DIR = os.path.dirname(MODULE_DIR)
INIT_DB_PATH = os.path.join(MODULE_DIR, "init_db.py")
MIGRATION_PATH = os.path.join(MODULE_DIR, "migrations",
                              "001_catering_invoice_link.py")
INIT_SCHEMA_PATH = os.path.join(SRC_DIR, "erpclaw", "scripts",
                                "erpclaw-setup", "init_schema.py")

LINK_TABLE = "foodclaw_catering_invoice"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_pre_change_db(path):
    """Foundation plus every foodclaw table except the link table."""
    _load("food_mig001_init_schema", INIT_SCHEMA_PATH).init_db(path)
    food_mod = _load("food_mig001_init_db", INIT_DB_PATH)
    sa = seam._sqlalchemy()
    fresh = sa.MetaData()
    for table in food_mod.METADATA.sorted_tables:
        if table.name == LINK_TABLE:
            continue
        table.to_metadata(fresh)
    seam.provision(fresh, path)
    assert not seam.table_exists(LINK_TABLE, path)
    return path


def seed_event(path, event_id, company_id):
    sql, _ = insert_row("foodclaw_catering_event", {
        "id": P(), "company_id": P(), "event_name": P(),
        "client_name": P(), "event_date": P(),
    })
    conn = get_connection(path)
    try:
        conn.execute(sql, [event_id, company_id, "Harvest Gala",
                           "Acme Corp", "2026-05-01"])
        conn.commit()
    finally:
        conn.close()


def read_event(path, event_id):
    t = Table("foodclaw_catering_event")
    q = Q.from_(t).select(t.star).where(t.id == P())
    conn = get_connection(path)
    try:
        row = conn.execute(q.get_sql(), [event_id]).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_link(path, link_id, event_id, sales_invoice_id, customer_id,
                amount, company_id):
    sql, _ = insert_row(LINK_TABLE, {
        "id": P(), "event_id": P(), "sales_invoice_id": P(),
        "customer_id": P(), "amount": P(), "company_id": P(),
    })
    conn = get_connection(path)
    try:
        conn.execute(sql, [link_id, event_id, sales_invoice_id,
                           customer_id, amount, company_id])
        conn.commit()
    finally:
        conn.close()


def link_count(path):
    t = Table(LINK_TABLE)
    q = Q.from_(t).select(t.star)
    conn = get_connection(path)
    try:
        return len(conn.execute(q.get_sql()).fetchall())
    finally:
        conn.close()


def test_migration_creates_the_table_on_a_pre_change_database(tmp_path):
    path = str(tmp_path / "pre.sqlite")
    make_pre_change_db(path)
    company_id = str(uuid.uuid4())
    seed_event(path, "evt-0001", company_id)
    before = read_event(path, "evt-0001")
    columns_before = seam.column_names("foodclaw_catering_event", path)

    mig = _load("food_mig001_migration", MIGRATION_PATH)
    result = mig.run_migration(path)

    assert result["provisioned"] is True
    assert result["tables"] == 1
    assert result["indexes"] >= 1
    assert seam.table_exists(LINK_TABLE, path)
    assert read_event(path, "evt-0001") == before
    assert seam.column_names("foodclaw_catering_event", path) == columns_before


def test_second_run_creates_nothing(tmp_path):
    path = str(tmp_path / "twice.sqlite")
    make_pre_change_db(path)
    seed_event(path, "evt-0001", str(uuid.uuid4()))

    mig = _load("food_mig001_migration", MIGRATION_PATH)
    first = mig.run_migration(path)
    assert first["tables"] == 1
    again = mig.run_migration(path)
    assert again["tables"] == 0
    assert again["indexes"] == 0
    assert again["already_present"] is True


def test_report_only_writes_nothing(tmp_path):
    path = str(tmp_path / "report.sqlite")
    make_pre_change_db(path)

    mig = _load("food_mig001_migration", MIGRATION_PATH)
    result = mig.run_migration(path, report_only=True)

    assert result["report_only"] is True
    assert result["already_present"] is False
    assert not seam.table_exists(LINK_TABLE, path)


def test_no_op_without_foodclaw(tmp_path):
    path = str(tmp_path / "foundation.sqlite")
    _load("food_mig001_init_schema", INIT_SCHEMA_PATH).init_db(path)

    mig = _load("food_mig001_migration", MIGRATION_PATH)
    result = mig.run_migration(path)

    assert result["provisioned"] is False
    assert result["tables"] == 0
    assert [t for t in seam.table_names(path)
            if t.startswith("foodclaw_")] == []


def test_fresh_install_equals_migrated(tmp_path):
    fresh_path = str(tmp_path / "fresh.sqlite")
    food_helpers.init_all_tables(fresh_path)
    migrated_path = str(tmp_path / "migrated.sqlite")
    make_pre_change_db(migrated_path)
    _load("food_mig001_migration", MIGRATION_PATH).run_migration(migrated_path)

    assert (seam.describe_table(LINK_TABLE, fresh_path)
            == seam.describe_table(LINK_TABLE, migrated_path))


def _check_link_uniqueness(path):
    company_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())
    seed_event(path, "evt-0101", company_id)
    seed_event(path, "evt-0102", company_id)
    insert_link(path, "link-0001", "evt-0101", "SI-0001",
                customer_id, "1200.00", company_id)

    with pytest.raises(Exception):
        insert_link(path, "link-0002", "evt-0101", "SI-0002",
                    customer_id, "1200.00", company_id)
    assert link_count(path) == 1

    with pytest.raises(Exception):
        insert_link(path, "link-0003", "evt-0102", "SI-0001",
                    customer_id, "800.00", company_id)
    assert link_count(path) == 1

    with pytest.raises(Exception):
        insert_link(path, "link-0004", "evt-missing", "SI-0009",
                    customer_id, "800.00", company_id)
    assert link_count(path) == 1


def test_link_uniqueness(tmp_path):
    fresh_path = str(tmp_path / "fresh.sqlite")
    food_helpers.init_all_tables(fresh_path)
    _check_link_uniqueness(fresh_path)

    migrated_path = str(tmp_path / "migrated.sqlite")
    make_pre_change_db(migrated_path)
    _load("food_mig001_migration", MIGRATION_PATH).run_migration(migrated_path)
    _check_link_uniqueness(migrated_path)
