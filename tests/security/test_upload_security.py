"""Security tests for Knowledge File Upload Security and Path Traversal Prevention (Phase 18)."""

import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_blocks_executable_file_types(client: AsyncClient, test_admin_user: dict):
    """Uploading executable scripts or binaries must be rejected with 400."""
    dangerous_files = [
        ("malicious.exe", b"MZ\x90\x00executable binary", "application/octet-stream"),
        ("exploit.sh", b"#!/bin/bash\nrm -rf /", "application/x-sh"),
        ("backdoor.py", b"import os; os.system('whoami')", "text/x-python"),
        ("payload.pdf.exe", b"fake binary", "application/octet-stream"),
    ]

    for filename, content, mime in dangerous_files:
        resp = await client.post(
            "/api/v1/knowledge/upload",
            files={"file": (filename, content, mime)},
            data={"title": f"Test {filename}"},
            headers=test_admin_user["headers"],
        )
        assert resp.status_code == 400, f"Dangerous file {filename} was not rejected"
        assert "disallowed" in resp.json()["detail"].lower() or "unsupported" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_path_traversal_filename_sanitization(client: AsyncClient, test_admin_user: dict):
    """Path traversal filename like ../../evil.txt must have path stripped safely."""
    uid = uuid.uuid4().hex[:8]
    content = f"Safe policy content for path traversal test {uid}".encode("utf-8")

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"../../traversal_{uid}.txt", content, "text/plain")},
        data={"title": f"Traversal Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 201
    # Document title and database record must exist without causing filesystem escape
    doc = resp.json()
    assert doc["title"] == f"Traversal Test {uid}"


@pytest.mark.asyncio
async def test_upload_rejects_fake_pdf_without_magic_bytes(client: AsyncClient, test_admin_user: dict):
    """A file named .pdf that does not begin with '%PDF-' must be rejected."""
    uid = uuid.uuid4().hex[:8]
    fake_pdf_content = b"This is just plain text disguised as a PDF document."

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"fake_{uid}.pdf", fake_pdf_content, "application/pdf")},
        data={"title": f"Fake PDF Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_rejects_text_with_null_bytes(client: AsyncClient, test_admin_user: dict):
    """Text document containing embedded null bytes (indicative of binary/shellcode) must be rejected."""
    uid = uuid.uuid4().hex[:8]
    binary_text = b"Normal header text\x00\x01\x02\x03\x04embedded binary payload"

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"nullbyte_{uid}.txt", binary_text, "text/plain")},
        data={"title": f"Null Byte Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 400
    assert "null bytes" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_blocks_dangerous_mimes(client: AsyncClient, test_admin_user: dict):
    """Files sent with dangerous MIME types such as text/html must be rejected."""
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("page.html", b"<html><body><script>alert(1)</script></body></html>", "text/html")},
        data={"title": "HTML Ingestion"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"].lower() or "disallowed" in resp.json()["detail"].lower()
