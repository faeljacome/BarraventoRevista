from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlsplit
import hashlib
import hmac
import json
import os
import secrets
import time
import webbrowser

from gerar_site import (
    CATEGORY_OPTIONS,
    INPUT_DIR,
    PROCESSED_DIR,
    SITE_DIR,
    UPLOADS_DIR,
    build_site,
    blocks_to_editor_markup,
    blocks_to_sidecar,
    editor_markup_to_blocks,
    extract_article,
    format_long_date,
    load_sidecar_metadata,
    normalize_hashtags,
    parse_categories,
    parse_csv_list,
    sidecar_path,
    slugify,
)


BUILD_LOCK = Lock()
MEMBER_LOCK = Lock()
SESSION_LOCK = Lock()
DATA_LOCK = Lock()
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
PROJECT_ROOT = SITE_DIR.parent
DATA_DIR = PROJECT_ROOT / "dados"
MEMBERS_FILE = DATA_DIR / "membros.json"
NOTICES_FILE = DATA_DIR / "recados.json"
STATS_FILE = DATA_DIR / "estatisticas.json"
SUBMISSIONS_FILE = DATA_DIR / "submissoes.json"
SUBMISSIONS_DIR = DATA_DIR / "submissoes"
SESSION_COOKIE_NAME = "barravento_member_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7
PASSWORD_ROUNDS = 240_000
SESSIONS: dict[str, dict[str, object]] = {}
ROLE_LABELS = {
    "admin": "Conselho Editorial",
    "reviewer": "Revisor",
}
DEFAULT_MEMBER_ROLE = "reviewer"


@dataclass
class UploadedFile:
    filename: str
    data: bytes


class UploadError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def validate_member_name(value: str) -> str:
    name = " ".join(value.strip().split())
    if len(name) < 2:
        raise UploadError("Informe o nome do membro.", 400)
    return name


def validate_member_email(value: str) -> str:
    email = normalize_email(value)
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain or "." not in domain:
        raise UploadError("Informe um e-mail valido.", 400)
    return email


def validate_member_password(value: str) -> str:
    password = value.strip()
    if len(password) < 8:
        raise UploadError("A senha precisa ter pelo menos 8 caracteres.", 400)
    return password


def normalize_member_role(value: str) -> str:
    role = str(value).strip().lower()
    if role not in ROLE_LABELS:
        return DEFAULT_MEMBER_ROLE
    return role


def is_member_admin(member: dict[str, str]) -> bool:
    return normalize_member_role(member.get("role", "")) == "admin"


