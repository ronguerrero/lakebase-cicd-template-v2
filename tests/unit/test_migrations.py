"""Unit tests: migration hygiene, no database required."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "ci"))
from migrate import discover  # noqa: E402

MIG_DIR = os.path.join(ROOT, "db", "migrations")
NAME = re.compile(r"^V(\d{3})__.+\.sql$")


def test_names_and_strictly_increasing_versions():
    migs = discover(MIG_DIR)
    assert migs, "expected at least one migration"
    seen = []
    for ver, base, _ in migs:
        assert NAME.match(base), f"bad migration name: {base}"
        seen.append(int(ver[1:]))
    assert seen == sorted(seen), "versions must sort in filename order"
    assert len(set(seen)) == len(seen), "duplicate version numbers"


def test_v004_is_expand_and_contract_safe():
    with open(os.path.join(MIG_DIR, "V004__add_signup_source.sql")) as f:
        sql = f.read().lower()
    assert "add column if not exists signup_source" in sql, "V004 must add the column"
    assert "not null" not in sql.split("signup_source")[1][:40], \
        "the new column must be nullable (expand step)"
