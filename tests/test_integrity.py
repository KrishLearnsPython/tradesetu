import hashlib
import os
import sys
from pathlib import Path

import pytest

# Allow the app's existing `from db_config import ...` import.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIRECTORY = PROJECT_ROOT / "tradesetu"

sys.path.insert(0, str(APP_DIRECTORY))

# Use a temporary test-only secret before importing the Flask app.
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-for-production")

from tradesetu.app import (
    generate_shipment_hash,
    hash_password,
    verify_password,
)


def test_new_password_hash_verifies_correct_password():
    password = "TestPassword123!"
    password_hash, salt = hash_password(password)

    assert password_hash.startswith("scrypt:")
    assert verify_password(password, password_hash, salt)


def test_new_password_hash_rejects_wrong_password():
    password_hash, salt = hash_password("TestPassword123!")

    assert not verify_password("WrongPassword!", password_hash, salt)


def test_legacy_sha256_password_hash_still_verifies():
    password = "LegacyPassword123!"
    salt = "legacy-test-salt"
    legacy_hash = hashlib.sha256((password + salt).encode()).hexdigest()

    assert verify_password(password, legacy_hash, salt)


def test_legacy_hash_rejects_wrong_password():
    password = "LegacyPassword123!"
    salt = "legacy-test-salt"
    legacy_hash = hashlib.sha256((password + salt).encode()).hexdigest()

    assert not verify_password("WrongPassword!", legacy_hash, salt)


def test_shipment_hash_is_deterministic():
    args = ("SHP123456", "PROD-001", "10", "50", "7", "0")

    first_hash = generate_shipment_hash(*args)
    second_hash = generate_shipment_hash(*args)

    assert first_hash == second_hash
    assert len(first_hash) == 64


@pytest.mark.parametrize(
    "field_index,replacement",
    [
        (0, "SHP999999"),
        (1, "PROD-999"),
        (2, "11"),
        (3, "51"),
        (4, "8"),
        (5, "previous-hash-changed"),
    ],
)
def test_changing_shipment_hash_input_changes_hash(field_index, replacement):
    args = ["SHP123456", "PROD-001", "10", "50", "7", "0"]
    original_hash = generate_shipment_hash(*args)

    args[field_index] = replacement
    changed_hash = generate_shipment_hash(*args)

    assert changed_hash != original_hash
