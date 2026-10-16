from pathlib import Path
from mysql_editor.storage import ConnectionProfile, LocalRepository, MasterPasswordStore, new_profile_id

def test_master_password_verifier_is_not_plaintext(tmp_path: Path):
    repo = LocalRepository(tmp_path / "settings.sqlite3")
    store = MasterPasswordStore(repo)
    store.create("long enough phrase", "long enough phrase")
    digest = repo.get_setting("master_password_hash")
    assert digest and digest != "long enough phrase"
    assert "$argon2id$" in digest
    assert store.verify("long enough phrase")
    assert not store.verify("wrong phrase")
    repo.close()

def test_master_password_validation_and_confirmation(tmp_path: Path):
    repo = LocalRepository(tmp_path / "settings.sqlite3")
    store = MasterPasswordStore(repo)
    try:
        store.create("short", "short")
    except ValueError:
        pass
    else:
        raise AssertionError("short password was accepted")
    try:
        store.create("a long enough password", "different confirmation")
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched confirmation was accepted")
    repo.close()

def test_profiles_never_have_password_column(tmp_path: Path):
    repo = LocalRepository(tmp_path / "settings.sqlite3")
    profile = ConnectionProfile(id=new_profile_id(), name="Local", host="localhost")
    repo.save_profile(profile)
    columns = [row[1] for row in repo._db.execute("PRAGMA table_info(profiles)")]
    assert "password" not in columns
    assert len(repo.profiles()) == 1
    repo.close()

def test_history_is_opt_in_and_cleared_when_disabled(tmp_path: Path):
    repo = LocalRepository(tmp_path / "settings.sqlite3")
    repo.add_history("Local", "SELECT 1", 1, "success")
    assert repo.history() == []
    repo.set_history_enabled(True)
    repo.add_history("Local", "SELECT 2", 2, "success")
    assert len(repo.history()) == 1
    repo.set_history_enabled(False)
    assert repo.history() == []
    repo.close()
