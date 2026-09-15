import hashlib

from app.main import create_token, hash_password, verify_password, verify_token


def test_pbkdf2_password_roundtrip():
    stored = hash_password("correct horse battery staple", iterations=10_000)
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", stored) == (True, False)
    assert verify_password("wrong", stored) == (False, False)


def test_plain_sha256_is_rejected_in_fresh_v9():
    sha = hashlib.sha256(b"123456").hexdigest()
    assert verify_password("123456", sha) == (False, False)


def test_signed_token_roundtrip():
    token = create_token("farmer_long")
    payload = verify_token(token)
    assert payload["sub"] == "farmer_long"


def test_bootstrap_only_targets_fresh_seed_placeholders(monkeypatch):
    import app.main as identity

    calls = []

    class Cursor:
        def execute(self, query, params=()):
            calls.append((" ".join(query.split()), params))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Db:
        def cursor(self):
            return Cursor()

        def commit(self):
            calls.append(("COMMIT", ()))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(identity, "TECHNICIAN_BOOTSTRAP_PASSWORD", "technician-password-unique")
    monkeypatch.setattr(identity, "FARMER_BOOTSTRAP_PASSWORD", "farmer-password-unique")
    monkeypatch.setattr(identity, "hash_password", lambda value: f"hashed:{value}")
    monkeypatch.setattr(identity, "conn", lambda: Db())

    identity.bootstrap_seed_passwords()

    updates = [item for item in calls if item[0].startswith("UPDATE")]
    assert len(updates) == 2
    assert all("password_hash='bootstrap_required'" in query for query, _ in updates)
    assert updates[0][1][0] == "hashed:technician-password-unique"
    assert updates[1][1][0] == "hashed:farmer-password-unique"
