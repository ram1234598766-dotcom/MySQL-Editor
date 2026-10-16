from mysql_editor.database import DatabaseWorker, safe_db_error


def test_automatic_tls_does_not_require_an_explicit_certificate_file():
    options = DatabaseWorker._connect_options({
        "host": "127.0.0.1",
        "username": "test",
        "password": "not-stored",
        "tls_mode": "Automatic TLS",
        "ca_file": "",
    })
    assert options["ssl_disabled"] is False
    assert options["ssl_verify_cert"] is False
    assert "ssl_ca" not in options


def test_strict_tls_enables_certificate_and_hostname_verification():
    options = DatabaseWorker._connect_options({
        "host": "db.example.invalid",
        "username": "test",
        "password": "not-stored",
        "tls_mode": "Verify server identity",
        "ca_file": "/not/used/in/this/pure-unit-test.pem",
    })
    assert options["ssl_verify_cert"] is True
    assert options["ssl_verify_identity"] is True
    assert options["ssl_ca"] == "/not/used/in/this/pure-unit-test.pem"


def test_disabled_tls_is_an_explicit_choice():
    options = DatabaseWorker._connect_options({
        "host": "localhost",
        "username": "test",
        "password": "",
        "tls_mode": "Disabled",
    })
    assert options["ssl_disabled"] is True


def test_database_errors_are_bounded_and_not_raw_multiline_traces():
    value = safe_db_error(RuntimeError("password=secret\n" + "x" * 1800))
    assert "secret" not in value
    assert len(value) <= 1601
