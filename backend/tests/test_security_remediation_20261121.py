"""Regression cases for the November remediation. Not executed during implementation."""
import asyncio
import gzip
import json
from dataclasses import replace

import pytest
from fastapi import HTTPException

from app.core.body_limits import BodySizeLimitMiddleware
from app.services import backup


def _request(chunks, headers=(), path="/api/v1/example"):
    async def run():
        messages = iter([{"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
                         for i, chunk in enumerate(chunks)])
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        async def app(scope, receive, send):
            try:
                while (await receive()).get("more_body"):
                    pass
                status = 200
            except HTTPException:
                status = 400  # A parser must not mask the size violation.
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        guard = BodySizeLimitMiddleware(app, json_bytes=4, multipart_bytes=8, backup_bytes=12)
        await guard({"type": "http", "method": "POST", "path": path, "headers": headers}, receive, send)
        return sent[0]["status"]
    return asyncio.run(run())


def test_actual_bytes_with_missing_or_understated_length():
    assert _request([b"12", b"345"]) == 413
    assert _request([b"12345"], [(b"content-length", b"1")]) == 413
    assert _request([b"12", b"34"]) == 200


@pytest.mark.parametrize("value", [b"-1", b"wrong", b"+2", b" 2"])
def test_invalid_length(value):
    assert _request([b""], [(b"content-length", value)]) == 400


def test_multipart_has_bounded_distinct_allowances():
    headers = [(b"content-type", b"multipart/form-data; boundary=abc")]
    assert _request([b"123456789"], headers) == 413
    assert _request([b"123456789"], headers, "/api/v1/backup/jobs/import") == 200
    assert _request([b"1" * 13], headers, "/api/v1/backup/jobs/import") == 413


def _records():
    return [
        {"type": "manifest", "kind": backup.ARCHIVE_KIND, "format_version": 1,
         "scope": "workspace", "organization": {"id": "tenant"}, "schema_revision": "revision",
         "tables": [{"name": "widgets", "columns": ["id"], "primary_key": ["id"]}]},
        {"type": "table", "table": "widgets", "rows": [{"id": "one"}]},
        {"type": "trailer", "tables": {"widgets": 1}, "rows": 1},
    ]


def _write(path, records):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    return path


def test_valid_archive(tmp_path):
    assert backup.scan_archive(_write(tmp_path / "valid.gz", _records()))["total_rows"] == 1


@pytest.mark.parametrize("variant", ["nonobject", "unknown_column", "trailing", "counts", "duplicate_table", "row_shape", "version"])
def test_malformed_archives(tmp_path, variant):
    records = _records()
    if variant == "nonobject":
        records[1] = []
    elif variant == "unknown_column":
        records[1]["rows"][0]["secret"] = "value"
    elif variant == "trailing":
        records.append(records[1])
    elif variant == "counts":
        records[2]["tables"] = {}
    elif variant == "duplicate_table":
        records[0]["tables"] *= 2
    elif variant == "row_shape":
        records[1]["rows"] = [None]
    else:
        records[0]["format_version"] = True
    with pytest.raises(backup.BackupError):
        backup.scan_archive(_write(tmp_path / "invalid.gz", records))


def test_archive_budgets(tmp_path, monkeypatch):
    path = _write(tmp_path / "limits.gz", _records())
    for change in ({"record_bytes": 8}, {"manifest_bytes": 8}, {"expanded_bytes": 8},
                   {"expansion_ratio": 1}, {"total_rows": 0}, {"rows_per_table": 0}, {"records": 1}):
        with monkeypatch.context() as context:
            context.setattr(backup, "ARCHIVE_POLICY", replace(backup.ARCHIVE_POLICY, **change))
            with pytest.raises(backup.BackupError):
                backup.scan_archive(path)


def test_mounted_routes_have_explicit_authentication_policy():
    from app.core.route_inventory import inventory
    from app.main import app
    assert inventory(app)["violations"] == []
