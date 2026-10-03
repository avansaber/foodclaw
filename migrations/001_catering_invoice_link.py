"""FoodClaw migration 001: add the foodclaw_catering_invoice link table.

A completed catering event IS billed as a sales invoice owned by the selling
module, so foodclaw keeps only the link on its own side: which event (billed
once), which sales invoice, which customer, how much, and which company.
Fresh installs already carry the table because ``init_db.py`` declares it;
this migration provisions it on installs that predate the declaration.

THE DECLARATION IS NOT REPEATED HERE. The new table is copied from the
module's OWN ``init_db.py`` declaration via ``to_metadata`` into a fresh
MetaData, with the declaration it points at carried along so its reference
resolves — the same load-by-file shape as educlaw migration 004, which
copies the shared link declaration instead of re-typing it. A second
hand-typed copy is the exact drift class educlaw 004 exists to repair.

WHO CAN NEED IT. Only an install where foodclaw is present runs a foodclaw
migration. The guard is the catering event table: where it is absent the
migration prints and does nothing, so a foundation-only database is left
untouched.

NOTHING ELSE IS TOUCHED. The provisioner creates only what is missing, so a
re-run creates nothing, and no existing row is read or rewritten.
"""
import argparse
import importlib.util
import os
import sys

# A new table only: this run creates one table and changes no row.
MIGRATION_DATA_CLASS = "none"

# Deployed-lib bootstrap, guarded: production has nothing pre-imported so this
# resolves the installed lib, while a caller that already bound a tree (tests,
# the module runner inside a worktree) keeps its binding (ADR-0034 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:  # pragma: no cover - env-dependent
    sys.path.insert(0, os.path.join(
        os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib import seam  # noqa: E402
from erpclaw_lib.db import get_dialect  # noqa: E402
from erpclaw_lib.paths import db_default  # noqa: E402

DEFAULT_DB_PATH = db_default()

TABLE = "foodclaw_catering_invoice"


def _target(db_path):
    """The database to act on.

    On PostgreSQL the runner passes ``ERPCLAW_DB_URL`` when set, else the
    location it was given (from the module manager, the SQLite default file
    path); ``connect.py`` passes ``None`` or the action's ``--db-path``; a URL
    argument is used as given, anything else yields ``None``.
    """
    if get_dialect() == "postgresql":
        if isinstance(db_path, str) and (
                db_path.startswith("postgresql://")
                or db_path.startswith("postgres://")):
            return db_path
        return None
    return db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)


def _catering_invoice_metadata():
    """The link-table declaration, loaded — never re-typed here.

    Copies ``foodclaw_catering_invoice`` from the module's own ``init_db.py``
    into a fresh MetaData that ``seam.provision`` can act on. The catering
    event table it points at is carried along as a reference-only declaration,
    and stays reference-only in the copy, so the provisioner never creates
    another table; the link table is the only owned table in the fresh
    metadata and the only thing a run can create.
    """
    init_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "init_db.py")
    spec = importlib.util.spec_from_file_location("foodclaw_init_db_001",
                                                  init_path)
    init_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(init_mod)

    sa = seam._sqlalchemy()
    fresh = sa.MetaData()
    seam.reference_table("foodclaw_catering_event", fresh)
    init_mod.CATERING_INVOICE.to_metadata(fresh)
    return fresh


def run_migration(db_path=None, report_only=False):
    target = _target(db_path)

    if not seam.table_exists("foodclaw_catering_event", target):
        print(f"  foodclaw_catering_event absent on this install. Nothing to do.")
        return {"provisioned": False, "reason": "foodclaw not installed",
                "tables": 0, "indexes": 0, "report_only": report_only}

    already = seam.table_exists(TABLE, target)
    if report_only:
        if already:
            print(f"  {TABLE} already present. Nothing to do.")
        else:
            print(f"  report-only: the real run would provision {TABLE} "
                  f"from the init_db.py declaration. Nothing written.")
        return {"provisioned": False, "already_present": already,
                "tables": 0, "indexes": 0, "report_only": True}

    metadata = _catering_invoice_metadata()
    created = seam.provision(metadata, target)
    print(f"  provisioned {TABLE} from the init_db.py declaration: "
          f"{created['tables']} table(s), {created['indexes']} index(es).")
    return {"provisioned": bool(created["tables"]),
            "already_present": already,
            "tables": created["tables"], "indexes": created["indexes"],
            "report_only": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migration 001: add the foodclaw_catering_invoice link table")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-only", action="store_true",
                        help="State what the real run would do; write nothing.")
    args = parser.parse_args()
    run_migration(args.db_path, report_only=args.report_only)
    print("foodclaw migration 001 "
          + ("report complete (no writes)." if args.report_only else "complete."))