def read_members() -> dict[str, dict[str, str]]:
    if not MEMBERS_FILE.exists():
        return {}

    try:
        raw = json.loads(MEMBERS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UploadError("O cadastro de membros esta corrompido.", 500) from exc

    payload = raw.get("members", raw) if isinstance(raw, dict) else {}
    if not isinstance(payload, dict):
        return {}

    members: dict[str, dict[str, str]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        email = normalize_email(str(value.get("email", key)))
        if not email:
            continue
        members[email] = {
            "name": str(value.get("name", "")).strip(),
            "email": email,
            "password_salt": str(value.get("password_salt", "")).strip(),
            "password_hash": str(value.get("password_hash", "")).strip(),
            "created_at": str(value.get("created_at", "")).strip(),
            "role": normalize_member_role(str(value.get("role", DEFAULT_MEMBER_ROLE)).strip()),
            "approved": "false" not in str(value.get("approved", True)).strip().lower() if "approved" in value else True,
            "approved_at": str(value.get("approved_at", "")).strip(),
        }
    return members


def write_members(members: dict[str, dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"members": members}
    MEMBERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, PASSWORD_ROUNDS)
    return salt_bytes.hex(), digest.hex()


def verify_password(password: str, member: dict[str, str]) -> bool:
    salt_hex = member.get("password_salt", "")
    stored_hash = member.get("password_hash", "")
    if not salt_hex or not stored_hash:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    _, candidate_hash = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, stored_hash)


def public_member_payload(member: dict[str, str]) -> dict[str, str]:
    return {
        "name": member.get("name", "").strip(),
        "email": member.get("email", "").strip(),
        "created_at": member.get("created_at", "").strip(),
        "role": normalize_member_role(member.get("role", DEFAULT_MEMBER_ROLE)),
        "role_label": ROLE_LABELS[normalize_member_role(member.get("role", DEFAULT_MEMBER_ROLE))],
        "approved": bool(member.get("approved", False)),
        "approved_at": member.get("approved_at", "").strip(),
    }


def register_member(name: str, email: str, password: str, role: str) -> dict[str, str]:
    normalized_name = validate_member_name(name)
    normalized_email = validate_member_email(email)
    normalized_password = validate_member_password(password)
    normalized_role = normalize_member_role(role)

    with MEMBER_LOCK:
        members = read_members()
        if normalized_email in members:
            raise UploadError("Ja existe um membro cadastrado com este e-mail.", 409)

        salt_hex, password_hash = hash_password(normalized_password)
        member = {
            "name": normalized_name,
            "email": normalized_email,
            "password_salt": salt_hex,
            "password_hash": password_hash,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "role": normalized_role,
            "approved": False,
            "approved_at": "",
        }
        members[normalized_email] = member
        write_members(members)
        return public_member_payload(member)


def authenticate_member(email: str, password: str) -> dict[str, str]:
    normalized_email = validate_member_email(email)
    normalized_password = validate_member_password(password)

    with MEMBER_LOCK:
        members = read_members()
        member = members.get(normalized_email)

    if member is None or not verify_password(normalized_password, member):
        raise UploadError("E-mail ou senha invalidos.", 401)
    if not bool(member.get("approved", False)):
        raise UploadError("Cadastro aguardando aprovacao do Conselho Editorial.", 403)
    return public_member_payload(member)


def create_session(email: str) -> str:
    token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        SESSIONS[token] = {
            "email": normalize_email(email),
            "expires_at": time.time() + SESSION_MAX_AGE,
        }
    return token


def expire_session(token: str | None) -> None:
    if token:
        with SESSION_LOCK:
            SESSIONS.pop(token, None)


def session_cookie(token: str | None, *, clear: bool = False) -> str:
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = "" if clear else (token or "")
    cookie[SESSION_COOKIE_NAME]["path"] = "/"
    cookie[SESSION_COOKIE_NAME]["httponly"] = True
    cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    cookie[SESSION_COOKIE_NAME]["max-age"] = "0" if clear else str(SESSION_MAX_AGE)
    return cookie.output(header="").strip()


def session_token_from_headers(headers) -> str | None:
    raw_cookie = headers.get("Cookie", "")
    if not raw_cookie:
        return None

    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(SESSION_COOKIE_NAME)
    if morsel is None:
        return None
    return morsel.value or None


def current_member_from_headers(headers) -> dict[str, str] | None:
    token = session_token_from_headers(headers)
    if not token:
        return None

    with SESSION_LOCK:
        session = dict(SESSIONS.get(token, {})) if token in SESSIONS else None
    if not session:
        return None

    expires_at = float(session.get("expires_at", 0) or 0)
    if expires_at <= time.time():
        expire_session(token)
        return None

    email = normalize_email(str(session.get("email", "")))
    if not email:
        expire_session(token)
        return None

    with MEMBER_LOCK:
        members = read_members()
        member = members.get(email)

    if member is None:
        expire_session(token)
        return None

    return public_member_payload(member)


def pending_member_registrations() -> list[dict[str, str]]:
    with MEMBER_LOCK:
        members = read_members()

    pending = [public_member_payload(member) for member in members.values() if not bool(member.get("approved", False))]
    pending.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return pending


def approve_member_registration(email: str) -> dict[str, str]:
    normalized_email = validate_member_email(email)
    with MEMBER_LOCK:
        members = read_members()
        member = members.get(normalized_email)
        if member is None:
            raise UploadError("Cadastro de membro nao encontrado.", 404)
        if bool(member.get("approved", False)):
            raise UploadError("Este cadastro ja foi aprovado.", 400)
        member["approved"] = True
        member["approved_at"] = datetime.now().isoformat(timespec="seconds")
        members[normalized_email] = member
        write_members(members)
        return public_member_payload(member)


def read_json_file(path: Path, default: object) -> object:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json_file(path: Path, payload: object) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_notice_message(value: str) -> str:
    message = "\n".join(part.rstrip() for part in value.replace("\r\n", "\n").splitlines()).strip()
    if len(message) < 2:
        raise UploadError("Escreva um recado antes de publicar.", 400)
    if len(message) > 5000:
        raise UploadError("O recado esta muito longo.", 400)
    return message


def read_notices() -> list[dict[str, str]]:
    raw = read_json_file(NOTICES_FILE, [])
    if isinstance(raw, dict):
        raw = raw.get("items", [])
    if not isinstance(raw, list):
        return []

    notices: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message", "")).strip()
        if not message:
            continue
        notices.append(
            {
                "id": str(item.get("id", "")).strip(),
                "message": message,
                "author_name": str(item.get("author_name", "")).strip() or "Membro",
                "author_email": str(item.get("author_email", "")).strip(),
                "created_at": str(item.get("created_at", "")).strip(),
            }
        )
    return notices


def add_notice(member: dict[str, str], message: str) -> dict[str, str]:
    normalized_message = normalize_notice_message(message)
    notice = {
        "id": secrets.token_hex(8),
        "message": normalized_message,
        "author_name": member.get("name", "").strip() or "Membro",
        "author_email": member.get("email", "").strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    with DATA_LOCK:
        notices = read_notices()
        notices.insert(0, notice)
        write_json_file(NOTICES_FILE, {"items": notices[:100]})
    return notice


def read_stats() -> dict[str, dict[str, int | str]]:
    raw = read_json_file(STATS_FILE, {})
    if isinstance(raw, dict):
        raw = raw.get("articles", raw)
    if not isinstance(raw, dict):
        return {}

    stats: dict[str, dict[str, int | str]] = {}
    for slug, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        stats[str(slug)] = {
            "views": int(payload.get("views", 0) or 0),
            "pdf_downloads": int(payload.get("pdf_downloads", 0) or 0),
            "updated_at": str(payload.get("updated_at", "")).strip(),
        }
    return stats


def write_stats(stats: dict[str, dict[str, int | str]]) -> None:
    write_json_file(STATS_FILE, {"articles": stats})


def record_stat(slug: str, kind: str) -> None:
    if kind not in {"views", "pdf_downloads"}:
        return
    with DATA_LOCK:
        stats = read_stats()
        entry = stats.setdefault(slug, {"views": 0, "pdf_downloads": 0, "updated_at": ""})
        entry[kind] = int(entry.get(kind, 0) or 0) + 1
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_stats(stats)


def list_articles():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return [
        extract_article(docx_file)
        for docx_file in sorted(
            PROCESSED_DIR.glob("*.docx"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    ]


def dashboard_rows() -> list[dict[str, object]]:
    with DATA_LOCK:
        stats = read_stats()

    rows: list[dict[str, object]] = []
    for article in list_articles():
        entry = stats.get(article.slug, {})
        rows.append(
            {
                "slug": article.slug,
                "title": article.title,
                "views": int(entry.get("views", 0) or 0),
                "pdf_downloads": int(entry.get("pdf_downloads", 0) or 0),
                "published_label": format_long_date(article.published_at),
                "article_url": f"/artigos/{article.slug}/",
                "pdf_url": f"/pdfs/{article.slug}.pdf",
            }
        )

    rows.sort(key=lambda item: (-int(item["views"]), -int(item["pdf_downloads"]), str(item["title"]).casefold()))
    return rows


def read_submissions() -> list[dict[str, object]]:
    raw = read_json_file(SUBMISSIONS_FILE, {"items": []})
    if isinstance(raw, dict):
        raw = raw.get("items", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def write_submissions(items: list[dict[str, object]]) -> None:
    write_json_file(SUBMISSIONS_FILE, {"items": items})


def pending_submission_items() -> list[dict[str, object]]:
    with DATA_LOCK:
        items = read_submissions()
    pending = [item for item in items if str(item.get("status", "pending")).strip() == "pending"]
    pending.sort(key=lambda item: str(item.get("requested_at", "")), reverse=True)
    return pending


def save_submission_file(submission_id: str, upload: UploadedFile | None, suffix_override: str | None = None) -> str:
    if upload is None or not upload.data:
        return ""
    target_dir = SUBMISSIONS_DIR / submission_id
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = suffix_override or Path(upload.filename).suffix
    safe_name = f"{slugify(Path(upload.filename).stem)}{suffix}"
    target = target_dir / safe_name
    target.write_bytes(upload.data)
    return safe_name


def field_csv_text(values: list[str]) -> str:
    return ", ".join(value for value in values if value)


def submission_requester(member: dict[str, str]) -> dict[str, str]:
    return {
        "name": member.get("name", "").strip(),
        "email": member.get("email", "").strip(),
        "role": normalize_member_role(member.get("role", DEFAULT_MEMBER_ROLE)),
        "role_label": ROLE_LABELS[normalize_member_role(member.get("role", DEFAULT_MEMBER_ROLE))],
    }


def create_pending_submission(
    *,
    kind: str,
    member: dict[str, str],
    payload: dict[str, object],
    docx: UploadedFile | None = None,
    image: UploadedFile | None = None,
) -> dict[str, object]:
    submission_id = secrets.token_hex(8)
    submission = {
        "id": submission_id,
        "kind": kind,
        "status": "pending",
        "requested_at": datetime.now().isoformat(timespec="seconds"),
        "requested_by": submission_requester(member),
        **payload,
    }

    if docx is not None and docx.data:
        submission["docx_filename"] = docx.filename
        submission["docx_file"] = save_submission_file(submission_id, docx, ".docx")
    if image is not None and image.data:
        submission["image_filename"] = image.filename
        submission["image_file"] = save_submission_file(submission_id, image, Path(image.filename).suffix)

    with DATA_LOCK:
        items = read_submissions()
        items.append(submission)
        write_submissions(items)
    return submission


def create_article_submission(
    fields: dict[str, list[str]],
    files: dict[str, UploadedFile],
    member: dict[str, str],
) -> dict[str, object]:
    docx = files.get("docx")
    image = files.get("image")
    if docx is None or not docx.data:
        raise UploadError("Selecione um arquivo .docx para publicar.", 400)
    if image is None or not image.data:
        raise UploadError("Selecione uma imagem de capa para publicar.", 400)

    selected_categories = field_values(fields, "categories")
    if not selected_categories:
        raise UploadError("Selecione pelo menos uma categoria.", 400)

    ensure_docx_upload(docx.filename)
    sanitize_image_suffix(image.filename)
    categories = parse_categories(selected_categories)
    payload = {
        "title": field_text(fields, "title"),
        "author": field_text(fields, "author"),
        "summary": field_text(fields, "summary"),
        "categories": categories,
        "tags": parse_csv_list(field_text(fields, "tags")),
        "hashtags": normalize_hashtags(parse_csv_list(field_text(fields, "hashtags"))),
        "source_name": docx.filename,
    }
    submission = create_pending_submission(kind="create", member=member, payload=payload, docx=docx, image=image)
    return {
        "ok": True,
        "pending": True,
        "message": "Texto enviado para aprovacao do Conselho Editorial.",
        "submission_id": submission["id"],
        "title": payload["title"] or Path(docx.filename).stem,
    }


def edit_article_submission(
    fields: dict[str, list[str]],
    files: dict[str, UploadedFile],
    member: dict[str, str],
) -> dict[str, object]:
    slug = slugify(field_text(fields, "slug"))
    if not slug:
        raise UploadError("Escolha um texto para editar.", 400)

    article = read_current_article(slug)
    selected_categories = field_values(fields, "categories")
    if not selected_categories:
        raise UploadError("Selecione pelo menos uma categoria.", 400)
    categories = parse_categories(selected_categories, title=article.title, slug=article.slug, lead=article.lead)

    title = field_text(fields, "title")
    author = field_text(fields, "author")
    summary = field_text(fields, "summary")
    tags = parse_csv_list(field_text(fields, "tags"))
    hashtags = normalize_hashtags(parse_csv_list(field_text(fields, "hashtags")))
    body_editor = field_text(fields, "body")
    current_body_editor = blocks_to_editor_markup(article.blocks)
    new_docx = files.get("docx")
    new_image = files.get("image")

    if new_docx is not None and new_docx.data:
        ensure_docx_upload(new_docx.filename)
    if new_image is not None and new_image.data:
        sanitize_image_suffix(new_image.filename)

    title_changed = title != article.title
    body_changed = normalize_editor_value(body_editor) != normalize_editor_value(current_body_editor)
    metadata_changed = any(
        [
            title_changed,
            categories != article.categories,
            author != article.author,
            summary != article.summary,
            tags != article.tags,
            hashtags != article.hashtags,
            body_changed,
        ]
    )
    docx_changed = bool(new_docx and new_docx.data)
    image_changed = bool(new_image and new_image.data)
    if not any([docx_changed, image_changed, metadata_changed]):
        raise UploadError("Nenhuma alteracao foi feita. A edicao nao sera executada.", 400)

    payload = {
        "slug": slug,
        "title": title,
        "author": author,
        "summary": summary,
        "categories": categories,
        "tags": tags,
        "hashtags": hashtags,
        "body": body_editor,
    }
    submission = create_pending_submission(kind="edit", member=member, payload=payload, docx=new_docx, image=new_image)
    return {
        "ok": True,
        "pending": True,
        "message": "Edicao enviada para aprovacao do Conselho Editorial.",
        "submission_id": submission["id"],
        "title": title or article.title,
    }


def submission_uploaded_file(submission: dict[str, object], key: str) -> UploadedFile | None:
    stored_name = str(submission.get(f"{key}_file", "")).strip()
    original_name = str(submission.get(f"{key}_filename", "")).strip()
    if not stored_name:
        return None
    target = SUBMISSIONS_DIR / str(submission.get("id", "")).strip() / stored_name
    if not target.exists():
        return None
    return UploadedFile(filename=original_name or stored_name, data=target.read_bytes())


def approve_submission_item(submission_id: str) -> dict[str, object]:
    with DATA_LOCK:
        items = read_submissions()

    submission = next((item for item in items if str(item.get("id", "")).strip() == submission_id), None)
    if submission is None:
        raise UploadError("Solicitacao pendente nao encontrada.", 404)
    if str(submission.get("status", "pending")).strip() != "pending":
        raise UploadError("Esta solicitacao ja foi processada.", 400)

    kind = str(submission.get("kind", "")).strip()
    if kind == "create":
        docx = submission_uploaded_file(submission, "docx")
        image = submission_uploaded_file(submission, "image")
        fields = {
            "title": [str(submission.get("title", ""))],
            "author": [str(submission.get("author", ""))],
            "summary": [str(submission.get("summary", ""))],
            "categories": [str(item) for item in submission.get("categories", []) if str(item).strip()],
            "tags": [field_csv_text([str(item) for item in submission.get("tags", []) if str(item).strip()])],
            "hashtags": [field_csv_text([str(item) for item in submission.get("hashtags", []) if str(item).strip()])],
        }
        files = {"docx": docx, "image": image} if docx and image else {}
        result = create_article(fields, files)
    elif kind == "edit":
        fields = {
            "slug": [str(submission.get("slug", ""))],
            "title": [str(submission.get("title", ""))],
            "author": [str(submission.get("author", ""))],
            "summary": [str(submission.get("summary", ""))],
            "body": [str(submission.get("body", ""))],
            "categories": [str(item) for item in submission.get("categories", []) if str(item).strip()],
            "tags": [field_csv_text([str(item) for item in submission.get("tags", []) if str(item).strip()])],
            "hashtags": [field_csv_text([str(item) for item in submission.get("hashtags", []) if str(item).strip()])],
        }
        files: dict[str, UploadedFile] = {}
        docx = submission_uploaded_file(submission, "docx")
        image = submission_uploaded_file(submission, "image")
        if docx is not None:
            files["docx"] = docx
        if image is not None:
            files["image"] = image
        result = edit_article(fields, files)
    else:
        raise UploadError("Tipo de solicitacao pendente invalido.", 400)

    submission["status"] = "approved"
    submission["approved_at"] = datetime.now().isoformat(timespec="seconds")
    with DATA_LOCK:
        refreshed = read_submissions()
        for index, item in enumerate(refreshed):
            if str(item.get("id", "")).strip() == submission_id:
                refreshed[index] = submission
                break
        write_submissions(refreshed)
    return result


def article_slug_from_request_path(request_path: str) -> str | None:
    parts = [part for part in request_path.split("/") if part]
    if len(parts) < 2 or parts[0] != "artigos":
        return None
    if len(parts) == 2:
        return parts[1]
    if len(parts) == 3 and parts[2] in {"index.html", ""}:
        return parts[1]
    return None


def pdf_slug_from_request_path(request_path: str) -> str | None:
    parts = [part for part in request_path.split("/") if part]
    if len(parts) != 2 or parts[0] != "pdfs" or not parts[1].lower().endswith(".pdf"):
        return None
    return Path(parts[1]).stem


def normalize_editor_value(value: str) -> str:
    return value.replace("\r\n", "\n").strip()


def field_values(fields: dict[str, list[str]], name: str) -> list[str]:
    return [value.strip() for value in fields.get(name, []) if value.strip()]


def field_text(fields: dict[str, list[str]], name: str) -> str:
    values = field_values(fields, name)
    return values[-1] if values else ""


def ensure_docx_upload(filename: str) -> str:
    original = Path(filename).name
    if Path(original).suffix.lower() != ".docx":
        raise UploadError("Envie apenas arquivos .docx.", 400)
    return slugify(Path(original).stem)


def sanitize_image_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise UploadError("Envie uma imagem .jpg, .jpeg, .png ou .webp.", 400)
    return suffix


def unique_article_slug(base_slug: str) -> str:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    candidate = base_slug or "artigo"
    counter = 2
    while (
        (INPUT_DIR / f"{candidate}.docx").exists()
        or (PROCESSED_DIR / f"{candidate}.docx").exists()
        or (INPUT_DIR / f"{candidate}.json").exists()
        or (PROCESSED_DIR / f"{candidate}.json").exists()
    ):
        candidate = f"{base_slug}-{counter}"
        counter += 1
    return candidate


def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, list[str]], dict[str, UploadedFile]]:
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )

    fields: dict[str, list[str]] = {}
    files: dict[str, UploadedFile] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue

        field_name = part.get_param("name", header="content-disposition")
        if not field_name:
            continue

        filename = part.get_filename()
        if filename:
            files[field_name] = UploadedFile(
                filename=filename,
                data=part.get_payload(decode=True) or b"",
            )
        else:
            fields.setdefault(field_name, []).append((part.get_content() or "").strip())

    return fields, files


def set_timestamp(path: Path) -> None:
    now = time.time()
    os.utime(path, (now, now))


def article_docx_path(slug: str) -> Path:
    return PROCESSED_DIR / f"{slug}.docx"


def read_current_article(slug: str):
    docx_path = article_docx_path(slug)
    if not docx_path.exists():
        raise UploadError("O texto selecionado para edicao nao existe mais.", 404)
    return extract_article(docx_path)


def current_uploaded_image_path(article) -> Path | None:
    if article.image_scope != "uploads" or not article.image_file:
        return None
    image_path = UPLOADS_DIR / article.image_file
    return image_path if image_path.exists() else None


def save_uploaded_image(slug: str, image: UploadedFile) -> str:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = sanitize_image_suffix(image.filename)
    image_name = f"{slug}{suffix}"
    target = UPLOADS_DIR / image_name

    for existing in UPLOADS_DIR.glob(f"{slug}.*"):
        if existing.suffix.lower() in ALLOWED_IMAGE_SUFFIXES and existing.name != image_name:
            existing.unlink()

    target.write_bytes(image.data)
    return image_name


def build_response(slug: str, message: str) -> dict[str, object]:
    articles = build_site()
    article = next((item for item in articles if item.slug == slug), None)
    if article is None:
        raise UploadError("O site nao conseguiu localizar o texto apos a atualizacao.", 500)

    return {
        "ok": True,
        "message": message,
        "title": article.title,
        "slug": article.slug,
        "article_url": f"/artigos/{article.slug}/",
        "home_url": "/",
    }


def create_article(fields: dict[str, list[str]], files: dict[str, UploadedFile]) -> dict[str, object]:
    docx = files.get("docx")
    image = files.get("image")
    if docx is None or not docx.data:
        raise UploadError("Selecione um arquivo .docx para publicar.", 400)
    if image is None or not image.data:
        raise UploadError("Selecione uma imagem de capa para publicar.", 400)

    selected_categories = field_values(fields, "categories")
    if not selected_categories:
        raise UploadError("Selecione pelo menos uma categoria.", 400)
    categories = parse_categories(selected_categories)

    base_slug = ensure_docx_upload(docx.filename)
    slug = unique_article_slug(base_slug)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    docx_path = article_docx_path(slug)
    docx_path.write_bytes(docx.data)
    set_timestamp(docx_path)

    image_name = save_uploaded_image(slug, image)
    metadata = {
        "title": field_text(fields, "title"),
        "author": field_text(fields, "author"),
        "summary": field_text(fields, "summary"),
        "categories": categories,
        "tags": parse_csv_list(field_text(fields, "tags")),
        "hashtags": normalize_hashtags(parse_csv_list(field_text(fields, "hashtags"))),
        "image_scope": "uploads",
        "image_file": image_name,
        "image_alt": Path(image.filename).stem,
        "image_caption": "Imagem enviada na publicacao.",
    }
    sidecar_path(docx_path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return build_response(slug, "Arquivo publicado com sucesso.")


def edit_article(fields: dict[str, list[str]], files: dict[str, UploadedFile]) -> dict[str, object]:
    slug = slugify(field_text(fields, "slug"))
    if not slug:
        raise UploadError("Escolha um texto para editar.", 400)

    article = read_current_article(slug)
    docx_path = article_docx_path(slug)
    current_sidecar = load_sidecar_metadata(docx_path)

    selected_categories = field_values(fields, "categories")
    if not selected_categories:
        raise UploadError("Selecione pelo menos uma categoria.", 400)

    categories = parse_categories(
        selected_categories,
        title=article.title,
        slug=article.slug,
        lead=article.lead,
    )

    title = field_text(fields, "title")
    author = field_text(fields, "author")
    summary = field_text(fields, "summary")
    tags = parse_csv_list(field_text(fields, "tags"))
    hashtags = normalize_hashtags(parse_csv_list(field_text(fields, "hashtags")))
    body_editor = field_text(fields, "body")
    current_body_editor = blocks_to_editor_markup(article.blocks)

    new_docx = files.get("docx")
    if new_docx is not None and new_docx.data:
        ensure_docx_upload(new_docx.filename)
    current_docx_bytes = docx_path.read_bytes()
    docx_changed = bool(new_docx and new_docx.data and new_docx.data != current_docx_bytes)

    new_image = files.get("image")
    current_image_path = current_uploaded_image_path(article)
    image_changed = False
    if new_image is not None and new_image.data:
        sanitize_image_suffix(new_image.filename)
        image_changed = current_image_path is None or new_image.data != current_image_path.read_bytes()

    title_changed = title != article.title
    body_changed = normalize_editor_value(body_editor) != normalize_editor_value(current_body_editor)
    metadata_changed = any(
        [
            title_changed,
            categories != article.categories,
            author != article.author,
            summary != article.summary,
            tags != article.tags,
            hashtags != article.hashtags,
            body_changed,
        ]
    )

    if not any([docx_changed, image_changed, metadata_changed]):
        raise UploadError("Nenhuma alteracao foi feita. A edicao nao sera executada.", 400)

    if docx_changed and new_docx is not None:
        docx_path.write_bytes(new_docx.data)

    if image_changed and new_image is not None:
        image_scope = "uploads"
        image_file = save_uploaded_image(slug, new_image)
        image_alt = Path(new_image.filename).stem
        image_caption = "Imagem atualizada na edicao."
    else:
        image_scope = str(current_sidecar.get("image_scope", "")).strip() or article.image_scope
        image_file = str(current_sidecar.get("image_file", "")).strip() or article.image_file
        image_alt = str(current_sidecar.get("image_alt", "")).strip() or article.image_alt
        image_caption = str(current_sidecar.get("image_caption", "")).strip() or article.image_caption

    body_blocks_payload = current_sidecar.get("body_blocks")
    if body_changed:
        parsed_blocks = editor_markup_to_blocks(body_editor)
        if not parsed_blocks:
            raise UploadError("Escreva o corpo do texto antes de salvar a edicao.", 400)
        body_blocks_payload = blocks_to_sidecar(parsed_blocks)
    elif docx_changed:
        body_blocks_payload = []

    set_timestamp(docx_path)
    metadata = {
        "title": title,
        "author": author,
        "summary": summary,
        "categories": categories,
        "tags": tags,
        "hashtags": hashtags,
        "image_scope": image_scope,
        "image_file": image_file,
        "image_alt": image_alt,
        "image_caption": image_caption,
    }
    if body_blocks_payload:
        metadata["body_blocks"] = body_blocks_payload
    sidecar_path(docx_path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return build_response(slug, "Arquivo atualizado com sucesso.")


class UploadHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        article_slug = article_slug_from_request_path(request_path)
        if article_slug:
            record_stat(article_slug, "views")

        pdf_slug = pdf_slug_from_request_path(request_path)
        if pdf_slug:
            record_stat(pdf_slug, "pdf_downloads")

        if request_path == "/api/members/session":
            try:
                member = self.current_member()
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "authenticated": member is not None,
                        "member": member,
                    },
                )
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"ok": False, "error": f"Falha interna ao verificar sessao: {exc}"})
            return

        if request_path in {"/api/members/notices", "/api/members/dashboard"}:
            try:
                member = self.require_member()
                payload = self.handle_member_get(request_path, member)
                self.send_json(200, payload)
            except UploadError as exc:
                self.send_json(exc.status_code, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"ok": False, "error": f"Falha interna no painel: {exc}"})
            return

        if request_path == "/api/members/approvals":
            try:
                member = self.require_admin()
                self.send_json(200, self.handle_approvals_get(member))
            except UploadError as exc:
                self.send_json(exc.status_code, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"ok": False, "error": f"Falha interna nas aprovacoes: {exc}"})
            return

        super().do_GET()

    def do_POST(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path == "/api/members/notices":
            try:
                member = self.require_member()
                payload = self.handle_member_post(request_path, member)
                self.send_json(201, payload)
            except UploadError as exc:
                self.send_json(exc.status_code, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"ok": False, "error": f"Falha interna ao publicar recado: {exc}"})
            return

        if request_path in {"/api/members/approvals/registrations/approve", "/api/members/approvals/submissions/approve"}:
            try:
                member = self.require_admin()
                payload = self.handle_approvals_post(request_path, member)
                self.send_json(200, payload)
            except UploadError as exc:
                self.send_json(exc.status_code, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"ok": False, "error": f"Falha interna ao aprovar: {exc}"})
            return

        if request_path in {"/api/members/register", "/api/members/login", "/api/members/logout"}:
            try:
                response, status_code, headers = self.handle_member_request(request_path)
                self.send_json(status_code, response, headers=headers)
            except UploadError as exc:
                self.send_json(exc.status_code, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"ok": False, "error": f"Falha interna ao autenticar: {exc}"})
            return

        if request_path not in {"/api/upload", "/api/edit"}:
            self.send_error(404, "Rota nao encontrada.")
            return

        try:
            member = self.require_member()
            response, status_code = self.handle_upload_request(request_path, member)
            self.send_json(status_code, response)
        except UploadError as exc:
            self.send_json(exc.status_code, {"ok": False, "error": str(exc)})
        except Exception as exc:  # pragma: no cover
            self.send_json(500, {"ok": False, "error": f"Falha interna ao publicar: {exc}"})

    def log_message(self, format: str, *args) -> None:
        print(f"[servidor] {self.address_string()} - {format % args}")

    def send_json(
        self,
        status_code: int,
        payload: dict[str, object],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def current_member(self) -> dict[str, str] | None:
        return current_member_from_headers(self.headers)

    def require_member(self) -> dict[str, str]:
        member = self.current_member()
        if member is None:
            raise UploadError("Acesso restrito a membros. Entre com e-mail e senha para continuar.", 401)
        return member

    def require_admin(self) -> dict[str, str]:
        member = self.require_member()
        if not is_member_admin(member):
            raise UploadError("Somente o Conselho Editorial pode acessar esta area.", 403)
        return member

    def read_json_payload(self) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise UploadError("Envio invalido. O formulario precisa usar JSON.", 400)

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}

        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise UploadError("Os dados enviados nao estao em JSON valido.", 400) from exc

        if not isinstance(payload, dict):
            raise UploadError("Os dados enviados precisam formar um objeto JSON.", 400)
        return payload

    def handle_member_request(
        self,
        request_path: str,
    ) -> tuple[dict[str, object], int, dict[str, str]]:
        if request_path == "/api/members/logout":
            token = session_token_from_headers(self.headers)
            expire_session(token)
            return (
                {"ok": True, "message": "Sessao encerrada.", "authenticated": False, "member": None},
                200,
                {"Set-Cookie": session_cookie(None, clear=True)},
            )

        payload = self.read_json_payload()
        email = str(payload.get("email", "")).strip()
        password = str(payload.get("password", ""))

        if request_path == "/api/members/register":
            name = str(payload.get("name", "")).strip()
            role = str(payload.get("role", DEFAULT_MEMBER_ROLE)).strip()
            member = register_member(name, email, password, role)
            return (
                {"ok": True, "message": "Cadastro enviado para aprovacao do Conselho Editorial.", "member": member},
                201,
                {},
            )

        member = authenticate_member(email, password)
        token = create_session(member["email"])
        return (
            {"ok": True, "message": "Login realizado com sucesso.", "member": member},
            200,
            {"Set-Cookie": session_cookie(token)},
        )

    def handle_member_get(self, request_path: str, member: dict[str, str]) -> dict[str, object]:
        if request_path == "/api/members/notices":
            return {
                "ok": True,
                "member": member,
                "items": read_notices(),
            }

        return {
            "ok": True,
            "member": member,
            "items": dashboard_rows(),
        }

    def handle_approvals_get(self, member: dict[str, str]) -> dict[str, object]:
        submissions = []
        for item in pending_submission_items():
            submissions.append(
                {
                    "id": str(item.get("id", "")).strip(),
                    "kind": str(item.get("kind", "")).strip(),
                    "title": str(item.get("title", "")).strip() or str(item.get("slug", "")).strip() or str(item.get("source_name", "")).strip() or "Sem titulo",
                    "slug": str(item.get("slug", "")).strip(),
                    "requested_at": str(item.get("requested_at", "")).strip(),
                    "requested_by": item.get("requested_by", {}),
                    "categories": [str(category) for category in item.get("categories", []) if str(category).strip()],
                }
            )

        return {
            "ok": True,
            "member": member,
            "registrations": pending_member_registrations(),
            "submissions": submissions,
        }

    def handle_member_post(self, request_path: str, member: dict[str, str]) -> dict[str, object]:
        payload = self.read_json_payload()
        if request_path == "/api/members/notices":
            message = str(payload.get("message", ""))
            notice = add_notice(member, message)
            return {
                "ok": True,
                "message": "Recado publicado com sucesso.",
                "item": notice,
            }

        raise UploadError("Rota de membros nao encontrada.", 404)

    def handle_approvals_post(self, request_path: str, member: dict[str, str]) -> dict[str, object]:
        payload = self.read_json_payload()
        if request_path == "/api/members/approvals/registrations/approve":
            approved = approve_member_registration(str(payload.get("email", "")).strip())
            return {
                "ok": True,
                "message": "Cadastro aprovado com sucesso.",
                "member": member,
                "approved_registration": approved,
            }

        if request_path == "/api/members/approvals/submissions/approve":
            result = approve_submission_item(str(payload.get("id", "")).strip())
            return {
                "ok": True,
                "message": "Publicacao aprovada com sucesso.",
                "member": member,
                "result": result,
            }

        raise UploadError("Rota de aprovacao nao encontrada.", 404)

    def handle_upload_request(self, request_path: str, member: dict[str, str]) -> tuple[dict[str, object], int]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise UploadError("Envio invalido. O formulario precisa usar multipart/form-data.", 400)

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise UploadError("Nenhum arquivo foi enviado.", 400)

        body = self.rfile.read(content_length)
        fields, files = parse_multipart(content_type, body)
        with BUILD_LOCK:
            if request_path == "/api/upload":
                if is_member_admin(member):
                    return create_article(fields, files), 201
                return create_article_submission(fields, files, member), 202
            if is_member_admin(member):
                return edit_article(fields, files), 200
            return edit_article_submission(fields, files, member), 202


def create_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), UploadHandler)


def maybe_open_browser(port: int) -> None:
    def _open() -> None:
        webbrowser.open(f"http://127.0.0.1:{port}/membros/", new=2)

    Thread(target=_open, daemon=True).start()


def main() -> None:
    parser = ArgumentParser(description="Servidor local para publicacao e edicao de textos.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    build_site()
    server = create_server(args.port)
    print(f"Servidor pronto em http://127.0.0.1:{args.port}/membros/")
    if args.open:
        maybe_open_browser(args.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
