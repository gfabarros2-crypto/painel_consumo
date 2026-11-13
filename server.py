"""Servidor local do painel. Em produção, use HTTPS e armazenamento persistente."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from domain import RESOURCES, analyze, normalize_record, public_record
from extractor import parse_pdf

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = Path(os.environ.get("EMPETUR_DATA_DIR", ROOT / "data")).resolve()
RECORDS_FILE = DATA / "records.json"
IMPORTS = DATA / "imports"
REVISIONS = DATA / "revisions"
MAX_UPLOAD = 4 * 1024 * 1024
WRITE_LOCK = threading.Lock()
BLOB_PREFIX = "empetur-consumo"


def blob_client():
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        return None
    from vercel.blob import sync as blob
    return blob


def blob_bytes(client, pathname: str) -> bytes | None:
    try:
        return client.get_blob(pathname, access="private").body
    except FileNotFoundError:
        return None


def save_import(import_id: str, document: bytes) -> None:
    client = blob_client()
    if client:
        client.put_blob(f"{BLOB_PREFIX}/imports/{import_id}.pdf", document, access="private", content_type="application/pdf")
    else:
        IMPORTS.mkdir(parents=True, exist_ok=True)
        (IMPORTS / f"{import_id}.pdf").write_bytes(document)


def import_exists(import_id: str) -> bool:
    client = blob_client()
    if client:
        return blob_bytes(client, f"{BLOB_PREFIX}/imports/{import_id}.pdf") is not None
    return (IMPORTS / f"{import_id}.pdf").exists()


def read_data() -> dict:
    client = blob_client()
    if client:
        content = blob_bytes(client, f"{BLOB_PREFIX}/records.json")
        if content is not None:
            return json.loads(content)
    if not RECORDS_FILE.exists():
        return {"schema_version": 1, "last_updated": None, "records": []}
    with RECORDS_FILE.open(encoding="utf-8") as stream:
        return json.load(stream)


def save_data(data: dict) -> None:
    client = blob_client()
    if client:
        previous = blob_bytes(client, f"{BLOB_PREFIX}/records.json")
        if previous is not None:
            snapshot = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
            client.put_blob(f"{BLOB_PREFIX}/revisions/{snapshot}", previous, access="private", content_type="application/json")
        content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        client.put_blob(f"{BLOB_PREFIX}/records.json", content, access="private", content_type="application/json", allow_overwrite=True)
        return
    if os.environ.get("VERCEL"):
        raise RuntimeError("Configure um Vercel Blob privado antes de publicar dados.")
    DATA.mkdir(parents=True, exist_ok=True)
    if RECORDS_FILE.exists():
        REVISIONS.mkdir(parents=True, exist_ok=True)
        snapshot = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
        (REVISIONS / snapshot).write_bytes(RECORDS_FILE.read_bytes())
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=DATA, prefix="records-", suffix=".tmp", delete=False
    ) as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temp_name = stream.name
    os.replace(temp_name, RECORDS_FILE)


def parse_multipart(content_type: str, body: bytes) -> dict:
    if "multipart/form-data" not in content_type:
        raise ValueError("Envie o PDF como formulário multipart.")
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    result = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            result[name] = part.get_payload(decode=True)
    return result


def admin_name_from_header(header: str, password: str) -> str | None:
    """Valida a senha compartilhada e extrai o nome declarado pelo editor."""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    name, separator, supplied_password = decoded.partition(":")
    name = name.strip()
    if not separator or not name or len(name) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        return None
    return name if hmac.compare_digest(supplied_password, password) else None


def apply_publication(data: dict, rows: list[dict], actor: str, import_id: str, timestamp: str) -> tuple[int, int]:
    """Atualiza competências e guarda quem publicou, inclusive em substituições."""
    existing = {(r["resource"], r["period"]): r for r in data.get("records", [])}
    changes = []
    for row in rows:
        key = (row["resource"], row["period"])
        changes.append({"resource": row["resource"], "period": row["period"], "action": "replaced" if key in existing else "created"})
        updated = {**row, "updated_by": actor, "updated_at": timestamp}
        if import_id:
            updated["source_file_id"] = import_id
        existing[key] = updated
    data["records"] = sorted(existing.values(), key=lambda r: (r["resource"], r["period"]))
    data["last_updated"] = timestamp
    data.setdefault("audit_log", []).append({
        "id": uuid.uuid4().hex,
        "at": timestamp,
        "user": actor,
        "changes": changes,
        "source_file_id": import_id or None,
    })
    return len(rows), sum(change["action"] == "replaced" for change in changes)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def send_json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if urlparse(self.path).path in ("/api/records", "/api/period", "/api/overview"):
            origin = self.headers.get("Origin")
            if origin in ("https://www.empetur.pe.gov.br", "https://empetur.pe.gov.br"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(encoded)

    def auth_ok(self) -> bool:
        password = os.environ.get("EMPETUR_ADMIN_PASSWORD")
        if not password:
            self.send_json({"error": "Área de abastecimento desativada: configure a senha."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return False
        self.admin_user = admin_name_from_header(self.headers.get("Authorization", ""), password)
        if not self.admin_user:
            self.send_json({"error": "Nome ou senha inválidos."}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/admin", "/admin.html"):
            self.path = "/admin.html"
            return super().do_GET()
        if path == "/api/records":
            data = read_data()
            records = data.get("records", [])
            sources = {}
            for resource, original in {
                "water": "https://www.empetur.pe.gov.br/images/consumo-mensal-de-agua-e-energia/2022/planilha_mensal_agua_empetur_-_AGUA.pdf",
                "energy": "https://www.empetur.pe.gov.br/images/consumo-mensal-de-agua-e-energia/2022/planilha_mensal_energia_empetur_-_LUZ.pdf",
            }.items():
                latest = max((r for r in records if r["resource"] == resource), key=lambda r: r["period"], default=None)
                if latest:
                    sources[resource] = latest.get("source_url") or "https://www.empetur.pe.gov.br/consumo-de-agua"
                else:
                    sources[resource] = original
            return self.send_json({
                "last_updated": data.get("last_updated"),
                "records": [public_record(r) for r in records],
                "sources": sources,
            })
        if path == "/api/period":
            query = parse_qs(parsed.query)
            resource = query.get("resource", [""])[0]
            period = query.get("period", [""])[0]
            try:
                result = analyze(read_data().get("records", []), resource, period)
                result["selected"] = public_record(result["selected"]) if result["selected"] else None
                for item in result["history"]:
                    if item["record"]:
                        item["record"] = public_record(item["record"])
                return self.send_json(result)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/overview":
            records = read_data().get("records", [])
            result = {}
            for resource in RESOURCES:
                periods = [r["period"] for r in records if r["resource"] == resource]
                result[resource] = analyze(records, resource, max(periods)) if periods else None
                if result[resource]:
                    result[resource].pop("history")
                    result[resource]["selected"] = public_record(result[resource]["selected"])
            return self.send_json(result)
        if path.startswith("/api/admin/"):
            if not self.auth_ok():
                return
            if path == "/api/admin/records":
                return self.send_json(read_data())
            return self.send_json({"error": "Rota não encontrada."}, HTTPStatus.NOT_FOUND)
        if path.startswith("/comprovantes/"):
            # Só arquivos explicitamente aprovados e ligados a um registro são publicados.
            return self.send_error(HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/admin/"):
            return self.send_json({"error": "Rota não encontrada."}, HTTPStatus.NOT_FOUND)
        if not self.auth_ok():
            return
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and urlparse(origin).netloc != host:
            return self.send_json({"error": "Origem não permitida."}, HTTPStatus.FORBIDDEN)
        if self.headers.get("X-Requested-With") != "EmpeturPainel":
            return self.send_json({"error": "Cabeçalho de solicitação ausente."}, HTTPStatus.FORBIDDEN)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_UPLOAD:
                raise ValueError("Arquivo ou solicitação vazia ou acima de 4 MB.")
            body = self.rfile.read(length)
            if path == "/api/admin/preview":
                fields = parse_multipart(self.headers.get("Content-Type", ""), body)
                resource = fields.get("resource", b"").decode("utf-8")
                document = fields.get("document", b"")
                if not document.startswith(b"%PDF-"):
                    raise ValueError("Selecione um arquivo PDF válido.")
                parsed = parse_pdf(document, resource)
                import_id = uuid.uuid4().hex
                if os.environ.get("VERCEL") and not blob_client():
                    return self.send_json({"error": "Configure um Vercel Blob privado para receber PDFs."}, HTTPStatus.SERVICE_UNAVAILABLE)
                save_import(import_id, document)
                return self.send_json({"import_id": import_id, **parsed})
            if path == "/api/admin/commit":
                payload = json.loads(body.decode("utf-8"))
                import_id = payload.get("import_id", "")
                if import_id and (not uuid_valid(import_id) or not import_exists(import_id)):
                    raise ValueError("Importação não encontrada. Envie o PDF novamente.")
                if os.environ.get("VERCEL") and not blob_client():
                    return self.send_json({"error": "Configure um Vercel Blob privado para publicar dados."}, HTTPStatus.SERVICE_UNAVAILABLE)
                rows = payload.get("rows")
                if not isinstance(rows, list) or not rows:
                    raise ValueError("Inclua pelo menos um mês para publicar.")
                normalized = [normalize_record(row) for row in rows]
                keys = [(r["resource"], r["period"]) for r in normalized]
                if len(set(keys)) != len(keys):
                    raise ValueError("Há meses repetidos na revisão.")
                with WRITE_LOCK:
                    data = read_data()
                    saved, replaced = apply_publication(data, normalized, self.admin_user, import_id, datetime.now(timezone.utc).isoformat())
                    save_data(data)
                return self.send_json({"saved": saved, "replaced": replaced})
            return self.send_json({"error": "Rota não encontrada."}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def uuid_valid(value: str) -> bool:
    return len(value) == 32 and all(char in "0123456789abcdef" for char in value)


if __name__ == "__main__":
    host = os.environ.get("EMPETUR_HOST", "127.0.0.1")
    port = int(os.environ.get("EMPETUR_PORT", "8765"))
    print(f"Painel EMPETUR em http://{host}:{port}/", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
