from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape, unescape
from pathlib import Path
import json
import math
import os
import re
import shutil
import unicodedata
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET
import zipfile

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Image as PlatypusImage, KeepTogether, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
ASSETS_DIR = SITE_DIR / "assets"
ARTICLES_DIR = SITE_DIR / "artigos"
CATEGORY_DIR = SITE_DIR / "categorias"
WHO_DIR = SITE_DIR / "quem-somos"
CONTACT_DIR = SITE_DIR / "contato"
SEARCH_DIR = SITE_DIR / "busca"
MEMBERS_DIR = SITE_DIR / "membros"
PANEL_DIR = SITE_DIR / "painel"
COOKIE_POLICY_DIR = SITE_DIR / "politica-de-cookies"
PDF_DIR = SITE_DIR / "pdfs"
PROFILE_DIR = SITE_DIR / "perfis"
INPUT_DIR = ROOT / "conteudo" / "entrada-docx"
PROCESSED_DIR = ROOT / "conteudo" / "processados"
UPLOADS_DIR = SITE_DIR / "uploads"
BACKUPS_DIR = ROOT / "dados" / "backups"
MEMBERS_FILE = ROOT / "dados" / "membros.json"
WHO_DATA_FILE = ROOT / "dados" / "quem-somos.json"
STATS_FILE = ROOT / "dados" / "estatisticas.json"
TEXT_BACKUP_ARCHIVE = BACKUPS_DIR / "textos-publicados.zip"
SUBMISSIONS_FILE = ROOT / "dados" / "submissoes.json"

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DOCX_DRAWING_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
CORE_NS = {"dc": "http://purl.org/dc/elements/1.1/"}

CATEGORY_OPTIONS = [
    "Editoriais",
    "Entrevistas",
    "Pol\u00edtica e Cr\u00edtica Econ\u00f4mica",
    "Ideologia, Arte e Cultura",
    "Tradu\u00e7\u00f5es",
    "Teoria em Movimento",
    "Textos liter\u00e1rios",
]
DEFAULT_CATEGORY = CATEGORY_OPTIONS[0]
DEFAULT_IMAGE_FILE = "logo-barravento.png"
SITE_LOGO_FILE = "logo_revista.png"
SITE_SYMBOL_FILE = "logo_farol.png"
SITE_BRAND_FONT_SOURCE = ROOT / "Font" / "blastimo_sans" / "BLASTIMO SANS.ttf"
SITE_BRAND_FONT_FILE = "blastimo-sans.ttf"
SITE_NAME = "Revista Barravento"
SITE_PUBLIC_URL = os.environ.get("SITE_PUBLIC_URL", "").strip().rstrip("/")
DEFAULT_SOCIAL_IMAGE = f"/assets/{SITE_LOGO_FILE}"
INSTAGRAM_URL = "https://www.instagram.com/revistabarravento?utm_source=ig_web_button_share_sheet&igsh=ZDNlZDc0MzIxNw=="
PDF_ACCENT = HexColor("#8d2f23")
PDF_MUTED = HexColor("#6a645f")
PDF_TEXT = HexColor("#2a201d")
PDF_RULE = HexColor("#d3b6ad")
MEMBER_OFFICE_OPTIONS = [
    "Opcao A",
    "Opcao B",
    "Opcao C",
]
KNOWN_TEXT_REPAIRS = {
    "J\ufffd\ufffdCOME": "JÁCOME",
    "Jï¿½ï¿½COME": "JÁCOME",
}


@dataclass
class Block:
    kind: str
    text: str
    level: int = 0
    html: str = ""
    align: str = "left"


@dataclass
class Article:
    article_id: str
    slug: str
    title: str
    author: str
    author_text: str
    categories: list[str]
    summary: str
    lead: str
    reading_time: int
    published_at: datetime
    updated_at: datetime
    source_name: str
    image_scope: str
    image_file: str
    image_alt: str
    image_caption: str
    tags: list[str]
    hashtags: list[str]
    blocks: list[Block]
    body_html: str = ""
    author_members: list[dict[str, str]] | None = None


@dataclass
class MemberProfile:
    name: str
    email: str
    role: str
    role_label: str
    profile_slug: str
    editorial_role: str
    education: str
    photo_url: str
    linked_articles: list[dict[str, str]]


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    chars: list[str] = []
    last_dash = False
    for char in ascii_value:
        if char.isalnum():
            chars.append(char)
            last_dash = False
        elif not last_dash:
            chars.append("-")
            last_dash = True
    slug = "".join(chars).strip("-")
    return slug or "artigo"


def sidecar_path(path: Path) -> Path:
    return path.with_suffix(".json")


def parse_stored_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                return parsed.replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    return None


def normalize_text_value(value: str) -> str:
    text = unicodedata.normalize("NFC", value.replace("\xa0", " "))
    for broken, fixed in KNOWN_TEXT_REPAIRS.items():
        text = text.replace(broken, fixed)
    return text


def normalize_loaded_value(value: object) -> object:
    if isinstance(value, str):
        return normalize_text_value(value)
    if isinstance(value, list):
        return [normalize_loaded_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_loaded_value(item) for key, item in value.items()}
    return value


def read_json_file(path: Path, fallback: object) -> object:
    if not path.exists():
        return fallback
    try:
        return normalize_loaded_value(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return fallback


def write_json_file(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_member_role(value: object) -> str:
    role = str(value or "").strip().lower()
    return role if role in {"admin", "reviewer"} else "reviewer"


def role_label(role: str) -> str:
    return "Conselho Editorial" if role == "admin" else "Revisor"


def normalize_member_office(value: object) -> str:
    office = str(value or "").strip()
    return office if office in MEMBER_OFFICE_OPTIONS else MEMBER_OFFICE_OPTIONS[0]


def member_profile_slug(name: str, email: str, explicit: object = "") -> str:
    direct = slugify(str(explicit or "").strip())
    if direct and direct != "artigo":
        return direct
    email_local = slugify(email.split("@", 1)[0] if "@" in email else email)
    base = slugify(name or email_local)
    if email_local and email_local not in base:
        return slugify(f"{base}-{email_local}")
    return base


def load_member_profiles() -> list[MemberProfile]:
    raw = read_json_file(MEMBERS_FILE, {})
    source = raw.get("members", raw) if isinstance(raw, dict) else {}
    if not isinstance(source, dict):
        return []

    profiles: list[MemberProfile] = []
    for key, item in source.items():
        if not isinstance(item, dict):
            continue
        approved = item.get("approved", True)
        if str(approved).strip().lower() == "false":
            continue
        published = item.get("profile_published", bool(str(item.get("name", "")).strip()))
        if str(published).strip().lower() == "false":
            continue
        name = str(item.get("name", "")).strip()
        email = str(item.get("email", key)).strip().lower()
        if not name or not email:
            continue
        role = normalize_member_role(item.get("role"))
        profiles.append(
            MemberProfile(
                name=name,
                email=email,
                role=role,
                role_label=role_label(role),
                profile_slug=member_profile_slug(name, email, item.get("profile_slug")),
                editorial_role=normalize_member_office(item.get("editorial_role")),
                education=str(item.get("education", "")).strip(),
                photo_url=str(item.get("photo_url", "")).strip(),
                linked_articles=[
                    {
                        "article_id": str(link.get("article_id", "")).strip(),
                        "title": str(link.get("title", "")).strip(),
                        "url": str(link.get("url", "")).strip(),
                        "slug": str(link.get("slug", "")).strip(),
                    }
                    for link in (item.get("linked_articles", []) if isinstance(item.get("linked_articles", []), list) else [])
                    if isinstance(link, dict) and str(link.get("title", "")).strip()
                ],
            )
        )
    profiles.sort(key=lambda member: member.name.casefold())
    return profiles


def load_who_content() -> dict[str, str]:
    raw = read_json_file(WHO_DATA_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "title": str(raw.get("title", "")).strip() or "Quem Somos",
        "summary": str(raw.get("summary", "")).strip() or "Pagina propria para apresentar a revista, a linha editorial e a equipe responsavel.",
        "body": str(raw.get("body", "")).strip() or "Esta pagina foi preparada para receber a apresentacao institucional da Revista Barravento.",
    }


def split_author_parts(value: str) -> list[str]:
    parts = re.split(r"[;,]\s*", str(value or "").strip())
    return [part.strip() for part in parts if part.strip()]


def author_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    compact = re.sub(r"\s+", " ", ascii_only).strip().casefold()
    return compact


def compose_article_author(author_text: str, author_members: list[dict[str, str]] | None) -> str:
    parts: list[str] = []
    known_keys: set[str] = set()
    for item in split_author_parts(author_text):
        item_key = author_key(item)
        if item and item_key not in known_keys:
            parts.append(item)
            known_keys.add(item_key)
    for member in (author_members or []):
        name = str(member.get("name", "")).strip()
        name_key = author_key(name)
        if name and name_key not in known_keys:
            parts.append(name)
            known_keys.add(name_key)
    return ", ".join(parts) if parts else "Redacao"


def persist_article_author_state(article: Article) -> None:
    sidecar = sidecar_path(PROCESSED_DIR / f"{article.slug}.docx")
    payload = read_json_file(sidecar, {})
    if not isinstance(payload, dict):
        payload = {}
    payload["article_id"] = article.article_id
    payload["author"] = article.author
    payload["author_text"] = article.author_text
    payload["author_members"] = article.author_members or []
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def enrich_article_member_links(articles: list[Article], members: list[MemberProfile]) -> None:
    lookup: dict[str, MemberProfile] = {}
    for member in members:
        lookup[slugify(member.name)] = member
        lookup[slugify(member.email)] = member
        lookup[slugify(member.profile_slug)] = member
        lookup[author_key(member.name)] = member
        lookup[author_key(member.email)] = member

    for article in articles:
        changed = False
        current_members = list(article.author_members or [])
        known_emails = {str(item.get("email", "")).strip().lower() for item in current_members}
        remaining_parts: list[str] = []
        source_parts = split_author_parts(article.author_text or article.author)
        for part in source_parts:
            member = lookup.get(author_key(part)) or lookup.get(slugify(part))
            if member:
                if member.email not in known_emails:
                    current_members.append(
                        {
                            "email": member.email,
                            "name": member.name,
                            "profile_slug": member.profile_slug,
                        }
                    )
                    known_emails.add(member.email)
                    changed = True
                continue
            remaining_parts.append(part)
        next_author_text = str(article.author_text or "").strip()
        if not next_author_text and remaining_parts:
            next_author_text = ", ".join(remaining_parts)
            changed = True
        next_author = compose_article_author(next_author_text, current_members)
        if article.article_id == article.slug:
            changed = True
        if next_author_text != article.author_text or next_author != article.author or current_members != (article.author_members or []):
            article.author_text = next_author_text
            article.author_members = current_members
            article.author = next_author
            changed = True
        if changed:
            persist_article_author_state(article)


def sync_submission_author_links(members: list[MemberProfile]) -> None:
    raw = read_json_file(SUBMISSIONS_FILE, {})
    if isinstance(raw, dict):
        items = raw.get("items")
    else:
        items = raw
    if not isinstance(items, list):
        return

    lookup: dict[str, MemberProfile] = {}
    for member in members:
        lookup[author_key(member.name)] = member
        lookup[author_key(member.email)] = member
        lookup[slugify(member.name)] = member
        lookup[slugify(member.email)] = member
        lookup[slugify(member.profile_slug)] = member

    changed = False
    for item in items:
        if not isinstance(item, dict):
            continue
        current_members = []
        known_emails: set[str] = set()
        for member in (item.get("author_members", []) if isinstance(item.get("author_members", []), list) else []):
            if not isinstance(member, dict):
                continue
            email = str(member.get("email", "")).strip().lower()
            name = str(member.get("name", "")).strip()
            profile_slug = str(member.get("profile_slug", "")).strip()
            if not email:
                continue
            if not name:
                matched = lookup.get(author_key(email))
                if matched:
                    name = matched.name
                    profile_slug = profile_slug or matched.profile_slug
            if email in known_emails:
                continue
            current_members.append({"email": email, "name": name or email, "profile_slug": profile_slug})
            known_emails.add(email)

        source_parts = split_author_parts(item.get("author_text", "") or item.get("author", ""))
        remaining_parts: list[str] = []
        for part in source_parts:
            member = lookup.get(author_key(part)) or lookup.get(slugify(part))
            if member:
                if member.email not in known_emails:
                    current_members.append(
                        {"email": member.email, "name": member.name, "profile_slug": member.profile_slug}
                    )
                    known_emails.add(member.email)
                    changed = True
                continue
            remaining_parts.append(part)

        next_author_text = str(item.get("author_text", "")).strip()
        if not next_author_text and remaining_parts:
            next_author_text = ", ".join(remaining_parts)
            changed = True
        next_author = compose_article_author(next_author_text, current_members)
        next_article_id = str(item.get("article_id", "")).strip() or str(item.get("slug", "")).strip() or str(item.get("id", "")).strip()
        normalized_members = sorted(
            current_members,
            key=lambda member: (str(member.get("name", "")).casefold(), str(member.get("email", "")).casefold()),
        )
        existing_members = sorted(
            [
                {
                    "email": str(member.get("email", "")).strip().lower(),
                    "name": str(member.get("name", "")).strip(),
                    "profile_slug": str(member.get("profile_slug", "")).strip(),
                }
                for member in (item.get("author_members", []) if isinstance(item.get("author_members", []), list) else [])
                if isinstance(member, dict) and str(member.get("email", "")).strip()
            ],
            key=lambda member: (str(member.get("name", "")).casefold(), str(member.get("email", "")).casefold()),
        )
        if (
            str(item.get("author_text", "")).strip() != next_author_text
            or str(item.get("author", "")).strip() != next_author
            or str(item.get("article_id", "")).strip() != next_article_id
            or existing_members != normalized_members
        ):
            item["author_text"] = next_author_text
            item["author"] = next_author
            item["author_members"] = current_members
            item["article_id"] = next_article_id
            changed = True

    if changed:
        write_json_file(SUBMISSIONS_FILE, raw)


def sync_member_article_links(articles: list[Article]) -> None:
    raw = read_json_file(MEMBERS_FILE, {})
    source = raw.get("members", raw) if isinstance(raw, dict) else {}
    if not isinstance(source, dict):
        return

    linked_by_email: dict[str, list[dict[str, str]]] = {}
    for article in articles:
        linked_entry = {
            "article_id": str(article.article_id or article.slug).strip(),
            "title": str(article.title).strip(),
            "slug": str(article.slug).strip(),
            "url": published_article_path(article),
        }
        for member in (article.author_members or []):
            email = str(member.get("email", "")).strip().lower()
            if not email:
                continue
            bucket = linked_by_email.setdefault(email, [])
            if not any(item["article_id"] == linked_entry["article_id"] for item in bucket):
                bucket.append(dict(linked_entry))

    changed = False
    for key, item in source.items():
        if not isinstance(item, dict):
            continue
        email = str(item.get("email", key)).strip().lower()
        expected = sorted(linked_by_email.get(email, []), key=lambda entry: (entry["title"].casefold(), entry["article_id"]))
        current = item.get("linked_articles", [])
        current_normalized = []
        if isinstance(current, list):
            for link in current:
                if not isinstance(link, dict):
                    continue
                current_normalized.append(
                    {
                        "article_id": str(link.get("article_id", "")).strip(),
                        "title": str(link.get("title", "")).strip(),
                        "slug": str(link.get("slug", "")).strip(),
                        "url": str(link.get("url", "")).strip(),
                    }
                )
        if current_normalized != expected:
            item["linked_articles"] = expected
            changed = True

    if changed:
        payload = {"members": source} if isinstance(raw, dict) and "members" in raw else source
        MEMBERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_csv_list(raw: object) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, (list, tuple, set)):
        chunks = [normalize_text_value(str(item)) for item in raw]
    else:
        chunks = normalize_text_value(str(raw)).replace(";", ",").replace("\n", ",").split(",")

    items: list[str] = []
    for chunk in chunks:
        value = " ".join(chunk.strip().split())
        if value and value not in items:
            items.append(value)
    return items


def normalize_hashtags(values: list[str]) -> list[str]:
    hashtags: list[str] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        if text.startswith("#"):
            text = text[1:]
        normalized = slugify(text)
        if normalized:
            tag = f"#{normalized}"
            if tag not in hashtags:
                hashtags.append(tag)
    return hashtags


def infer_categories(title: str, slug: str, lead: str) -> list[str]:
    haystack = " ".join([title, slug.replace("-", " "), lead]).casefold()
    matches: list[str] = []

    def add(category: str) -> None:
        if category not in matches:
            matches.append(category)

    if "editorial" in haystack:
        add("Editoriais")
    if "entrevista" in haystack:
        add("Entrevistas")
    if any(token in haystack for token in ["econom", "critica economica", "politica economica"]):
        add("Política e Crítica Econômica")
    if any(token in haystack for token in ["ideologia", "arte", "cultura"]):
        add("Ideologia, Arte e Cultura")
    if any(token in haystack for token in ["traducao", "traduz", "tradutor", "traducoes"]):
        add("Traduções")
    if "teoria em movimento" in haystack:
        add("Teoria em Movimento")
    if any(token in haystack for token in ["poema", "conto", "literario", "literatura", "ficcao"]):
        add("Textos literários")

    return matches or [DEFAULT_CATEGORY]


def parse_categories(raw: object, *, title: str = "", slug: str = "", lead: str = "") -> list[str]:
    items = parse_csv_list(raw)
    categories = [item for item in items if item in CATEGORY_OPTIONS]
    if categories:
        return categories
    return infer_categories(title, slug, lead)


def format_long_date(moment: datetime) -> str:
    months = [
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    return f"{moment.day:02d} de {months[moment.month - 1]} de {moment.year}"


def page_path_from_root(root_prefix: str, local_path: str) -> str:
    prefix = str(root_prefix or "").replace("\\", "/")
    path = str(local_path or "").replace("\\", "/")
    while prefix.startswith("../"):
        prefix = prefix[3:]
    while path.startswith("../"):
        path = path[3:]
    return (prefix + path).lstrip("./")


def absolute_site_url(path_from_root: str) -> str:
    clean = "/" + str(path_from_root or "").lstrip("/")
    if not SITE_PUBLIC_URL:
        return clean
    return f"{SITE_PUBLIC_URL}{clean}"


def seo_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def read_core_metadata(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        raw = archive.read("docProps/core.xml")
    except KeyError:
        return {}

    root = ET.fromstring(raw)
    metadata: dict[str, str] = {}
    for field, selector in {
        "title": "dc:title",
        "creator": "dc:creator",
        "description": "dc:description",
        "subject": "dc:subject",
    }.items():
        node = root.find(selector, CORE_NS)
        if node is not None and node.text:
            metadata[field] = normalize_text_value(" ".join(node.text.split()))
    return metadata


def xml_tag_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def word_property_enabled(node: ET.Element | None) -> bool:
    if node is None:
        return False
    val = node.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "true")
    return str(val).lower() not in {"false", "0", "off", "none"}


def compact_whitespace(value: str) -> str:
    return normalize_text_value(re.sub(r"[ \t]+", " ", value)).strip()


def wrap_inline_html(text: str, *, bold: bool = False, italic: bool = False) -> str:
    html = text
    if bold:
        html = f"<strong>{html}</strong>"
    if italic:
        html = f"<em>{html}</em>"
    return html


def make_paragraph_block(text: str, html: str = "", *, align: str = "left") -> Block:
    plain = compact_whitespace(text)
    rich_html = html.strip() or escape_with_breaks(plain)
    return Block(kind="paragraph", text=plain, html=rich_html, align=align)


def reference_heading_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def is_reference_heading(text: str) -> bool:
    key = reference_heading_key(text)
    return key in {
        "referencias",
        "referencias bibliograficas",
        "bibliografia",
        "obras citadas",
    }


def is_reference_style(style_name: str) -> bool:
    normalized = style_name.casefold().replace(" ", "")
    return any(token in normalized for token in {"bibliography", "bibliografia", "referencia", "reference"})


def paragraph_content(
    paragraph: ET.Element,
    *,
    footnotes: dict[str, tuple[str, str]] | None = None,
    footnote_order: list[str] | None = None,
    footnote_numbers: dict[str, int] | None = None,
    inline_images: dict[str, str] | None = None,
) -> tuple[str, str]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    for run in paragraph.findall("./w:r", WORD_NS):
        bold = word_property_enabled(run.find("./w:rPr/w:b", WORD_NS))
        italic = word_property_enabled(run.find("./w:rPr/w:i", WORD_NS))
        run_text_parts: list[str] = []
        run_html_parts: list[str] = []

        for node in run:
            tag_name = xml_tag_name(node.tag)
            if tag_name == "rPr":
                continue
            if tag_name == "t":
                chunk = normalize_text_value(node.text or "")
                if chunk:
                    run_text_parts.append(chunk)
                    run_html_parts.append(escape(chunk))
            elif tag_name == "tab":
                run_text_parts.append(" ")
                run_html_parts.append(" ")
            elif tag_name in {"br", "cr"}:
                run_text_parts.append("\n")
                run_html_parts.append("<br>")
            elif tag_name == "footnoteReference" and footnotes is not None:
                footnote_id = node.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id", "")
                if not footnote_id or footnote_id not in footnotes:
                    continue
                if footnote_numbers is None or footnote_order is None:
                    continue
                if footnote_id not in footnote_numbers:
                    footnote_numbers[footnote_id] = len(footnote_order) + 1
                    footnote_order.append(footnote_id)
                marker = f"[{footnote_numbers[footnote_id]}]"
                run_text_parts.append(marker)
                run_html_parts.append(f"<sup>{escape(marker)}</sup>")

        run_text = "".join(run_text_parts)
        run_html = "".join(run_html_parts)
        if run_html:
            html_parts.append(wrap_inline_html(run_html, bold=bold, italic=italic))
        if run_text:
            text_parts.append(run_text)

    if not text_parts and not html_parts:
        for node in paragraph.iter():
            tag_name = xml_tag_name(node.tag)
            if tag_name == "t" and node.text:
                value = normalize_text_value(node.text)
                text_parts.append(value)
                html_parts.append(escape(value))

    if inline_images:
        image_ids = []
        for blip in paragraph.findall(".//a:blip", DOCX_DRAWING_NS):
            image_id = blip.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", "")
            if image_id and image_id not in image_ids:
                image_ids.append(image_id)
        for image_id in image_ids:
            image_name = inline_images.get(image_id, "").strip()
            if not image_name:
                continue
            html_parts.append(f'<img class="article-inline-image" src="/uploads/{escape(image_name)}" alt="Imagem do documento">')
            if not text_parts:
                text_parts.append("[Imagem]")

    plain_text = compact_whitespace("".join(text_parts).replace("\r", "\n"))
    rich_html = "".join(html_parts).strip()
    rich_html = re.sub(r"(?:<br>\s*){3,}", "<br><br>", rich_html).strip()
    if not plain_text:
        return "", ""
    return plain_text, (rich_html or escape_with_breaks(plain_text))


def read_docx_footnotes(archive: zipfile.ZipFile) -> dict[str, tuple[str, str]]:
    try:
        raw = archive.read("word/footnotes.xml")
    except KeyError:
        return {}

    root = ET.fromstring(raw)
    footnotes: dict[str, tuple[str, str]] = {}
    for note in root.findall("./w:footnote", WORD_NS):
        footnote_id = note.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id", "")
        note_type = note.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type", "")
        if not footnote_id or footnote_id.startswith("-") or note_type in {"separator", "continuationSeparator"}:
            continue

        text_parts: list[str] = []
        html_parts: list[str] = []
        for paragraph in note.findall("./w:p", WORD_NS):
            text, html = paragraph_content(paragraph)
            if not text:
                continue
            text_parts.append(text)
            html_parts.append(html)

        if text_parts:
            footnotes[footnote_id] = (" ".join(text_parts).strip(), "<br>".join(html_parts).strip())
    return footnotes


def blocks_to_sidecar(blocks: list[Block]) -> list[dict[str, object]]:
    return [
        {
            "kind": block.kind,
            "text": block.text,
            "level": block.level,
            "html": block.html,
        }
        for block in blocks
    ]


def blocks_from_sidecar(raw: object) -> list[Block]:
    if not isinstance(raw, list):
        return []

    blocks: list[Block] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "paragraph")).strip() or "paragraph"
        text = compact_whitespace(str(item.get("text", "")))
        if not text:
            continue
        level = int(item.get("level", 0) or 0)
        html = str(item.get("html", "")).strip()
        align = str(item.get("align", "left") or "left").strip() or "left"
        blocks.append(Block(kind=kind, text=text, level=level, html=html, align=align))
    return blocks


def extract_docx_inline_images(archive: zipfile.ZipFile, slug: str) -> dict[str, str]:
    try:
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    except KeyError:
        return {}

    mapping: dict[str, str] = {}
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    counter = 1
    for node in relationships.findall(".//{*}Relationship"):
        rel_id = str(node.attrib.get("Id", "")).strip()
        target = str(node.attrib.get("Target", "")).strip()
        if not rel_id or "media/" not in target:
            continue
        source = f"word/{target.lstrip('/')}"
        try:
            data = archive.read(source)
        except KeyError:
            continue
        suffix = Path(target).suffix.lower() or ".png"
        filename = f"{slug}-inline-{counter}{suffix}"
        (UPLOADS_DIR / filename).write_bytes(data)
        mapping[rel_id] = filename
        counter += 1
    return mapping


def read_docx_blocks(path: Path) -> tuple[list[Block], dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        metadata = read_core_metadata(archive)
        footnotes = read_docx_footnotes(archive)
        inline_images = extract_docx_inline_images(archive, path.stem)

    blocks: list[Block] = []
    bibliography_blocks: list[Block] = []
    reference_section_started = False
    footnote_order: list[str] = []
    footnote_numbers: dict[str, int] = {}

    for paragraph in document.findall("./w:body/w:p", WORD_NS):
        text, html = paragraph_content(
            paragraph,
            footnotes=footnotes,
            footnote_order=footnote_order,
            footnote_numbers=footnote_numbers,
            inline_images=inline_images,
        )
        if not text:
            continue

        style_node = paragraph.find("./w:pPr/w:pStyle", WORD_NS)
        style_name = ""
        if style_node is not None:
            style_name = style_node.attrib.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val",
                "",
            )

        normalized_style = style_name.lower().replace(" ", "")
        if is_reference_heading(text):
            reference_section_started = True
            continue

        if reference_section_started or is_reference_style(style_name):
            bibliography_blocks.append(make_paragraph_block(text, html))
            continue

        if normalized_style in {"title", "heading1"}:
            blocks.append(Block(kind="heading", text=text, level=1))
        elif normalized_style == "heading2":
            blocks.append(Block(kind="heading", text=text, level=2))
        elif normalized_style in {"heading3", "heading4"}:
            blocks.append(Block(kind="heading", text=text, level=3))
        else:
            blocks.append(make_paragraph_block(text, html))

    if footnote_order:
        blocks.append(Block(kind="heading", text="Notas de rodapé", level=2))
        for footnote_id in footnote_order:
            marker = f"[{footnote_numbers[footnote_id]}]"
            note_text, note_html = footnotes[footnote_id]
            blocks.append(make_paragraph_block(f"{marker} {note_text}", f"<strong>{escape(marker)}</strong> {note_html}"))

    if bibliography_blocks:
        blocks.append(Block(kind="heading", text="Referências bibliográficas", level=2))
        blocks.extend(bibliography_blocks)

    return blocks, metadata


def summarize(text: str, max_words: int = 34) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,.;:") + "..."


def load_sidecar_metadata(path: Path) -> dict[str, object]:
    sidecar_file = sidecar_path(path)
    if not sidecar_file.exists():
        return {}

    try:
        return normalize_loaded_value(json.loads(sidecar_file.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {}


def load_monthly_read_counts(target_month: str | None = None) -> dict[str, int]:
    month_key = target_month or datetime.now().strftime("%Y-%m")
    if not STATS_FILE.exists():
        return {}
    try:
        raw = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    source = raw.get("articles", {}) if isinstance(raw, dict) else {}
    if not isinstance(source, dict):
        return {}

    counts: dict[str, int] = {}
    for slug, entry in source.items():
        if not isinstance(entry, dict):
            continue
        total = 0
        daily = entry.get("daily", {})
        if isinstance(daily, dict):
            for day_key, day_entry in daily.items():
                if not str(day_key).startswith(month_key):
                    continue
                if isinstance(day_entry, dict):
                    total += int(day_entry.get("views", 0) or 0)
        counts[str(slug)] = total
    return counts


def resolve_image(sidecar_data: dict[str, object], fallback_title: str) -> tuple[str, str, str, str]:
    image_file = str(sidecar_data.get("image_file", "")).strip()
    image_scope = str(sidecar_data.get("image_scope", "")).strip() or "assets"
    image_alt = str(sidecar_data.get("image_alt", "")).strip() or fallback_title
    image_caption = str(sidecar_data.get("image_caption", "")).strip() or fallback_title

    if image_scope == "uploads" and image_file and (UPLOADS_DIR / image_file).exists():
        return image_scope, image_file, image_alt, image_caption

    return "assets", DEFAULT_IMAGE_FILE, "Logo da Revista Barravento", "Imagem padrao da revista."


def strip_inline_markup(value: str) -> str:
    text = value.replace("**", "").replace("*", "")
    return compact_whitespace(text)


def editor_markup_to_html(value: str) -> str:
    html = escape(value)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html, flags=re.DOTALL)
    html = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", html, flags=re.DOTALL)
    html = re.sub(r"\[(\d+)\]", r"<sup>[\1]</sup>", html)
    return html.replace("\n", "<br>").strip()


def rich_html_to_editor_markup(value: str) -> str:
    markup = value.strip()
    markup = re.sub(r"<br\s*/?>", "\n", markup, flags=re.IGNORECASE)
    markup = re.sub(r"<sup>\s*(\[[^\]]+\])\s*</sup>", r"\1", markup, flags=re.IGNORECASE)
    markup = re.sub(r"<strong>(.*?)</strong>", r"**\1**", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(r"<b>(.*?)</b>", r"**\1**", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(r"<em>(.*?)</em>", r"*\1*", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(r"<i>(.*?)</i>", r"*\1*", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(r"<[^>]+>", "", markup)
    return unescape(markup).strip()


def blocks_to_editor_markup(blocks: list[Block]) -> str:
    chunks: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            prefix = "### " if block.level >= 3 else "## "
            chunks.append(f"{prefix}{block.text}")
            continue
        chunks.append(rich_html_to_editor_markup(block.html or escape_with_breaks(block.text)))
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


def editor_markup_to_blocks(value: str) -> list[Block]:
    normalized = normalize_text_value(value).replace("\r\n", "\n").strip()
    if not normalized:
        return []

    blocks: list[Block] = []
    for chunk in re.split(r"\n\s*\n", normalized):
        piece = chunk.strip()
        if not piece:
            continue
        if piece.startswith("### "):
            blocks.append(Block(kind="heading", text=compact_whitespace(piece[4:]), level=3))
            continue
        if piece.startswith("## "):
            blocks.append(Block(kind="heading", text=compact_whitespace(piece[3:]), level=2))
            continue
        if piece.startswith("# "):
            blocks.append(Block(kind="heading", text=compact_whitespace(piece[2:]), level=1))
            continue

        text = strip_inline_markup(piece.replace("\n", " "))
        html = editor_markup_to_html(piece)
        if text:
            blocks.append(make_paragraph_block(text, html))
    return blocks


def paragraph_html(block: Block) -> str:
    return block.html or escape_with_breaks(block.text)


def pdf_paragraph_text(value: str) -> str:
    html = value.replace("<strong>", "<b>").replace("</strong>", "</b>")
    html = html.replace("<em>", "<i>").replace("</em>", "</i>")
    html = re.sub(r"<br\s*>", "<br/>", html, flags=re.IGNORECASE)
    html = re.sub(r"<img\b[^>]*>", "[Imagem]", html, flags=re.IGNORECASE)
    return html


def extract_article(path: Path) -> Article:
    sidecar_data = load_sidecar_metadata(path)
    sidecar_blocks = blocks_from_sidecar(sidecar_data.get("body_blocks"))
    if sidecar_blocks:
        blocks = sidecar_blocks
        core_metadata: dict[str, str] = {}
    else:
        blocks, core_metadata = read_docx_blocks(path)

    if not blocks:
        fallback = path.stem.replace("_", " ") or "Documento sem conteudo."
        blocks = [make_paragraph_block(fallback)]

    body_blocks = list(blocks)
    title = str(sidecar_data.get("title", "")).strip() or core_metadata.get("title", "")
    if not title:
        title_index = next(
            (index for index, block in enumerate(body_blocks) if block.kind == "heading"),
            0,
        )
        title = body_blocks[title_index].text
        del body_blocks[title_index]
    elif body_blocks and body_blocks[0].text.strip() == title.strip():
        del body_blocks[0]

    author = str(sidecar_data.get("author", "")).strip() or core_metadata.get("creator", "").strip()
    author_text = str(sidecar_data.get("author_text", "")).strip()
    if body_blocks:
        lower = body_blocks[0].text.lower()
        if lower.startswith("por ") or lower.startswith("por:"):
            extracted_author = (
                body_blocks[0]
                .text.replace("Por:", "")
                .replace("por:", "")
                .replace("Por ", "")
                .replace("por ", "")
                .strip()
            )
            author = author or extracted_author
            del body_blocks[0]
        elif author and body_blocks[0].text.strip().lower() == author.lower():
            del body_blocks[0]

    author = author or "Redacao"
    if not author_text and not (sidecar_data.get("author_members") or []):
        author_text = author
    lead = next((block.text for block in body_blocks if block.kind == "paragraph"), "")
    summary = (
        str(sidecar_data.get("summary", "")).strip()
        or core_metadata.get("description", "")
        or summarize(lead or title)
    )
    if not lead:
        lead = summary
    if not body_blocks:
        body_blocks = [make_paragraph_block(summary)]

    categories = parse_categories(
        sidecar_data.get("categories") or sidecar_data.get("category") or core_metadata.get("subject"),
        title=title,
        slug=path.stem,
        lead=lead,
    )

    word_count = sum(len(block.text.split()) for block in body_blocks if block.kind == "paragraph")
    reading_time = max(1, math.ceil(word_count / 220))
    image_scope, image_file, image_alt, image_caption = resolve_image(sidecar_data, title)
    tags = parse_csv_list(sidecar_data.get("tags"))
    hashtags = normalize_hashtags(parse_csv_list(sidecar_data.get("hashtags")))
    raw_author_members = sidecar_data.get("author_members")
    author_members = [
        {
            "email": str(item.get("email", "")).strip().lower(),
            "name": str(item.get("name", "")).strip(),
            "profile_slug": slugify(str(item.get("profile_slug", "")).strip() or str(item.get("name", "")).strip()),
        }
        for item in (raw_author_members if isinstance(raw_author_members, list) else [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]

    stat = path.stat()
    created_at = (
        parse_stored_datetime(sidecar_data.get("created_at"))
        or datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime))
    )
    updated_at = (
        parse_stored_datetime(sidecar_data.get("updated_at"))
        or datetime.fromtimestamp(stat.st_mtime)
    )

    return Article(
        article_id=str(sidecar_data.get("article_id", "")).strip() or path.stem,
        slug=path.stem,
        title=title,
        author=compose_article_author(author_text, author_members) if (author_text or author_members) else author,
        author_text=author_text,
        categories=categories,
        summary=summary,
        lead=lead,
        reading_time=reading_time,
        published_at=created_at,
        updated_at=updated_at,
        source_name=path.name,
        image_scope=image_scope,
        image_file=image_file,
        image_alt=image_alt,
        image_caption=image_caption,
        tags=tags,
        hashtags=hashtags,
        blocks=body_blocks,
        body_html=str(sidecar_data.get("body_html", "")).strip() or blocks_to_rich_editor_html(body_blocks),
        author_members=author_members,
    )


def json_for_script(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def escape_with_breaks(text: str) -> str:
    return "<br>".join(escape(part) for part in text.split("\n"))


def image_src(article: Article, root_prefix: str) -> str:
    return f"{root_prefix}{article.image_scope}/{escape(article.image_file)}"


def category_page_href(category: str, root_prefix: str) -> str:
    return f"{root_prefix}categorias/{slugify(category)}/"


def article_href(article: Article, root_prefix: str) -> str:
    return f"{root_prefix}artigos/{escape(article.slug)}/"


def pdf_href(article: Article, root_prefix: str) -> str:
    return f"{root_prefix}pdfs/{escape(article.slug)}.pdf"


def profile_href(profile_slug: str, root_prefix: str) -> str:
    return f"{root_prefix}perfis/{escape(profile_slug)}/"


def article_author_links(article: Article, root_prefix: str) -> str:
    return escape(article.author or "Redacao")


def published_article_path(article: Article) -> str:
    return f"/artigos/{article.slug}/"


def page_links(root_prefix: str) -> dict[str, str]:
    return {
        "home": f"{root_prefix}index.html",
        "publish": f"{root_prefix}painel/#member-panel",
        "members": f"{root_prefix}membros/",
        "members_login": f"{root_prefix}membros/",
        "members_panel": f"{root_prefix}painel/#member-panel",
        "search": f"{root_prefix}busca/",
        "who": f"{root_prefix}quem-somos/",
        "contact": f"{root_prefix}contato/",
        "cookies": f"{root_prefix}politica-de-cookies/",
        "logo": site_logo_href(root_prefix),
        "symbol": site_symbol_href(root_prefix),
    }


def root_prefix_from_page_path(page_path: str) -> str:
    parts = [part for part in str(page_path or "").split("/") if part]
    if parts and parts[-1].lower().endswith(".html"):
        parts = parts[:-1]
    return "../" * len(parts)


def render_member_nav_script() -> str:
    return """  <script>
    (() => {
      const panelStateKey = "barravento-member-last-session";
      const link = document.querySelector(".topline__member-link[data-login-href][data-panel-href]");
      const state = document.querySelector(".topline__member-state");
      if (!link) {
        return;
      }

      const loginHref = link.dataset.loginHref || link.getAttribute("href") || "";
      const panelHref = link.dataset.panelHref || loginHref;

      function apply(authenticated, member) {
        if (authenticated && member) {
          link.textContent = member.email || "Membros";
          link.href = panelHref;
          link.classList.add("is-authenticated");
          if (state) {
            state.hidden = false;
            state.textContent = "Logado";
            state.title = member.email || member.role_label || "";
          }
          return;
        }

        link.textContent = "Membros";
        link.href = loginHref;
        link.classList.remove("is-authenticated");
        if (state) {
          state.hidden = true;
          state.textContent = "";
          state.removeAttribute("title");
        }
      }

      apply(false, null);
      if (window.location.protocol === "file:") {
        return;
      }

      fetch("/api/members/session", { credentials: "same-origin" })
        .then((response) => response.json().catch(() => ({})))
        .then((payload) => {
          const authenticated = Boolean(payload && payload.authenticated);
          apply(authenticated, authenticated && payload ? payload.member : null);
          if (!authenticated) {
            try {
              localStorage.removeItem(panelStateKey);
            } catch (error) {
              return;
            }
          }
        })
        .catch(() => {
          apply(false, null);
          try {
            localStorage.removeItem(panelStateKey);
          } catch (error) {
            return;
          }
        });
    })();
  </script>
"""


def render_cookie_consent_markup(root_prefix: str) -> str:
    links = page_links(root_prefix)
    policy_link = links["cookies"]
    support_link = links["contact"]
    return f"""
  <a class="support-button" href="{support_link}">Apoia-se</a>
  <section class="cookie-banner" data-cookie-banner hidden aria-live="polite">
    <div class="cookie-banner__inner">
      <div class="cookie-banner__copy">
        <strong>Cookies e tecnologias semelhantes</strong>
        <p>Usamos um cookie necessario para a area de membros e recurso opcional de desempenho para leituras e mais lidos. Os opcionais ficam desligados por padrao.</p>
        <a href="{policy_link}">Ler a Politica de Cookies</a>
      </div>
      <div class="cookie-banner__actions">
        <button class="button-link button-link--ghost" type="button" data-cookie-reject>Rejeitar opcionais</button>
        <button class="button-link" type="button" data-cookie-accept>Aceitar opcionais</button>
      </div>
    </div>
  </section>
"""


def render_footer(root_prefix: str) -> str:
    links = page_links(root_prefix)
    return f"""
    <footer class="site-footer">
      <div class="container site-footer__inner">
        <p class="site-footer__copy">Revista Barravento.</p>
        <nav class="site-footer__nav" aria-label="Rodape">
          <a href="{links['who']}">Quem Somos</a>
          <a href="{links['contact']}">Contato</a>
          <a href="{links['cookies']}">Politica de Cookies</a>
        </nav>
      </div>
    </footer>
"""


def render_cookie_consent_script(root_prefix: str) -> str:
    policy_link = json.dumps(page_links(root_prefix)["cookies"])
    return f"""  <script>
    (() => {{
      const consentKey = "barravento-cookie-preferences";
      const performanceKeys = ["barravento-read-counts", "barravento-read-counts-monthly"];
      const performancePrefixes = ["barravento-read-stamp:"];
      const policyLink = {policy_link};
      const banner = document.querySelector("[data-cookie-banner]");
      const openButton = document.querySelector("[data-cookie-open]");

      function defaults() {{
        return {{
          necessary: true,
          performance: false,
          decided: false,
          updated_at: ""
        }};
      }}

      function readPreferences() {{
        try {{
          const stored = JSON.parse(localStorage.getItem(consentKey) || "null");
          if (!stored || typeof stored !== "object") {{
            return defaults();
          }}
          return {{
            necessary: true,
            performance: Boolean(stored.performance),
            decided: Boolean(stored.decided),
            updated_at: String(stored.updated_at || "")
          }};
        }} catch (error) {{
          return defaults();
        }}
      }}

      function clearPerformanceStorage() {{
        try {{
          performanceKeys.forEach((key) => localStorage.removeItem(key));
          const keysToRemove = [];
          for (let index = 0; index < localStorage.length; index += 1) {{
            const key = localStorage.key(index) || "";
            if (performancePrefixes.some((prefix) => key.startsWith(prefix))) {{
              keysToRemove.push(key);
            }}
          }}
          keysToRemove.forEach((key) => localStorage.removeItem(key));
        }} catch (error) {{
          return;
        }}
      }}

      function storePreferences(next) {{
        const payload = {{
          necessary: true,
          performance: Boolean(next && next.performance),
          decided: true,
          updated_at: new Date().toISOString()
        }};
        try {{
          localStorage.setItem(consentKey, JSON.stringify(payload));
        }} catch (error) {{
          return payload;
        }}
        if (!payload.performance) {{
          clearPerformanceStorage();
        }}
        return payload;
      }}

      function applyPreferences(prefs) {{
        if (banner) {{
          banner.hidden = Boolean(prefs.decided);
        }}
        document.body.dataset.cookieDecision = prefs.decided ? "set" : "pending";
        document.body.dataset.cookiePerformance = prefs.performance ? "granted" : "denied";
      }}

      function emitPreferences(prefs) {{
        window.dispatchEvent(new CustomEvent("barravento:consent-changed", {{ detail: prefs }}));
      }}

      window.BarraventoConsent = {{
        getPreferences: readPreferences,
        hasPerformanceConsent() {{
          return Boolean(readPreferences().performance);
        }}
      }};

      const initial = readPreferences();
      applyPreferences(initial);

      const acceptButton = document.querySelector("[data-cookie-accept]");
      const rejectButton = document.querySelector("[data-cookie-reject]");

      if (acceptButton) {{
        acceptButton.addEventListener("click", () => {{
          const prefs = storePreferences({{ performance: true }});
          applyPreferences(prefs);
          emitPreferences(prefs);
        }});
      }}

      if (rejectButton) {{
        rejectButton.addEventListener("click", () => {{
          const prefs = storePreferences({{ performance: false }});
          applyPreferences(prefs);
          emitPreferences(prefs);
        }});
      }}

    }})();
  </script>
"""


def render_shell(
    *,
    page_title: str,
    description: str,
    css_path: str,
    icon_path: str,
    body_class: str,
    content: str,
    page_path: str = "",
    seo_type: str = "website",
    keywords: list[str] | None = None,
    image_path: str = DEFAULT_SOCIAL_IMAGE,
    seo_json_ld: list[dict[str, object]] | None = None,
    robots_content: str = "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1",
) -> str:
    canonical_url = absolute_site_url(page_path)
    social_image_url = absolute_site_url(page_path_from_root("", image_path))
    root_prefix = root_prefix_from_page_path(page_path)
    keywords_content = ", ".join(
        item for item in ([SITE_NAME, "revista", "marxismo", "crítica", "artigos"] + (keywords or [])) if item
    )
    json_ld = "\n".join(
        f'  <script type="application/ld+json">{seo_json(item)}</script>'
        for item in (seo_json_ld or [])
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page_title)} | Revista Barravento</title>
  <meta name="description" content="{escape(description)}">
  <meta name="robots" content="{escape(robots_content)}">
  <meta name="keywords" content="{escape(keywords_content)}">
  <meta name="author" content="{SITE_NAME}">
  <link rel="canonical" href="{escape(canonical_url)}">
  <meta property="og:locale" content="pt_BR">
  <meta property="og:site_name" content="{SITE_NAME}">
  <meta property="og:type" content="{escape(seo_type)}">
  <meta property="og:title" content="{escape(page_title)} | {SITE_NAME}">
  <meta property="og:description" content="{escape(description)}">
  <meta property="og:url" content="{escape(canonical_url)}">
  <meta property="og:image" content="{escape(social_image_url)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{escape(page_title)} | {SITE_NAME}">
  <meta name="twitter:description" content="{escape(description)}">
  <meta name="twitter:image" content="{escape(social_image_url)}">
  <link rel="icon" href="{icon_path}">
  <link rel="stylesheet" href="{css_path}">
{json_ld}
</head>
<body class="{body_class}">
{render_cookie_consent_markup(root_prefix)}
{render_cookie_consent_script(root_prefix)}
  <div class="page">
{content}
{render_footer(root_prefix)}
  </div>
{render_member_nav_script()}
</body>
</html>
"""


def render_search_form(root_prefix: str) -> str:
    links = page_links(root_prefix)
    return f"""        <form class="header-search" action="{links['search']}" method="get">
          <label class="sr-only" for="site-search">Buscar</label>
          <input id="site-search" name="q" type="search" placeholder="Buscar textos, tags e categorias">
          <button type="submit">Buscar</button>
        </form>"""


def render_nav(root_prefix: str) -> str:
    links = page_links(root_prefix)
    category_links = "".join(
        f'<a class="menu-link" href="{category_page_href(category, root_prefix)}">{escape(category)}</a>'
        for category in CATEGORY_OPTIONS
    )
    return f"""{category_links}
          <a class="menu-link" href="{links['who']}">Quem Somos</a>
          <a class="menu-link" href="{links['contact']}">Contato</a>"""


def render_header(root_prefix: str, *, date_label: str) -> str:
    links = page_links(root_prefix)
    return f"""    <div class="topline">
      <div class="container topline__inner">
        <span>Revista</span>
        <div class="topline__member-area">
          <a class="topline__social-link" href="{INSTAGRAM_URL}" target="_blank" rel="noopener noreferrer">Instagram</a>
          <span class="topline__member-state" hidden></span>
          <a
            class="topline__member-link"
            href="{links['members_login']}"
            data-login-href="{links['members_login']}"
            data-panel-href="{links['members_panel']}"
          >Membros</a>
        </div>
      </div>
    </div>
    <header class="masthead">
      <div class="container masthead__top">
        <a class="masthead__brand" href="{links['home']}">
          <img class="masthead__symbol" src="{site_symbol_href(root_prefix)}" alt="Farol da Revista Barravento">
        </a>
{render_search_form(root_prefix)}
      </div>
      <div class="menu-strip">
        <div class="container">
          <nav class="menu-strip__nav" aria-label="Categorias e paginas">
            {render_nav(root_prefix)}
          </nav>
        </div>
      </div>
    </header>
"""


def render_category_badges(categories: list[str], root_prefix: str, *, klass: str = "category-badges") -> str:
    return f"""<div class="{klass}">
  {"".join(f'<a class="category-badge" href="{category_page_href(category, root_prefix)}">{escape(category)}</a>' for category in categories)}
</div>"""


def render_standard_card(article: Article, root_prefix: str) -> str:
    return f"""<article class="article-card">
  <a class="article-card__image" href="{article_href(article, root_prefix)}">
    <img src="{image_src(article, root_prefix)}" alt="{escape(article.image_alt)}">
  </a>
  <div class="article-card__body">
    {render_category_badges(article.categories, root_prefix)}
    <div class="meta-row">
      <span>{format_long_date(article.published_at)}</span>
      <span>{article.reading_time} min</span>
    </div>
    <h3><a href="{article_href(article, root_prefix)}">{escape(article.title)}</a></h3>
    <p>{escape(article.summary)}</p>
    <a class="article-card__link" href="{article_href(article, root_prefix)}">Ler texto</a>
  </div>
</article>"""


def render_compact_story(article: Article, root_prefix: str) -> str:
    return f"""<article class="story-mini">
  <a class="story-mini__image" href="{article_href(article, root_prefix)}">
    <img src="{image_src(article, root_prefix)}" alt="{escape(article.image_alt)}">
  </a>
  <div class="story-mini__body">
    <div class="meta-row">
      <span>{format_long_date(article.published_at)}</span>
      <span>{article.reading_time} min</span>
    </div>
    <h3><a href="{article_href(article, root_prefix)}">{escape(article.title)}</a></h3>
  </div>
</article>"""


def render_featured_story(article: Article) -> str:
    return f"""          <article class="feature-card">
            <a class="feature-card__image" href="{article_href(article, '')}">
              <img src="{image_src(article, '')}" alt="{escape(article.image_alt)}">
            </a>
            <div class="feature-card__body">
              {render_category_badges(article.categories, '')}
              <div class="meta-row">
                <span>{format_long_date(article.published_at)}</span>
                <span>{article.reading_time} min de leitura</span>
              </div>
              <h2><a href="{article_href(article, '')}">{escape(article.title)}</a></h2>
              <p>{escape(article.summary)}</p>
              <a class="article-card__link" href="{article_href(article, '')}">Abrir texto</a>
            </div>
          </article>"""


def render_featured_carousel(articles: list[Article]) -> str:
    featured_items = articles[:10]
    if not featured_items:
        return """          <div class="empty-state empty-state--feature">
            <h2>Nenhum texto publicado ainda</h2>
            <p>Use o <a href="painel/#member-panel">painel de membros</a> para criar o primeiro texto com imagem, categorias e tags.</p>
          </div>"""

    slides = []
    dots = []
    for index, article in enumerate(featured_items):
        active = " is-active" if index == 0 else ""
        slides.append(
            f"""            <article class="feature-card feature-card--slide{active}" data-feature-slide>
              <a class="feature-card__image" href="{article_href(article, '')}">
                <img src="{image_src(article, '')}" alt="{escape(article.image_alt)}">
              </a>
              <div class="feature-card__body">
                {render_category_badges(article.categories, '')}
                <div class="meta-row">
                  <span>{format_long_date(article.published_at)}</span>
                  <span>{article.reading_time} min de leitura</span>
                </div>
                <h2><a href="{article_href(article, '')}">{escape(article.title)}</a></h2>
                <p>{escape(article.summary)}</p>
                <a class="article-card__link" href="{article_href(article, '')}">Abrir texto</a>
              </div>
            </article>"""
        )
        dots.append(
            f"""            <button class="feature-carousel__dot{active}" type="button" data-feature-dot aria-label="Mostrar texto {index + 1}"></button>"""
        )

    return f"""          <section class="feature-carousel" data-feature-carousel>
            <button class="feature-carousel__arrow feature-carousel__arrow--prev" type="button" data-feature-prev aria-label="Mostrar texto anterior">&#8249;</button>
            <div class="feature-carousel__track">
{chr(10).join(slides)}
            </div>
            <button class="feature-carousel__arrow feature-carousel__arrow--next" type="button" data-feature-next aria-label="Mostrar proximo texto">&#8250;</button>
            <div class="feature-carousel__controls" aria-label="Ultimos textos criados">
{chr(10).join(dots)}
            </div>
          </section>"""


def render_most_read_item(article: Article) -> str:
    return f"""            <li class="most-read__item" data-most-read-item data-slug="{escape(article.slug)}">
              <a class="most-read__link" href="{article_href(article, '')}">{escape(article.title)}</a>
              <span class="most-read__meta">
                <span>{format_long_date(article.published_at)}</span>
              </span>
            </li>"""


def render_most_read_sidebar(articles: list[Article]) -> str:
    items = "\n".join(render_most_read_item(article) for article in articles[:5])
    if not items:
        items = """            <li class="most-read__item most-read__item--empty">
              <span class="most-read__link">Os textos publicados aparecerao aqui.</span>
            </li>"""

    return f"""          <aside class="home-note most-read" data-most-read-list>
            <span class="eyebrow">Mais lidos do mes</span>
            <h2>Textos mais lidos do mes</h2>
            <ol class="most-read__list">
{items}
            </ol>
          </aside>"""


def render_empty_compact(category: str) -> str:
    return f"""<div class="empty-state empty-state--compact">
  <h3>{escape(category)}</h3>
  <p>Os tres textos mais recentes desta editoria aparecerao aqui.</p>
</div>"""


def render_home_category_panel(category: str, articles: list[Article]) -> str:
    stories = articles[:3]
    body = "\n".join(render_compact_story(article, "") for article in stories) if stories else render_empty_compact(category)
    return f"""        <section class="category-panel">
          <div class="category-panel__head">
            <h2><a href="{category_page_href(category, '')}">{escape(category)}</a></h2>
            <a class="category-panel__link" href="{category_page_href(category, '')}">Ver todos</a>
          </div>
          <div class="category-panel__list">
{body}
          </div>
        </section>"""


def render_article_body(article: Article) -> str:
    if article.body_html.strip():
        return "\n".join(
            f"              {line}" if line.strip() else ""
            for line in article.body_html.strip().splitlines()
        )

    html_parts: list[str] = []
    first_paragraph = True
    for block in article.blocks:
        if block.kind == "heading":
            tag = "h2" if block.level <= 2 else "h3"
            html_parts.append(f'              <{tag} class="article-block--align-{escape(block.align)}">{escape(block.text)}</{tag}>')
            continue
        if block.kind == "divider":
            html_parts.append('              <hr class="article-divider">')
            continue
        if block.kind == "quote":
            inner = block.html or f"<p>{escape_with_breaks(block.text)}</p>"
            html_parts.append(f'              <blockquote class="article-quote article-block--align-{escape(block.align)}">{inner}</blockquote>')
            continue
        if block.kind == "list":
            if block.html:
                html_parts.append(f'              <div class="article-list article-block--align-{escape(block.align)}">{block.html}</div>')
                continue
            tag = "ol" if block.level > 0 else "ul"
            items = [item.strip() for item in block.text.split(" • ") if item.strip()]
            list_html = "".join(f"<li>{escape(item)}</li>" for item in items)
            html_parts.append(f'              <div class="article-list article-block--align-{escape(block.align)}"><{tag}>{list_html}</{tag}></div>')
            continue

        klass = ' class="article-lead article-block--align-%s"' % escape(block.align) if first_paragraph else ' class="article-block--align-%s"' % escape(block.align)
        html_parts.append(f"              <p{klass}>{paragraph_html(block)}</p>")
        first_paragraph = False
    return "\n".join(html_parts)


def render_tag_cloud(title: str, values: list[str], root_prefix: str = "") -> str:
    if not values:
        return ""
    return f"""            <section class="sidebar-card">
              <h3>{escape(title)}</h3>
              <div class="tag-list">
                {''.join(f'<a class="tag" href="{root_prefix}busca/?q={quote_plus(item)}" aria-label="Buscar por {escape(item)}">{escape(item)}</a>' for item in values)}
              </div>
            </section>
"""


def render_home_tag_mosaic(articles: list[Article]) -> str:
    counts: dict[str, int] = {}
    for article in articles:
        for value in [*article.tags, *article.hashtags]:
            tag = str(value or "").strip()
            if not tag:
                continue
            counts[tag] = counts.get(tag, 0) + 1

    if not counts:
        return ""

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    max_count = max(counts.values()) or 1
    min_count = min(counts.values()) or 1
    spread = max(1, max_count - min_count)

    links: list[str] = []
    for tag, count in ranked:
        size = 1 + round(((count - min_count) / spread) * 4)
        size = max(1, min(5, size))
        links.append(
            f'<a class="tag-mosaic__link tag-mosaic__link--size-{size}" href="busca/?q={quote_plus(tag)}" '
            f'title="{escape(tag)} aparece em {count} texto{"s" if count != 1 else ""}" '
            f'aria-label="{escape(tag)} aparece em {count} texto{"s" if count != 1 else ""}. Abrir busca.">'
            f"{escape(tag)}"
            f'<span class="tag-mosaic__count">{count}</span>'
            f"</a>"
        )

    return f"""        <section class="category-panel category-panel--tags">
          <div class="category-panel__head">
            <h2>Tags</h2>
            <span class="category-panel__link">Temas recorrentes</span>
          </div>
          <div class="tag-mosaic" aria-label="Mosaico de tags recorrentes">
            {"".join(links)}
          </div>
        </section>"""


def font_candidates(*names: str) -> list[Path]:
    fonts_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    return [fonts_dir / name for name in names]


def resolve_pdf_font(alias: str, fallback: str, *candidates: str) -> str:
    if alias in pdfmetrics.getRegisteredFontNames():
        return alias

    for candidate in font_candidates(*candidates):
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont(alias, str(candidate)))
                return alias
            except Exception:
                continue
    return fallback


def resolve_pdf_font_path(alias: str, fallback: str, *candidates: Path) -> str:
    if alias in pdfmetrics.getRegisteredFontNames():
        return alias

    for candidate in candidates:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont(alias, str(candidate)))
                return alias
            except Exception:
                continue
    return fallback


def pdf_font_map() -> dict[str, str]:
    return {
        "serif": resolve_pdf_font("BarraventoSerif", "Times-Roman", "georgia.ttf", "times.ttf"),
        "serif_bold": resolve_pdf_font("BarraventoSerifBold", "Times-Bold", "georgiab.ttf", "timesbd.ttf"),
        "sans": resolve_pdf_font("BarraventoSans", "Helvetica", "arial.ttf", "calibri.ttf"),
        "sans_bold": resolve_pdf_font("BarraventoSansBold", "Helvetica-Bold", "arialbd.ttf", "calibrib.ttf"),
        "brand": resolve_pdf_font_path("BarraventoBrand", "Helvetica-Bold", SITE_BRAND_FONT_SOURCE),
    }


def pdf_styles() -> dict[str, ParagraphStyle]:
    fonts = pdf_font_map()
    return {
        "brand_title": ParagraphStyle(
            "PdfBrandTitle",
            fontName=fonts["brand"],
            fontSize=25,
            leading=24,
            textColor=PDF_ACCENT,
            spaceAfter=4 * mm,
        ),
        "header_title": ParagraphStyle(
            "PdfHeaderTitle",
            fontName=fonts["serif_bold"],
            fontSize=24,
            leading=28,
            textColor=PDF_TEXT,
            spaceAfter=3 * mm,
        ),
        "meta": ParagraphStyle(
            "PdfMeta",
            fontName=fonts["sans"],
            fontSize=9.5,
            leading=13,
            textColor=PDF_MUTED,
            spaceAfter=1.4 * mm,
        ),
        "lead": ParagraphStyle(
            "PdfLead",
            fontName=fonts["serif"],
            fontSize=14.2,
            leading=24,
            alignment=TA_JUSTIFY,
            textColor=PDF_TEXT,
            spaceAfter=5.5 * mm,
        ),
        "body": ParagraphStyle(
            "PdfBody",
            fontName=fonts["serif"],
            fontSize=12.8,
            leading=22,
            alignment=TA_JUSTIFY,
            textColor=PDF_TEXT,
            spaceAfter=5 * mm,
        ),
        "heading": ParagraphStyle(
            "PdfHeading",
            fontName=fonts["sans_bold"],
            fontSize=10.2,
            leading=14,
            alignment=TA_LEFT,
            textColor=PDF_ACCENT,
            spaceBefore=7 * mm,
            spaceAfter=2.6 * mm,
        ),
    }


def site_logo_filename() -> str:
    if (ROOT / SITE_LOGO_FILE).exists():
        return SITE_LOGO_FILE
    return DEFAULT_IMAGE_FILE


def site_logo_href(root_prefix: str) -> str:
    return f"{root_prefix}assets/{site_logo_filename()}"


def site_symbol_href(root_prefix: str) -> str:
    symbol_file = SITE_SYMBOL_FILE if (ROOT / SITE_SYMBOL_FILE).exists() else DEFAULT_IMAGE_FILE
    return f"{root_prefix}assets/{symbol_file}"


def build_pdf_header(article: Article, published: str, article_link_label: str, article_link_target: str) -> KeepTogether:
    styles = pdf_styles()
    title_link = f'<link href="{article_link_target}" color="#2a201d">{escape(article.title)}</link>'
    header_flowables: list[object] = []
    logo_path = ROOT / "logopdf.fw.png"
    if logo_path.exists():
        try:
            logo_reader = ImageReader(str(logo_path))
            logo_width_px, logo_height_px = logo_reader.getSize()
            logo_width = (logo_width_px * 72 / 96) * (2 / 3)
            logo_height = (logo_height_px * 72 / 96) * (2 / 3)
            logo = PlatypusImage(str(logo_path), width=logo_width, height=logo_height)
            logo.hAlign = "LEFT"
            header_flowables.append(logo)
            header_flowables.append(Spacer(1, 3 * mm))
        except Exception:
            pass
    header_flowables.extend([
        Paragraph(title_link, styles["header_title"]),
        Paragraph(f"Autor: {escape(article.author)}", styles["meta"]),
        Paragraph(f"Publicacao: {escape(published)}", styles["meta"]),
        Paragraph(
            f'Link do texto: <link href="{article_link_target}" color="#8d2f23">{escape(article_link_label)}</link>',
            styles["meta"],
        ),
    ])
    return KeepTogether(
        [
            *header_flowables,
            Spacer(1, 4 * mm),
            HRFlowable(width="100%", thickness=0.8, color=PDF_RULE, spaceBefore=0, spaceAfter=6 * mm),
        ]
    )


def create_article_pdf(article: Article) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = PDF_DIR / f"{article.slug}.pdf"
    published = format_long_date(article.published_at)
    article_link_label = "www.revistabarravento.com.br"
    article_link_target = "https://www.revistabarravento.com.br"
    styles = pdf_styles()

    story: list[object] = [build_pdf_header(article, published, article_link_label, article_link_target)]
    first_paragraph = True

    for block in article.blocks:
        if block.kind == "heading":
            story.append(Paragraph(escape(block.text.upper()), styles["heading"]))
            continue

        style = styles["lead"] if first_paragraph else styles["body"]
        story.append(Paragraph(pdf_paragraph_text(paragraph_html(block)), style))
        first_paragraph = False

    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    def apply_pdf_metadata(canvas, _document) -> None:
        canvas.setTitle(article.title)
        canvas.setAuthor(article.author)
        canvas.setSubject("Revista Barravento")

    document.build(story, onFirstPage=apply_pdf_metadata, onLaterPages=apply_pdf_metadata)


def render_home_page(articles: list[Article]) -> str:
    today = format_long_date(datetime.now())
    monthly_read_counts = load_monthly_read_counts()
    most_read_articles = sorted(
        articles,
        key=lambda article: (
            -int(monthly_read_counts.get(article.slug, 0) or 0),
            -article.published_at.timestamp(),
        ),
    )
    category_sections = "\n".join(
        render_home_category_panel(
            category,
            [article for article in articles if category in article.categories],
        )
        for category in CATEGORY_OPTIONS
    )

    featured_html = render_featured_carousel(articles)
    most_read_html = render_most_read_sidebar(most_read_articles)
    tag_mosaic_html = render_home_tag_mosaic(articles)
    if tag_mosaic_html:
        category_sections = f"{category_sections}\n{tag_mosaic_html}" if category_sections else tag_mosaic_html
    home_script = """
      <script>
        (() => {
          const carousel = document.querySelector("[data-feature-carousel]");
          if (!carousel) {
            return;
          }

          const slides = Array.from(carousel.querySelectorAll("[data-feature-slide]"));
          const dots = Array.from(carousel.querySelectorAll("[data-feature-dot]"));
          const previousButton = carousel.querySelector("[data-feature-prev]");
          const nextButton = carousel.querySelector("[data-feature-next]");
          if (slides.length < 2) {
            return;
          }

          let currentIndex = 0;
          let timer = null;

          const applySlide = (nextIndex) => {
            currentIndex = nextIndex;
            slides.forEach((slide, index) => {
              slide.classList.toggle("is-active", index === currentIndex);
            });
            dots.forEach((dot, index) => {
              dot.classList.toggle("is-active", index === currentIndex);
            });
          };

          const restart = () => {
            if (timer) {
              clearInterval(timer);
            }
            timer = setInterval(() => {
              applySlide((currentIndex + 1) % slides.length);
            }, 5000);
          };

          dots.forEach((dot, index) => {
            dot.addEventListener("click", () => {
              applySlide(index);
              restart();
            });
          });

          if (previousButton) {
            previousButton.addEventListener("click", () => {
              applySlide((currentIndex - 1 + slides.length) % slides.length);
              restart();
            });
          }

          if (nextButton) {
            nextButton.addEventListener("click", () => {
              applySlide((currentIndex + 1) % slides.length);
              restart();
            });
          }

          carousel.addEventListener("mouseenter", () => {
            if (timer) {
              clearInterval(timer);
            }
          });

          carousel.addEventListener("mouseleave", restart);
          applySlide(0);
          restart();
        })();
      </script>"""

    content = f"""{render_header('', date_label=today)}
    <main>
      <section class="home-stage">
        <div class="container home-stage__grid">
{featured_html}
{most_read_html}
        </div>
      </section>

      <section class="section compact-hub">
        <div class="container">
          <div class="section__head section__head--compact">
            <div>
              <span class="eyebrow">Editorias</span>
              <h2>Ultimos tres textos por categoria</h2>
            </div>
          </div>
          <div class="category-panel-grid">
{category_sections}
          </div>
        </div>
      </section>
{home_script}
    </main>
"""
    return render_shell(
        page_title="Home",
        description="Revista Barravento com busca, categorias editoriais e publicacao automatica.",
        css_path="styles/site.css",
        icon_path=site_logo_href(""),
        body_class="home-page",
        content=content,
        page_path="",
        keywords=["revista", "artigos", "editorial", "cultura", "teoria", "traduções"],
        seo_json_ld=[
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": SITE_NAME,
                "url": absolute_site_url(""),
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": absolute_site_url("busca/?q={search_term_string}"),
                    "query-input": "required name=search_term_string",
                },
            }
        ],
    )


def render_category_page(category: str, articles: list[Article]) -> str:
    cards = (
        "\n".join(render_standard_card(article, "../../") for article in articles)
        if articles
        else """            <div class="empty-state">
              <h3>Sem textos publicados ainda</h3>
              <p>Quando um artigo for marcado nesta editoria, ele aparecera automaticamente aqui.</p>
            </div>"""
    )
    content = f"""{render_header('../../', date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner">
        <div class="container">
          <span class="eyebrow">Categoria</span>
          <h2>{escape(category)}</h2>
          <p>Todos os textos relacionados a esta editoria aparecem nesta pagina.</p>
        </div>
      </section>

      <section class="section">
        <div class="container">
          <div class="article-grid article-grid--wide">
{cards}
          </div>
        </div>
      </section>
    </main>
"""
    return render_shell(
        page_title=category,
        description=f"Arquivo da editoria {category}.",
        css_path="../../styles/site.css",
        icon_path=site_logo_href("../../"),
        body_class="category-page",
        content=content,
        page_path=f"categorias/{slugify(category)}/index.html",
        keywords=[category, "categoria", "artigos"],
    )


def render_static_page(
    *,
    title: str,
    eyebrow: str,
    summary: str,
    blocks: list[str],
    root_prefix: str,
    body_class: str,
) -> str:
    paragraphs = "\n".join(f"            <p>{escape(block)}</p>" for block in blocks)
    content = f"""{render_header(root_prefix, date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner">
        <div class="container">
          <span class="eyebrow">{escape(eyebrow)}</span>
          <h2>{escape(title)}</h2>
          <p>{escape(summary)}</p>
        </div>
      </section>

      <section class="section">
        <div class="container static-copy">
{paragraphs}
        </div>
      </section>
    </main>
"""
    return render_shell(
        page_title=title,
        description=summary,
        css_path=f"{root_prefix}styles/site.css",
        icon_path=site_logo_href(root_prefix),
        body_class=body_class,
        content=content,
        page_path=page_path_from_root(root_prefix, f"{slugify(title)}/index.html") if root_prefix else f"{slugify(title)}/index.html",
        keywords=[title, eyebrow],
    )


def render_member_directory_section(title: str, description: str, members: list[MemberProfile], root_prefix: str) -> str:
    if not members:
        return ""
    items = "\n".join(
        f"""            <li class="member-directory-list__item">
              <a href="{profile_href(member.profile_slug, root_prefix)}">{escape(member.name)}</a>
              <span> - {escape(member.editorial_role)}</span>
            </li>"""
        for member in members
    )
    return f"""      <section class="section">
        <div class="container">
          <div class="card-header">
            <h3>{escape(title)}</h3>
            <p>{escape(description)}</p>
          </div>
          <ul class="member-directory-list">
{items}
          </ul>
        </div>
      </section>
"""


def render_who_page(members: list[MemberProfile]) -> str:
    content = load_who_content()
    council_members = [member for member in members if member.role == "admin"]
    other_members = [member for member in members if member.role != "admin"]
    body_blocks = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", content["body"])
        if paragraph.strip()
    ]
    body_html = "\n".join(f"            <p>{escape(block)}</p>" for block in body_blocks)
    page_content = f"""{render_header("../", date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner">
        <div class="container">
          <span class="eyebrow">Institucional</span>
          <h2>{escape(content['title'])}</h2>
          <p>{escape(content['summary'])}</p>
        </div>
      </section>

      <section class="section">
        <div class="container static-copy">
{body_html}
        </div>
      </section>
{render_member_directory_section("Conselho Editorial", "Integrantes do conselho com perfil publico.", council_members, "../")}{render_member_directory_section("Integrantes", "Perfis publicos dos membros da revista.", other_members, "../")}    </main>
"""
    return render_shell(
        page_title=content["title"],
        description=content["summary"],
        css_path="../styles/site.css",
        icon_path=site_logo_href("../"),
        body_class="static-page",
        content=page_content,
        page_path="quem-somos/index.html",
        keywords=["Quem Somos", "Institucional", "Equipe"],
    )


def render_profile_page(member: MemberProfile, articles: list[Article]) -> str:
    authored_articles = [
        article for article in articles
        if any(
            str(item.get("email", "")).strip().lower() == member.email.lower()
            for item in (article.author_members or [])
        )
    ]
    photo_src = f"../../{member.photo_url.lstrip('/')}" if member.photo_url else ""
    photo_markup = f'<img src="{escape(photo_src)}" alt="{escape(member.name)}">' if photo_src else ""
    authored_cards = "\n".join(render_standard_card(article, "../../") for article in authored_articles)
    if not authored_cards:
        authored_cards = """            <div class="empty-state empty-state--compact">
              <h3>Sem textos vinculados ainda</h3>
              <p>Os textos assinados por este integrante aparecerao aqui.</p>
            </div>"""
    page_content = f"""{render_header("../../", date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner profile-banner">
        <div class="container">
          <div class="profile-banner__inner">
            <div class="profile-banner__copy">
              <span class="eyebrow">Perfil</span>
              <h2>{escape(member.name)}</h2>
              <p>{escape(member.editorial_role)}</p>
              <div class="meta-row">
                <span>{escape(member.role_label)}</span>
                <span>{escape(member.education or "Formacao nao informada.")}</span>
              </div>
            </div>
            {f'<figure class="profile-banner__photo">{photo_markup}</figure>' if photo_markup else ""}
          </div>
        </div>
      </section>

      <section class="section">
        <div class="container profile-details">
          <article class="sidebar-card profile-details__card">
            <h3>Formacao</h3>
            <p>{escape(member.education or "Formacao nao informada.")}</p>
          </article>
          <article class="sidebar-card profile-details__card">
            <h3>Atuacao na revista</h3>
            <p>{escape(member.editorial_role)}</p>
            <p><a class="article-card__link" href="../../quem-somos/">Voltar para Quem Somos</a></p>
          </article>
        </div>
      </section>

      <section class="section">
        <div class="container">
          <div class="card-header">
            <h3>Textos assinados</h3>
          </div>
          <div class="story-grid">
{authored_cards}
          </div>
        </div>
      </section>
    </main>
"""
    return render_shell(
        page_title=member.name,
        description=f"Perfil de {member.name} na Revista Barravento.",
        css_path="../../styles/site.css",
        icon_path=site_logo_href("../../"),
        body_class="static-page profile-page",
        content=page_content,
        page_path=f"perfis/{member.profile_slug}/index.html",
        seo_type="profile",
        keywords=[member.name, member.editorial_role, member.role_label],
        image_path=member.photo_url or DEFAULT_SOCIAL_IMAGE,
    )


def serialize_article_for_client(article: Article, root_prefix: str) -> dict[str, object]:
    return {
        "slug": article.slug,
        "article_id": article.article_id,
        "title": article.title,
        "author": article.author,
        "author_text": article.author_text,
        "author_members": article.author_members or [],
        "summary": article.summary,
        "body_editor": blocks_to_editor_markup(article.blocks),
        "body_html": article.body_html or blocks_to_rich_editor_html(article.blocks),
        "body_blocks": [serialize_block_for_client(block) for block in article.blocks],
        "categories": article.categories,
        "tags": article.tags,
        "hashtags": article.hashtags,
        "published_label": format_long_date(article.published_at),
        "reading_time": article.reading_time,
        "article_url": article_href(article, root_prefix),
        "image_url": image_src(article, root_prefix),
        "image_alt": article.image_alt,
        "source_name": article.source_name,
    }


def serialize_block_for_client(block: Block) -> dict[str, object]:
    return {
        "kind": block.kind,
        "text": block.text,
        "level": block.level,
        "html": block.html,
        "align": block.align,
    }


def block_align_style(block: Block) -> str:
    if block.align and block.align != "left":
        return f' style="text-align:{escape(block.align)}"'
    return ""


def blocks_to_rich_editor_html(blocks: list[Block]) -> str:
    html_parts: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            tag = "h3" if block.level >= 3 else "h2"
            html_parts.append(f"<{tag}{block_align_style(block)}>{escape(block.text)}</{tag}>")
            continue
        if block.kind == "divider":
            html_parts.append("<hr>")
            continue
        if block.kind == "quote":
            inner = block.html or f"<p>{escape_with_breaks(block.text)}</p>"
            html_parts.append(f"<blockquote{block_align_style(block)}>{inner}</blockquote>")
            continue
        if block.kind == "list":
            if block.html:
                html_parts.append(f'<div{block_align_style(block)}>{block.html}</div>')
                continue
            tag = "ol" if block.level > 0 else "ul"
            items = [item.strip() for item in block.text.split(" • ") if item.strip()]
            html_parts.append(f'<div{block_align_style(block)}><{tag}>{"".join(f"<li>{escape(item)}</li>" for item in items)}</{tag}></div>')
            continue
        html_parts.append(f"<p{block_align_style(block)}>{paragraph_html(block)}</p>")
    return "".join(html_parts)


def category_select_html(*, name: str, select_id: str) -> str:
    options = "\n".join(
        f'                  <option value="{escape(category)}">{escape(category)}</option>'
        for category in CATEGORY_OPTIONS
    )
    checkboxes = "\n".join(
        f"""                    <label class="category-combobox__option">
                      <input type="checkbox" value="{escape(category)}" data-category-checkbox>
                      <span>{escape(category)}</span>
                    </label>"""
        for category in CATEGORY_OPTIONS
    )
    return f"""                <div class="category-combobox" data-category-combobox>
                  <button class="category-combobox__toggle" type="button" aria-expanded="false">
                    <span class="category-combobox__label">Selecionar categorias</span>
                    <span class="category-combobox__arrow" aria-hidden="true">▼</span>
                  </button>
                  <div class="category-combobox__menu" hidden>
                    <label class="category-combobox__search">
                      <input type="search" placeholder="Buscar categoria" data-category-search>
                    </label>
                    <div class="category-combobox__options">
{checkboxes}
                    </div>
                  </div>
                  <div class="category-combobox__summary" data-category-summary hidden></div>
                  <select id="{select_id}" name="{name}" class="category-select" multiple size="{len(CATEGORY_OPTIONS)}" required hidden>
{options}
                  </select>
                </div>
                <p class="field-help">Clique no campo, abra o drop e marque quantas categorias quiser.</p>"""


def member_select_html(*, name: str, select_id: str, label: str, multiple: bool = True) -> str:
    multiple_attr = " multiple" if multiple else ""
    size_attr = ' size="6"' if multiple else ""
    helper = "Selecione integrantes cadastrados para somar aos nomes digitados no campo Autor." if multiple else "Escolha um cargo para o perfil publico."
    return f"""              <div class="field field--half">
                <span>{escape(label)}</span>
                <div class="category-combobox" data-member-combobox>
                  <button class="category-combobox__toggle" type="button" aria-expanded="false">
                    <span class="category-combobox__label">Selecionar integrantes</span>
                    <span class="category-combobox__arrow" aria-hidden="true">▼</span>
                  </button>
                  <div class="category-combobox__menu" hidden>
                    <label class="category-combobox__search">
                      <input type="search" placeholder="Buscar integrante" data-member-search>
                    </label>
                    <div class="category-combobox__options" data-member-options>
                    </div>
                  </div>
                  <div class="category-combobox__summary" data-member-summary hidden></div>
                  <select id="{select_id}" name="{name}" class="category-select" multiple size="6" hidden>
                  </select>
                </div>
                <p class="field-help">{escape(helper)}</p>
              </div>"""


def render_upload_page(articles: list[Article], *, root_prefix: str = "") -> str:
    links = page_links(root_prefix)
    article_data = json_for_script([serialize_article_for_client(article, root_prefix) for article in articles])
    content = f"""{render_header(root_prefix, date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner">
        <div class="container">
          <span class="eyebrow">Painel de membros</span>
          <h2>Painel editorial da revista</h2>
          <p>Use este painel para publicar, revisar, editar e acompanhar o acervo. O acesso acontece pela pagina de membros.</p>
        </div>
      </section>

      <section class="section" id="member-auth-entry">
        <div class="container editor-grid members-grid">
          <section class="upload-card upload-card--main">
            <div class="card-header">
              <h3>Acesso de membro</h3>
              <p>Se a sua sessao expirar, entre novamente com o e-mail e a senha aprovados para liberar o painel de membros.</p>
            </div>
            <form id="login-form" class="upload-form">
              <label class="field">
                <span>E-mail</span>
                <input id="login-email" name="email" type="email" autocomplete="username" required>
              </label>

              <label class="field">
                <span>Senha</span>
                <input id="login-password" name="password" type="password" autocomplete="current-password" required>
              </label>

              <div class="upload-actions">
                <button class="button-link" type="submit">Entrar</button>
              </div>
              <div class="upload-status" id="login-status" role="status" aria-live="polite"></div>
            </form>
          </section>
        </div>
      </section>

      <section class="section">
        <div class="container">
          <section class="upload-card member-session" id="member-session" hidden>
            <div class="card-header">
              <h3>Membro autenticado</h3>
              <p id="member-summary">Assim que o login for confirmado, o painel editorial sera aberto abaixo.</p>
            </div>
            <div class="upload-actions">
              <button class="button-link button-link--ghost" id="open-profile-tab" type="button">Editar perfil</button>
              <button class="button-link button-link--ghost" id="logout-button" type="button">Sair</button>
            </div>
            <div class="upload-status" id="member-status" role="status" aria-live="polite"></div>
          </section>

          <section class="upload-card member-lock" id="member-lock">
            <div class="card-header">
              <h3>Painel editorial protegido</h3>
              <p>As abas de publicacao, edicao, recados, dashboard e aprovacoes ficam bloqueadas ate que um membro aprovado entre com e-mail e senha.</p>
            </div>
          </section>
        </div>
      </section>

      <section class="section member-panel" id="member-panel" hidden>
        <div class="container">
          <nav class="member-tabs" aria-label="Abas do painel de membros">
            <button class="member-tab-button is-active" data-member-tab="notices" type="button">Recados</button>
            <button class="member-tab-button" data-member-tab="upload" type="button">Publicar</button>
            <button class="member-tab-button" data-member-tab="edit" type="button">Editar texto</button>
            <button class="member-tab-button" data-member-tab="profile" type="button">Editar perfil</button>
            <button class="member-tab-button" data-member-tab="members" type="button">Cadastrar membro</button>
            <button class="member-tab-button" id="approvals-tab-button" data-member-tab="approvals" type="button">Aprovações</button>
            <button class="member-tab-button" data-member-tab="dashboard" type="button">Dashboard</button>
            <button class="member-tab-button" id="logs-tab-button" data-member-tab="logs" type="button">Logs</button>
          </nav>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="upload" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Publicar</h3>
              <p>Use este bloco para criar uma nova pagina no site. O sistema preserva negrito, italico e desloca notas de rodape e referencias bibliograficas para o final.</p>
            </div>
            <form id="create-form" class="upload-form upload-form--editor-layout">
              <label class="field field--half field--docx-option">
                <span>Arquivo DOCX</span>
                <input name="docx" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required>
              </label>

              <input id="create-docx-import-id" name="docx_import_id" type="hidden">

              <div class="upload-actions upload-actions--inline upload-actions--subtle">
                <button class="button-link button-link--ghost button-link--subtle button-link--tiny" id="create-import-docx" type="button">Importar DOCX para edicao</button>
              </div>

              <label class="field field--half">
                <span>Imagem de capa</span>
                <input name="image" type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" required>
              </label>

              <div class="field field--half">
                <span>Categorias</span>
{category_select_html(name='categories', select_id='create-categories')}
              </div>

              <label class="field field--half">
                <span>Titulo</span>
                <input name="title" type="text" placeholder="Informe o titulo do texto." required>
              </label>

              <label class="field field--half">
                <span>Autor</span>
                <input name="author" type="text" placeholder="Opcional. Se vazio, o sistema tenta ler do documento.">
              </label>

{member_select_html(name='author_members', select_id='create-author-members', label='Integrantes autores')}

              <label class="field field--half">
                <span>Resumo</span>
                <textarea name="summary" rows="3" placeholder="Opcional. Se vazio, o resumo sera gerado automaticamente."></textarea>
              </label>

              <label class="field field--half">
                <span>Tags</span>
                <input name="tags" type="text" placeholder="Ex.: teoria, cultura, politica">
              </label>

              <label class="field field--half">
                <span>Hashtags</span>
                <input name="hashtags" type="text" placeholder="Ex.: marxismo, classe trabalhadora">
              </label>

              <div class="field field--editor field--full">
                <span>Corpo do texto</span>
                <div class="rich-editor">
                  <div class="rich-editor__meta rich-editor__meta--compact">
                    <div class="rich-editor__meta-text">
                      <strong>Editor de criacao</strong>
                      <span>Importe o DOCX, ajuste o tamanho da fonte e revise o texto final aqui.</span>
                    </div>
                    <div class="rich-editor__meta-actions">
                      <label class="rich-editor__control">
                        <span>Tamanho da fonte</span>
                        <select id="create-font-size">
                          <option value="12px">12 px</option>
                          <option value="14px">14 px</option>
                          <option value="16px">16 px</option>
                          <option value="17px" selected>17 px</option>
                          <option value="18px">18 px</option>
                          <option value="20px">20 px</option>
                          <option value="24px">24 px</option>
                          <option value="28px">28 px</option>
                          <option value="32px">32 px</option>
                          <option value="36px">36 px</option>
                        </select>
                      </label>
                    </div>
                  </div>
                  <div id="create-body-editor" class="rich-editor__textarea"></div>
                </div>
                <textarea id="create-body" name="body" hidden></textarea>
                <input id="create-body-html" name="body_html" type="hidden">
                <input id="create-body-blocks" name="body_blocks_json" type="hidden">
                <p class="field-help">Importe o DOCX para esta caixa, revise e publique apenas o que ficou editado aqui.</p>
              </div>

              <div class="upload-actions upload-actions--guarded" id="create-submit-actions">
                <button class="button-link" id="create-submit-button" type="submit" disabled aria-disabled="true">Publicar texto</button>
              </div>
              <div class="upload-status" id="create-status" role="status" aria-live="polite"></div>
            </form>
          </section>

          <section class="upload-card upload-card--main member-tab-card is-active" data-member-tab-panel="notices" aria-hidden="false" style="display:block;">
            <div class="card-header">
              <h3>Recados para membros</h3>
              <p>Esse mural fica visivel para todos os membros logados. Escreva e publique um recado abaixo.</p>
            </div>
            <p class="field-help">Os recados e retornos do Conselho Editorial ficam disponiveis por ate 2 meses e depois sao removidos automaticamente.</p>
            <form id="notice-form" class="upload-form">
              <label class="field">
                <span>Novo recado</span>
                <textarea id="notice-message" name="message" rows="5" placeholder="Escreva aqui o recado para os outros membros." required></textarea>
              </label>

              <div class="upload-actions">
                <button class="button-link" type="submit">Publicar recado</button>
              </div>
              <div class="upload-status" id="notice-status" role="status" aria-live="polite"></div>
            </form>
            <div class="member-notices" id="notice-list"></div>
          </section>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="dashboard" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Dashboard editorial</h3>
              <p>Os numeros abaixo mostram acessos por texto e downloads de PDF por texto, coletados no servidor local.</p>
            </div>
            <div class="dashboard-toolbar">
              <label class="field dashboard-filter">
                <span>Periodo</span>
                <select id="dashboard-period">
                  <option value="7">Ultimos 7 dias</option>
                  <option value="30" selected>Ultimos 30 dias</option>
                  <option value="90">Ultimos 90 dias</option>
                  <option value="365">Ultimos 365 dias</option>
                  <option value="all">Todo o periodo</option>
                </select>
              </label>
              <label class="field dashboard-filter">
                <span>Modalidade</span>
                <select id="dashboard-metric">
                  <option value="views" selected>Acessos</option>
                  <option value="locations">Local dos acessos</option>
                  <option value="pdf_downloads">Download PDF</option>
                </select>
              </label>
              <label class="field dashboard-filter">
                <span>Grafico</span>
                <select id="dashboard-chart-kind">
                  <option value="line" selected>Linha</option>
                  <option value="pie">Pizza</option>
                </select>
              </label>
              <button class="button-link button-link--ghost" id="dashboard-refresh" type="button">Atualizar dashboard</button>
            </div>
            <div class="upload-status" id="dashboard-status" role="status" aria-live="polite"></div>
            <div class="member-dashboard" id="dashboard-list"></div>
          </section>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="edit" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Editar texto</h3>
              <p>Selecione um texto existente. O arquivo novo ou a imagem nova substituem os anteriores, voce pode editar o corpo e tambem excluir o texto pelo painel.</p>
            </div>
            <form id="edit-form" class="upload-form upload-form--editor-layout">
              <div class="field field--half field--edit-target">
                <span>Texto existente</span>
                <div class="field-inline-actions">
                  <select id="edit-slug" name="slug" required>
                    <option value="">Escolha um texto</option>
                  </select>
                  <button class="button-link button-link--ghost button-link--danger button-link--tiny" id="delete-article-button" type="button">Excluir</button>
                </div>
              </div>

              <label class="field field--half">
                <span>Titulo</span>
                <input id="edit-title" name="title" type="text" required>
              </label>

              <label class="field field--half">
                <span>Nova imagem</span>
                <input name="image" type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp">
              </label>

              <div class="field field--half">
                <span>Categorias</span>
{category_select_html(name='categories', select_id='edit-categories')}
              </div>

              <label class="field field--half">
                <span>Autor</span>
                <input id="edit-author" name="author" type="text">
              </label>

{member_select_html(name='author_members', select_id='edit-author-members', label='Integrantes autores')}

              <label class="field field--half">
                <span>Resumo</span>
                <textarea id="edit-summary" name="summary" rows="3"></textarea>
              </label>

              <label class="field field--half">
                <span>Tags</span>
                <input id="edit-tags" name="tags" type="text">
              </label>

              <label class="field field--half">
                <span>Hashtags</span>
                <input id="edit-hashtags" name="hashtags" type="text">
              </label>

              <label class="field field--half field--docx-option">
                <span>Novo DOCX</span>
                <input name="docx" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document">
              </label>

              <input id="edit-docx-import-id" name="docx_import_id" type="hidden">

              <div class="upload-actions upload-actions--inline upload-actions--subtle">
                <button class="button-link button-link--ghost button-link--subtle" id="edit-import-docx" type="button">Importar novo DOCX para edicao</button>
              </div>

              <div class="field field--editor field--full">
                <span>Corpo do texto</span>
                <div class="editor-workspace">
                  <div class="rich-editor" data-rich-editor>
                    <div class="rich-editor__meta">
                      <div class="rich-editor__meta-text">
                        <strong>Editor completo</strong>
                        <span>Negrito, fontes, cores, alinhamento, tabelas, codigo, links, listas e visualizacao.</span>
                      </div>
                      <div class="rich-editor__meta-actions">
                        <label class="rich-editor__control">
                          <span>Tamanho da fonte</span>
                          <select id="edit-font-size">
                            <option value="12px">12 px</option>
                            <option value="14px">14 px</option>
                            <option value="16px">16 px</option>
                            <option value="17px" selected>17 px</option>
                            <option value="18px">18 px</option>
                            <option value="20px">20 px</option>
                            <option value="24px">24 px</option>
                            <option value="28px">28 px</option>
                            <option value="32px">32 px</option>
                            <option value="36px">36 px</option>
                          </select>
                        </label>
                        <label class="rich-editor__switch">
                          <input id="editor-spellcheck-toggle" type="checkbox" checked>
                          <span>Corretor ortografico</span>
                        </label>
                        <button class="rich-editor__ghost" id="editor-preview-button" type="button">Visualizar</button>
                        <button class="rich-editor__ghost" id="editor-export-html" type="button">Exportar HTML</button>
                        <button class="rich-editor__ghost" id="editor-export-txt" type="button">Exportar TXT</button>
                      </div>
                    </div>
                    <div id="editor-toolbar" class="rich-editor__toolbar-host"></div>
                    <div
                      id="edit-body-editor"
                      class="rich-editor__textarea"
                    ></div>
                  </div>
                  <aside class="editor-insights">
                    <div class="editor-insights__tabs">
                      <button class="is-active" type="button">Resumo</button>
                    </div>
                    <div class="editor-insights__section">
                      <span class="editor-insights__eyebrow">Panorama</span>
                      <div class="editor-insights__cards">
                        <article class="editor-insights__card">
                          <span>Caracteres</span>
                          <strong id="editor-char-count">0</strong>
                        </article>
                        <article class="editor-insights__card">
                          <span>Palavras</span>
                          <strong id="editor-word-count">0</strong>
                        </article>
                        <article class="editor-insights__card">
                          <span>Leitura</span>
                          <strong id="editor-reading-time">1 min</strong>
                        </article>
                        <article class="editor-insights__card">
                          <span>Blocos</span>
                          <strong id="editor-block-count">0</strong>
                        </article>
                      </div>
                    </div>
                    <div class="editor-insights__section">
                      <span class="editor-insights__eyebrow">Status</span>
                      <p id="editor-status-text">O texto sera preservado com HTML rico e enviado para aprovacao.</p>
                    </div>
                    <div class="editor-insights__section">
                      <span class="editor-insights__eyebrow">Resumo rapido</span>
                      <p id="editor-summary-preview">Comece a escrever para ver uma previa curta do conteudo.</p>
                    </div>
                  </aside>
                </div>
                <textarea id="edit-body" name="body" hidden></textarea>
                <input id="edit-body-html" name="body_html" type="hidden">
                <input id="edit-body-blocks" name="body_blocks_json" type="hidden">
                <p class="field-help">O texto final preserva HTML rico, tabelas, trechos de codigo, cores, alinhamento e links.</p>
              </div>

              <div class="upload-actions">
                <button class="button-link" type="submit">Salvar edicao</button>
              </div>
              <div class="upload-status" id="edit-status" role="status" aria-live="polite"></div>
            </form>
          </section>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="profile" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Editar perfil</h3>
              <p>Atualize seu perfil publico com nome, cargo na revista, formacao e foto. Esse perfil aparece na pagina Quem Somos.</p>
            </div>
            <form id="profile-form" class="upload-form upload-form--editor-layout">
              <label class="field field--half">
                <span>Nome</span>
                <input id="profile-name" name="name" type="text" autocomplete="name" required>
              </label>

              <label class="field field--half">
                <span>Cargo na revista</span>
                <select id="profile-editorial-role" name="editorial_role" required>
                  <option value="Opcao A">Opcao A</option>
                  <option value="Opcao B">Opcao B</option>
                  <option value="Opcao C">Opcao C</option>
                </select>
              </label>

              <label class="field field--half">
                <span>Formacao</span>
                <textarea id="profile-education" name="education" rows="4" placeholder="Ex.: graduacao, pesquisa, area de atuacao"></textarea>
              </label>

              <label class="field field--half">
                <span>Foto</span>
                <input id="profile-photo" name="photo" type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp">
              </label>

              <div class="upload-actions">
                <button class="button-link" type="submit">Salvar perfil</button>
              </div>
              <div class="upload-status" id="profile-status" role="status" aria-live="polite"></div>
            </form>

            <section class="profile-preview-card">
              <div class="card-header">
                <h3>Previa publica</h3>
                <p>Resumo de como seu perfil aparece no site.</p>
              </div>
              <div id="profile-preview"></div>
            </section>

            <section class="upload-card upload-card--nested" id="who-form-shell" hidden>
              <div class="card-header">
                <h3>Upar Quem Somos</h3>
                <p>Disponivel apenas para membros do Conselho Editorial. O texto salvo aparece na pagina Quem Somos.</p>
              </div>
              <form id="who-form" class="upload-form">
                <label class="field">
                  <span>Titulo</span>
                  <input id="who-title" name="title" type="text" required>
                </label>

                <label class="field">
                  <span>Resumo</span>
                  <textarea id="who-summary" name="summary" rows="3" required></textarea>
                </label>

                <label class="field">
                  <span>Texto institucional</span>
                  <textarea id="who-body" name="body" rows="8" required></textarea>
                </label>

                <div class="upload-actions">
                  <button class="button-link" type="submit">Salvar Quem Somos</button>
                </div>
                <div class="upload-status" id="who-status" role="status" aria-live="polite"></div>
              </form>
            </section>
          </section>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="members" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Cadastrar membro</h3>
              <p>Crie um novo acesso e escolha o perfil. Todo cadastro entra em fila e precisa ser aprovado pelo Conselho Editorial.</p>
            </div>
            <form id="register-form" class="upload-form">
              <label class="field">
                <span>Nome</span>
                <input id="register-name" name="name" type="text" autocomplete="name" required>
              </label>

              <label class="field">
                <span>E-mail</span>
                <input id="register-email" name="email" type="email" autocomplete="username" required>
              </label>

              <label class="field">
                <span>Perfil</span>
                <select id="register-role" name="role" required>
                  <option value="reviewer">Revisor</option>
                  <option value="admin">Conselho Editorial</option>
                </select>
              </label>

              <label class="field">
                <span>Senha</span>
                <input id="register-password" name="password" type="password" autocomplete="new-password" required>
              </label>

              <label class="field">
                <span>Confirmar senha</span>
                <input id="register-password-confirm" name="password_confirm" type="password" autocomplete="new-password" required>
              </label>

              <div class="upload-actions">
                <button class="button-link" type="submit">Cadastrar</button>
              </div>
              <div class="upload-status" id="register-status" role="status" aria-live="polite"></div>
            </form>
          </section>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="approvals" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Aprovações do Conselho Editorial</h3>
              <p>Cadastros e publicações pendentes só aparecem para administradores e podem ser aprovados por aqui.</p>
            </div>
            <div class="upload-actions">
              <button class="button-link button-link--ghost" id="approvals-refresh" type="button">Atualizar aprovações</button>
            </div>
            <div class="upload-status" id="approvals-status" role="status" aria-live="polite"></div>
            <div class="member-approvals">
              <section class="approval-group">
                <div class="card-header">
                  <h3>Cadastros pendentes</h3>
                </div>
                <div id="registration-approvals"></div>
              </section>
              <section class="approval-group">
                <div class="card-header">
                  <h3>Publicações pendentes</h3>
                </div>
                <div id="submission-approvals"></div>
              </section>
            </div>
          </section>

          <section class="upload-card upload-card--main member-tab-card" data-member-tab-panel="logs" aria-hidden="true" style="display:none;">
            <div class="card-header">
              <h3>Logs do Conselho Editorial</h3>
              <p>Registros curtos em TXT com retenção automática de 3 meses. Esta aba mostra acessos e ações dos membros.</p>
            </div>
            <div class="upload-actions">
              <button class="button-link button-link--ghost" id="logs-refresh" type="button">Atualizar logs</button>
            </div>
            <div class="upload-status" id="logs-status" role="status" aria-live="polite"></div>
            <div class="member-log-list" id="logs-list"></div>
          </section>
        </div>
      </section>

      <link rel="stylesheet" href="/vendor/quill/quill.snow.css">
      <script src="/vendor/quill/quill.js"></script>
      <script id="articles-data" type="application/json">{article_data}</script>
      <script>
        (() => {{
          const rawArticles = JSON.parse(document.getElementById("articles-data").textContent);
          let articles = repairValue(rawArticles);
          let articleMap = new Map(articles.map((item) => [item.slug, item]));
          const loginForm = document.getElementById("login-form");
          const registerForm = document.getElementById("register-form");
          const noticeForm = document.getElementById("notice-form");
          const createForm = document.getElementById("create-form");
          const createImportDocxButton = document.getElementById("create-import-docx");
          const createSubmitActions = document.getElementById("create-submit-actions");
          const createSubmitButton = document.getElementById("create-submit-button");
          const createDocxImportInput = document.getElementById("create-docx-import-id");
          const createDocxInput = createForm ? formField(createForm, "docx") : null;
          const createBodyInput = document.getElementById("create-body");
          const createBodyHtmlInput = document.getElementById("create-body-html");
          const createBodyBlocksInput = document.getElementById("create-body-blocks");
          const createBodyEditor = document.getElementById("create-body-editor");
          const editForm = document.getElementById("edit-form");
          const editImportDocxButton = document.getElementById("edit-import-docx");
          const editDocxImportInput = document.getElementById("edit-docx-import-id");
          const editDocxInput = editForm ? formField(editForm, "docx") : null;
          const editSelect = document.getElementById("edit-slug");
          const editBodyInput = document.getElementById("edit-body");
          const editBodyHtmlInput = document.getElementById("edit-body-html");
          const editBodyBlocksInput = document.getElementById("edit-body-blocks");
          const editBodyEditor = document.getElementById("edit-body-editor");
          const profileForm = document.getElementById("profile-form");
          const profilePreview = document.getElementById("profile-preview");
          const whoForm = document.getElementById("who-form");
          const whoFormShell = document.getElementById("who-form-shell");
          const openProfileTabButton = document.getElementById("open-profile-tab");
          const editorToolbar = document.getElementById("editor-toolbar");
          const editorSpellcheckToggle = document.getElementById("editor-spellcheck-toggle");
          const editorPreviewButton = document.getElementById("editor-preview-button");
          const editorExportHtmlButton = document.getElementById("editor-export-html");
          const editorExportTxtButton = document.getElementById("editor-export-txt");
          const editorCharCount = document.getElementById("editor-char-count");
          const editorWordCount = document.getElementById("editor-word-count");
          const editorReadingTime = document.getElementById("editor-reading-time");
          const editorBlockCount = document.getElementById("editor-block-count");
          const editorStatusText = document.getElementById("editor-status-text");
          const editorSummaryPreview = document.getElementById("editor-summary-preview");
          const deleteArticleButton = document.getElementById("delete-article-button");
          const logoutButton = document.getElementById("logout-button");
          const dashboardRefresh = document.getElementById("dashboard-refresh");
          const dashboardPeriod = document.getElementById("dashboard-period");
          const dashboardChartKind = document.getElementById("dashboard-chart-kind");
          const dashboardMetric = document.getElementById("dashboard-metric");
          const approvalsRefresh = document.getElementById("approvals-refresh");
          const logsRefresh = document.getElementById("logs-refresh");
          const memberLock = document.getElementById("member-lock");
          const memberPanel = document.getElementById("member-panel");
          const memberSession = document.getElementById("member-session");
          const memberSummary = document.getElementById("member-summary");
          const memberTabs = Array.from(document.querySelectorAll("[data-member-tab]"));
          const memberTabPanels = Array.from(document.querySelectorAll("[data-member-tab-panel]"));
          const approvalsTabButton = document.getElementById("approvals-tab-button");
          const logsTabButton = document.getElementById("logs-tab-button");
          const membersTabButton = document.querySelector('[data-member-tab="members"]');
          const noticeList = document.getElementById("notice-list");
          const dashboardList = document.getElementById("dashboard-list");
          const logsList = document.getElementById("logs-list");
          const registrationApprovals = document.getElementById("registration-approvals");
          const submissionApprovals = document.getElementById("submission-approvals");
          const loginStatus = document.getElementById("login-status");
          const registerStatus = document.getElementById("register-status");
          const noticeStatus = document.getElementById("notice-status");
          const dashboardStatus = document.getElementById("dashboard-status");
          const logsStatus = document.getElementById("logs-status");
          const approvalsStatus = document.getElementById("approvals-status");
          const memberStatus = document.getElementById("member-status");
          const createStatus = document.getElementById("create-status");
          const editStatus = document.getElementById("edit-status");
          const profileStatus = document.getElementById("profile-status");
          const whoStatus = document.getElementById("who-status");
          const memberAuthEntry = document.getElementById("member-auth-entry");
          const loginPageHref = {json.dumps(links["members_login"])};
          const panelPageHref = {json.dumps(links["members_panel"])};
          const panelStateKey = "barravento-member-last-session";
          const popupStatusNodes = [
            loginStatus,
            registerStatus,
            noticeStatus,
            dashboardStatus,
            logsStatus,
            approvalsStatus,
            memberStatus,
            createStatus,
            editStatus,
            profileStatus,
            whoStatus
          ].filter(Boolean);
          let editorReady = null;
          let pendingEditorHtml = "";
          let createEditorReady = null;
          let pendingCreateEditorHtml = "";
          let member = null;
          let memberDirectory = [];
          let dashboardPayload = null;
          let editSnapshot = null;
          let toastHost = null;

          function escapeHtml(value) {{
            return String(value).replace(/[&<>"']/g, (char) => {{
              const map = {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}};
              return map[char] || char;
            }});
          }}

          function suspiciousScore(value) {{
            const matches = String(value || "").match(/[ÃÂâ€™œž¢€]/g);
            return matches ? matches.length : 0;
          }}

          function repairText(value) {{
            const text = String(value ?? "");
            if (!text || suspiciousScore(text) === 0) {{
              return text;
            }}
            try {{
              const repaired = decodeURIComponent(escape(text));
              return suspiciousScore(repaired) <= suspiciousScore(text) ? repaired : text;
            }} catch (_error) {{
              return text;
            }}
          }}

          function repairValue(value) {{
            if (typeof value === "string") {{
              return repairText(value);
            }}
            if (Array.isArray(value)) {{
              return value.map((item) => repairValue(item));
            }}
            if (value && typeof value === "object") {{
              return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, repairValue(item)]));
            }}
            return value;
          }}

          function getToastHost() {{
            if (toastHost && document.body.contains(toastHost)) {{
              return toastHost;
            }}
            toastHost = document.createElement("div");
            toastHost.className = "member-toast-host";
            toastHost.setAttribute("aria-live", "polite");
            toastHost.setAttribute("aria-atomic", "false");
            document.body.appendChild(toastHost);
            return toastHost;
          }}

          function showToast(kind, html) {{
            const host = getToastHost();
            const toast = document.createElement("article");
            toast.className = "member-toast member-toast--" + kind;
            toast.innerHTML = '<div class="member-toast__body">' + html + '</div><button class="member-toast__close" type="button" aria-label="Fechar notificacao">Fechar</button>';
            host.appendChild(toast);
            const close = () => {{
              toast.classList.add("is-leaving");
              window.setTimeout(() => {{
                if (toast.parentNode) {{
                  toast.parentNode.removeChild(toast);
                }}
              }}, 220);
            }};
            const closeButton = toast.querySelector(".member-toast__close");
            if (closeButton) {{
              closeButton.addEventListener("click", close);
            }}
            const timeout = kind === "error" ? 5200 : (kind === "pending" ? 2400 : 3600);
            window.setTimeout(close, timeout);
          }}

          function setStatus(node, kind, html) {{
            node.className = "upload-status is-" + kind;
            node.innerHTML = html;
            if (node && node.dataset && node.dataset.popupStatus === "true" && html) {{
              showToast(kind, html);
            }}
          }}

          function clearStatus(node) {{
            node.className = "upload-status";
            node.innerHTML = "";
          }}

          function storePanelMemberState(current) {{
            try {{
              if (current) {{
                localStorage.setItem(panelStateKey, JSON.stringify({{
                  member: current,
                  saved_at: new Date().toISOString()
                }}));
              }} else {{
                localStorage.removeItem(panelStateKey);
              }}
            }} catch (error) {{
              return;
            }}
          }}

          function readStoredPanelMemberState() {{
            try {{
              const stored = JSON.parse(localStorage.getItem(panelStateKey) || "null");
              if (!stored || typeof stored !== "object" || !stored.member) {{
                return null;
              }}
              return stored.member;
            }} catch (error) {{
              return null;
            }}
          }}

          function describeCreateRequirements() {{
            if (!createForm) {{
              return {{ valid: true, message: "" }};
            }}
            const missing = [];
            const titleField = formField(createForm, "title");
            const imageField = formField(createForm, "image");
            const titleValue = String(titleField ? titleField.value : "").trim();
            const hasDocx = Boolean(createDocxInput && createDocxInput.files && createDocxInput.files[0]);
            const hasImage = Boolean(imageField && imageField.files && imageField.files[0]);
            const hasCategories = getCheckedValues(createForm).length > 0;
            const hasBody = collectEditorBlocks(getCreateEditorHtml()).length > 0;

            if (!member) {{
              missing.push("entre como membro");
            }}
            if (!hasDocx) {{
              missing.push("selecione o DOCX");
            }}
            if (!hasImage) {{
              missing.push("adicione a imagem de capa");
            }}
            if (!hasCategories) {{
              missing.push("marque ao menos uma categoria");
            }}
            if (!titleValue) {{
              missing.push("preencha o titulo");
            }}
            if (!hasBody) {{
              missing.push("importe e revise o corpo do texto");
            }}

            return missing.length
              ? {{ valid: false, message: "Faltando para publicar: " + missing.join("; ") + "." }}
              : {{ valid: true, message: "" }};
          }}

          function updateCreateSubmitState() {{
            if (!createSubmitActions || !createSubmitButton) {{
              return;
            }}
            const state = describeCreateRequirements();
            createSubmitButton.disabled = !state.valid;
            createSubmitButton.setAttribute("aria-disabled", state.valid ? "false" : "true");
            createSubmitButton.title = state.message;
            createSubmitActions.title = state.message;
            createSubmitActions.dataset.disabledReason = state.message;
            createSubmitActions.classList.toggle("is-disabled", !state.valid);
          }}

          popupStatusNodes.forEach((node) => {{
            node.dataset.popupStatus = "true";
          }});

          function normalizeInlineText(value) {{
            return repairText(String(value || "").replace(/\\u00a0/g, " ")).replace(/[ \\t]+/g, " ").trim();
          }}

          function normalizeMultilineText(value) {{
            return repairText(String(value || "").replace(/\\r\\n/g, "\\n").replace(/\\u00a0/g, " "));
          }}

          function htmlToText(html) {{
            const probe = document.createElement("div");
            probe.innerHTML = html;
            return normalizeInlineText(probe.textContent || "");
          }}

          function sanitizeUrl(value) {{
            const text = String(value || "").trim();
            if (!text) {{
              return "";
            }}
            if (/^(https?:|mailto:|#|\\/)/i.test(text)) {{
              return text;
            }}
            if (/^[\\w.-]+@[\\w.-]+\\.[A-Za-z]{{2,}}$/.test(text)) {{
              return "mailto:" + text;
            }}
            if (/^[\\w.-]+\\.[A-Za-z]{{2,}}/.test(text)) {{
              return "https://" + text;
            }}
            return "";
          }}

          function normalizeAlign(value) {{
            const text = String(value || "").trim().toLowerCase();
            return ["left", "center", "right", "justify"].includes(text) ? text : "left";
          }}

          function detectBlockAlign(node) {{
            if (!node || node.nodeType !== Node.ELEMENT_NODE) {{
              return "left";
            }}
            return normalizeAlign(node.style.textAlign || node.getAttribute("align") || "");
          }}

          function sanitizeInlineNodes(nodes) {{
            return nodes.map((node) => sanitizeInlineNode(node)).join("");
          }}

          function sanitizeInlineStyleValue(value) {{
            const allowed = [];
            String(value || "").split(";").forEach((chunk) => {{
              const [rawName, ...rawRest] = chunk.split(":");
              const name = String(rawName || "").trim().toLowerCase();
              const input = rawRest.join(":").trim();
              if (!name || !input) {{
                return;
              }}
              if (name === "text-align") {{
                const normalized = input.toLowerCase();
                if (["left", "center", "right", "justify"].includes(normalized)) {{
                  allowed.push(name + ":" + normalized);
                }}
                return;
              }}
              if (name === "color" || name === "background-color") {{
                if (/^(#[0-9a-f]{{3,8}}|rgba?\\([^)]*\\)|hsla?\\([^)]*\\)|[a-z-]+)$/i.test(input)) {{
                  allowed.push(name + ":" + input);
                }}
                return;
              }}
              if (name === "font-size") {{
                if (/^([0-9]{{1,3}}(\\.[0-9]+)?)(px|pt|em|rem|%)$/i.test(input) || /^(xx-small|x-small|small|medium|large|x-large|xx-large)$/i.test(input)) {{
                  allowed.push(name + ":" + input);
                }}
                return;
              }}
              if (name === "font-family") {{
                const safeFamily = input.replace(/[^a-z0-9,\\- "'_]/gi, "").trim();
                if (safeFamily) {{
                  allowed.push(name + ":" + safeFamily);
                }}
                return;
              }}
              if (name === "font-weight") {{
                if (/^(normal|bold|bolder|lighter|[1-9]00)$/i.test(input)) {{
                  allowed.push(name + ":" + input.toLowerCase());
                }}
                return;
              }}
              if (name === "font-style") {{
                if (/^(normal|italic|oblique)$/i.test(input)) {{
                  allowed.push(name + ":" + input.toLowerCase());
                }}
                return;
              }}
              if (name === "text-decoration") {{
                const normalized = input.toLowerCase().replace(/\\s+/g, " ").trim();
                if (/^(none|underline|line-through|underline line-through|line-through underline)$/.test(normalized)) {{
                  allowed.push(name + ":" + normalized);
                }}
                return;
              }}
              if (name === "line-height") {{
                if (/^([0-9]+(\\.[0-9]+)?)(px|pt|em|rem|%)?$/i.test(input) || /^(normal)$/i.test(input)) {{
                  allowed.push(name + ":" + input);
                }}
                return;
              }}
              if (name === "letter-spacing") {{
                if (/^-?([0-9]+(\\.[0-9]+)?)(px|pt|em|rem)$/i.test(input) || /^(normal)$/i.test(input)) {{
                  allowed.push(name + ":" + input);
                }}
                return;
              }}
              if (name === "white-space") {{
                if (/^(normal|pre|pre-wrap|pre-line|nowrap)$/i.test(input)) {{
                  allowed.push(name + ":" + input.toLowerCase());
                }}
                return;
              }}
              if (name === "margin-left" || name === "padding-left" || name === "text-indent") {{
                if (/^-?([0-9]+(\\.[0-9]+)?)(px|pt|em|rem|%)$/i.test(input)) {{
                  allowed.push(name + ":" + input);
                }}
              }}
            }});
            return allowed.join("; ");
          }}

          function sanitizeInlineNode(node) {{
            if (node.nodeType === Node.TEXT_NODE) {{
              return escapeHtml(node.textContent || "");
            }}
            if (node.nodeType !== Node.ELEMENT_NODE) {{
              return "";
            }}
            const tag = node.tagName.toLowerCase();
            if (tag === "br") {{
              return "<br>";
            }}
            if (["strong", "b", "em", "i", "u", "sup", "sub", "s", "span", "code"].includes(tag)) {{
              const style = sanitizeInlineStyleValue(node.getAttribute("style") || "");
              const attrs = style ? ' style="' + escapeHtml(style) + '"' : "";
              return "<" + tag + attrs + ">" + sanitizeInlineNodes(Array.from(node.childNodes)) + "</" + tag + ">";
            }}
            if (tag === "a") {{
              const href = sanitizeUrl(node.getAttribute("href") || node.textContent || "");
              const inner = sanitizeInlineNodes(Array.from(node.childNodes)) || escapeHtml(node.textContent || href);
              if (!href) {{
                return inner;
              }}
              return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + inner + "</a>";
            }}
            return sanitizeInlineNodes(Array.from(node.childNodes));
          }}

          function serializeFallback(node) {{
            const text = normalizeInlineText(node.textContent || "");
            if (!text) {{
              return null;
            }}
            return {{
              kind: "paragraph",
              text,
              level: 0,
              html: escapeHtml(text).replace(/\\n/g, "<br>"),
              align: detectBlockAlign(node)
            }};
          }}

          function serializeParagraph(node) {{
            const html = sanitizeInlineNodes(Array.from(node.childNodes)).trim();
            const text = htmlToText(html);
            if (!text) {{
              return serializeFallback(node);
            }}
            return {{
              kind: "paragraph",
              text,
              level: 0,
              html,
              align: detectBlockAlign(node)
            }};
          }}

          function serializeHeading(node) {{
            const text = normalizeInlineText(node.textContent || "");
            if (!text) {{
              return null;
            }}
            const tag = node.tagName.toLowerCase();
            const level = tag === "h3" ? 3 : tag === "h1" ? 1 : 2;
            return {{
              kind: "heading",
              text,
              level,
              html: "",
              align: detectBlockAlign(node)
            }};
          }}

          function serializeDivider() {{
            return {{
              kind: "divider",
              text: "---",
              level: 0,
              html: "",
              align: "left"
            }};
          }}

          function serializeQuote(node) {{
            const directParagraphs = Array.from(node.children).filter((child) => child.tagName && child.tagName.toLowerCase() === "p");
            const inner = directParagraphs.length
              ? directParagraphs.map((child) => {{
                  const paragraph = serializeParagraph(child);
                  return paragraph ? "<p>" + paragraph.html + "</p>" : "";
                }}).join("")
              : (() => {{
                  const paragraph = serializeParagraph(node);
                  return paragraph ? "<p>" + paragraph.html + "</p>" : "";
                }})();
            const text = htmlToText(inner);
            if (!text) {{
              return null;
            }}
            return {{
              kind: "quote",
              text,
              level: 0,
              html: inner,
              align: detectBlockAlign(node)
            }};
          }}

          function serializeList(node) {{
            const tag = node.tagName.toLowerCase() === "ol" ? "ol" : "ul";
            const items = Array.from(node.children)
              .filter((child) => child.tagName && child.tagName.toLowerCase() === "li")
              .map((child) => sanitizeInlineNodes(Array.from(child.childNodes)).trim())
              .filter(Boolean);
            if (!items.length) {{
              return null;
            }}
            const html = "<" + tag + ">" + items.map((item) => "<li>" + item + "</li>").join("") + "</" + tag + ">";
            return {{
              kind: "list",
              text: items.map((item) => htmlToText(item)).join(" • "),
              level: tag === "ol" ? 1 : 0,
              html,
              align: detectBlockAlign(node)
            }};
          }}

          function collectEditorBlocks(editorHtml) {{
            const blocks = [];
            const probe = document.createElement("div");
            probe.innerHTML = String(editorHtml || "");
            const nodes = Array.from(probe.childNodes);
            if (!nodes.length && normalizeInlineText(probe.textContent || "")) {{
              const fallback = serializeParagraph(probe);
              return fallback ? [fallback] : [];
            }}

            nodes.forEach((node) => {{
              if (node.nodeType === Node.TEXT_NODE) {{
                const text = normalizeInlineText(node.textContent || "");
                if (text) {{
                  blocks.push({{
                    kind: "paragraph",
                    text,
                    level: 0,
                    html: escapeHtml(text)
                  }});
                }}
                return;
              }}
              if (node.nodeType !== Node.ELEMENT_NODE) {{
                return;
              }}
              const tag = node.tagName.toLowerCase();
              let block = null;
              if (tag === "h1" || tag === "h2" || tag === "h3") {{
                block = serializeHeading(node);
              }} else if (tag === "hr") {{
                block = serializeDivider();
              }} else if (tag === "blockquote") {{
                block = serializeQuote(node);
              }} else if (tag === "ul" || tag === "ol") {{
                block = serializeList(node);
              }} else if (tag === "div" && node.children.length === 1 && (node.children[0].tagName.toLowerCase() === "ul" || node.children[0].tagName.toLowerCase() === "ol")) {{
                block = serializeList(node.children[0]);
                if (block) {{
                  block.align = detectBlockAlign(node);
                }}
              }} else {{
                block = serializeFallback(node);
              }}
              if (block) {{
                blocks.push(block);
              }}
            }});
            return blocks;
          }}

          function inlineHtmlToMarkup(html) {{
            let markup = String(html || "").trim();
            markup = markup.replace(/<br\\s*\\/?>/gi, "\\n");
            markup = markup.replace(/<sup>\\s*(\\[[^\\]]+\\])\\s*<\\/sup>/gi, "$1");
            markup = markup.replace(/<a [^>]*href="([^"]+)"[^>]*>(.*?)<\\/a>/gi, "$2 ($1)");
            markup = markup.replace(/<(strong|b)>(.*?)<\\/\\1>/gi, "**$2**");
            markup = markup.replace(/<(em|i)>(.*?)<\\/\\1>/gi, "*$2*");
            markup = markup.replace(/<u>(.*?)<\\/u>/gi, "$1");
            markup = markup.replace(/<[^>]+>/g, "");
            return normalizeMultilineText(markup).trim();
          }}

          function blocksToLegacyMarkup(blocks) {{
            return blocks.map((block) => {{
              if (block.kind === "heading") {{
                const prefix = block.level >= 3 ? "### " : block.level === 1 ? "# " : "## ";
                return prefix + normalizeInlineText(block.text);
              }}
              if (block.kind === "list") {{
                const probe = document.createElement("div");
                probe.innerHTML = block.html || "";
                const items = Array.from(probe.querySelectorAll("li"))
                  .map((item, index) => {{
                    const text = normalizeInlineText(item.textContent || "");
                    return block.level > 0 ? String(index + 1) + ". " + text : "- " + text;
                  }})
                  .filter(Boolean);
                return items.join("\\n");
              }}
              if (block.kind === "quote") {{
                return inlineHtmlToMarkup(block.html || block.text)
                  .split("\\n")
                  .map((line) => line ? "> " + line : ">")
                  .join("\\n");
              }}
              return inlineHtmlToMarkup(block.html || block.text);
            }}).filter(Boolean).join("\\n\\n").trim();
          }}

          function renderLegacyMarkup(markup) {{
            const value = normalizeMultilineText(markup).trim();
            if (!value) {{
              return "";
            }}
            return value.split(/\\n\\s*\\n/g).map((chunk) => {{
              const piece = chunk.trim();
              if (!piece) {{
                return "";
              }}
              if (piece.startsWith("### ")) {{
                return "<h3>" + escapeHtml(piece.slice(4)) + "</h3>";
              }}
              if (piece.startsWith("## ")) {{
                return "<h2>" + escapeHtml(piece.slice(3)) + "</h2>";
              }}
              if (piece.startsWith("# ")) {{
                return "<h2>" + escapeHtml(piece.slice(2)) + "</h2>";
              }}
              if (piece.startsWith("- ")) {{
                const items = piece.split("\\n").map((line) => line.replace(/^-\\s*/, "").trim()).filter(Boolean);
                return "<ul>" + items.map((item) => "<li>" + escapeHtml(item) + "</li>").join("") + "</ul>";
              }}
              if (/^>\\s*/.test(piece)) {{
                const html = piece
                  .split("\\n")
                  .map((line) => line.replace(/^>\\s?/, ""))
                  .filter(Boolean)
                  .map((line) => "<p>" + escapeHtml(line) + "</p>")
                  .join("");
                return "<blockquote>" + html + "</blockquote>";
              }}
              let html = escapeHtml(piece);
              html = html.replace(/\\*\\*(.+?)\\*\\*/gs, "<strong>$1</strong>");
              html = html.replace(/(?<!\\*)\\*(?!\\*)(.+?)(?<!\\*)\\*(?!\\*)/gs, "<em>$1</em>");
              html = html.replace(/\\[(\\d+)\\]/g, "<sup>[$1]</sup>");
              return "<p>" + html.replace(/\\n/g, "<br>") + "</p>";
            }}).join("");
          }}

          function getEditorInstance() {{
            return window.barraventoEditor || null;
          }}

          function getCreateEditorInstance() {{
            return window.barraventoCreateEditor || null;
          }}

          function registerRichEditorFormats() {{
            if (!window.Quill || window.__barraventoQuillFormatsRegistered) {{
              return;
            }}
            const sizeStyle = window.Quill.import("attributors/style/size");
            const fontStyle = window.Quill.import("attributors/style/font");
            const alignStyle = window.Quill.import("attributors/style/align");
            sizeStyle.whitelist = ["12px", "14px", "16px", "17px", "18px", "20px", "24px", "28px", "32px", "36px"];
            window.Quill.register(sizeStyle, true);
            window.Quill.register(fontStyle, true);
            window.Quill.register(alignStyle, true);
            window.__barraventoQuillFormatsRegistered = true;
          }}

          function getEditorHtml() {{
            const editor = getEditorInstance();
            if (editor) {{
              return repairText(editor.root.innerHTML);
            }}
            return repairText(pendingEditorHtml || editBodyEditor.innerHTML || "");
          }}

          function updateEditorSummary(html, blocks) {{
            const text = normalizeMultilineText(
              String(html || "")
                .replace(/<br\\s*\\/?>/gi, "\\n")
                .replace(/<\\/(p|li|blockquote|ul|ol|h[1-6]|tr|div|pre|table)>/gi, "\\n")
                .replace(/<[^>]+>/g, " ")
            ).trim();
            const words = text ? text.split(/\\s+/).filter(Boolean).length : 0;
            const chars = text.length;
            const reading = Math.max(1, Math.ceil(words / 220));
            if (editorCharCount) {{
              editorCharCount.textContent = String(chars);
            }}
            if (editorWordCount) {{
              editorWordCount.textContent = String(words);
            }}
            if (editorReadingTime) {{
              editorReadingTime.textContent = reading + " min";
            }}
            if (editorBlockCount) {{
              editorBlockCount.textContent = String(blocks.length);
            }}
            if (editorStatusText) {{
              editorStatusText.textContent = words
                ? "Editor pronto para aprovar, exportar e publicar."
                : "O texto sera preservado com HTML rico e enviado para aprovacao.";
            }}
            if (editorSummaryPreview) {{
              editorSummaryPreview.textContent = text
                ? text.slice(0, 220) + (text.length > 220 ? "..." : "")
                : "Comece a escrever para ver uma previa curta do conteudo.";
            }}
          }}

          function serializeEditorHtml(html, bodyInput, bodyHtmlInput, bodyBlocksInput) {{
            const blocks = collectEditorBlocks(String(html || "").trim());
            bodyHtmlInput.value = String(html || "").trim();
            bodyBlocksInput.value = JSON.stringify(blocks);
            bodyInput.value = blocksToLegacyMarkup(blocks);
            return blocks;
          }}

          function getCreateEditorHtml() {{
            const editor = getCreateEditorInstance();
            if (editor) {{
              return repairText(editor.root.innerHTML);
            }}
            return repairText(pendingCreateEditorHtml || createBodyEditor.innerHTML || "");
          }}

          function applyHtmlToQuill(editor, html) {{
            if (!editor) {{
              return;
            }}
            const safeHtml = repairText(String(html || ""));
            if (!safeHtml.trim()) {{
              editor.setText("");
              return;
            }}
            try {{
              const converted = editor.clipboard && typeof editor.clipboard.convert === "function"
                ? editor.clipboard.convert({{
                    html: safeHtml,
                    text: htmlToText(safeHtml)
                  }})
                : null;
              if (converted && typeof editor.setContents === "function") {{
                editor.setContents(converted, "silent");
                if (typeof editor.setSelection === "function") {{
                  editor.setSelection(0, 0, "silent");
                }}
                return;
              }}
            }} catch (_error) {{}}
            try {{
              if (editor.clipboard && typeof editor.clipboard.dangerouslyPasteHTML === "function") {{
                editor.clipboard.dangerouslyPasteHTML(safeHtml, "silent");
                return;
              }}
            }} catch (_error) {{}}
            if (editor.root) {{
              editor.root.innerHTML = safeHtml;
            }}
          }}

          function setCreateEditorHtml(html) {{
            pendingCreateEditorHtml = repairText(String(html || ""));
            const editor = getCreateEditorInstance();
            if (editor) {{
              applyHtmlToQuill(editor, pendingCreateEditorHtml);
            }} else if (createBodyEditor) {{
              createBodyEditor.innerHTML = pendingCreateEditorHtml;
            }}
            syncCreateBodyFields();
          }}

          function syncCreateBodyFields() {{
            const blocks = serializeEditorHtml(getCreateEditorHtml(), createBodyInput, createBodyHtmlInput, createBodyBlocksInput);
            updateCreateSubmitState();
            return blocks;
          }}

          function setEditorHtml(html) {{
            pendingEditorHtml = repairText(String(html || ""));
            const editor = getEditorInstance();
            if (editor) {{
              applyHtmlToQuill(editor, pendingEditorHtml);
            }} else if (editBodyEditor) {{
              editBodyEditor.innerHTML = pendingEditorHtml;
            }}
            syncEditBodyFields();
          }}

          function syncEditBodyFields() {{
            const html = getEditorHtml().trim();
            const blocks = serializeEditorHtml(html, editBodyInput, editBodyHtmlInput, editBodyBlocksInput);
            updateEditorSummary(html, blocks);
            return blocks;
          }}

          function syncCategoryCombobox(form) {{
            const box = form.querySelector("[data-category-combobox]");
            const select = form.querySelector('select[name="categories"]');
            if (!box || !select) {{
              return;
            }}
            const selected = Array.from(select.selectedOptions).map((option) => option.value);
            box.querySelectorAll("[data-category-checkbox]").forEach((input) => {{
              input.checked = selected.includes(input.value);
            }});
            const label = box.querySelector(".category-combobox__label");
            const summary = box.querySelector("[data-category-summary]");
            if (label) {{
              label.textContent = !selected.length
                ? "Selecionar categorias"
                : selected.length <= 2
                  ? selected.join(", ")
                  : selected.length + " categorias selecionadas";
            }}
            if (summary) {{
              summary.hidden = selected.length === 0;
              summary.innerHTML = selected.length
                ? selected.map((item) => '<span class="category-combobox__tag">' + escapeHtml(item) + '</span>').join("")
                : "";
            }}
            box.classList.toggle("has-selection", selected.length > 0);
            if (form === createForm) {{
              updateCreateSubmitState();
            }}
          }}

          function setCheckedValues(form, values) {{
            const items = new Set(values);
            const select = form.querySelector('select[name="categories"]');
            if (!select) {{
              return;
            }}
            for (const option of select.options) {{
              option.selected = items.has(option.value);
            }}
            syncCategoryCombobox(form);
          }}

          function getCheckedValues(form) {{
            const select = form.querySelector('select[name="categories"]');
            if (!select) {{
              return [];
            }}
            return Array.from(select.selectedOptions).map((option) => option.value);
          }}

          function formField(form, name) {{
            return form ? form.querySelector('[name="' + name + '"]') : null;
          }}

          function csv(values) {{
            return values.join(", ");
          }}

          function setMultiSelectValues(select, values) {{
            if (!select) {{
              return;
            }}
            const selected = new Set((Array.isArray(values) ? values : []).map((item) => String(item || "")));
            Array.from(select.options).forEach((option) => {{
              option.selected = selected.has(option.value);
            }});
            const memberBox = select.closest("[data-member-combobox]");
            if (memberBox) {{
              syncMemberCombobox(memberBox);
            }}
          }}

          function getMultiSelectValues(select) {{
            if (!select) {{
              return [];
            }}
            return Array.from(select.selectedOptions).map((option) => option.value);
          }}

          function syncMemberCombobox(box) {{
            if (!box) {{
              return;
            }}
            const select = box.querySelector('select[name="author_members"]');
            if (!select) {{
              return;
            }}
            const selectedOptions = Array.from(select.selectedOptions);
            const selectedValues = selectedOptions.map((option) => option.value);
            box.querySelectorAll("[data-member-checkbox]").forEach((input) => {{
              input.checked = selectedValues.includes(input.value);
            }});
            const selectedNames = selectedOptions.map((option) => option.textContent.trim()).filter(Boolean);
            const label = box.querySelector(".category-combobox__label");
            const summary = box.querySelector("[data-member-summary]");
            if (label) {{
              label.textContent = !selectedNames.length
                ? "Selecionar integrantes"
                : selectedNames.length <= 2
                  ? selectedNames.join(", ")
                  : selectedNames.length + " integrantes selecionados";
            }}
            if (summary) {{
              summary.hidden = selectedNames.length === 0;
              summary.innerHTML = selectedNames.length
                ? selectedNames.map((item) => '<span class="category-combobox__tag">' + escapeHtml(item) + '</span>').join("")
                : "";
            }}
            box.classList.toggle("has-selection", selectedNames.length > 0);
          }}

          function renderMemberSelectOptions() {{
            const memberOptions = memberDirectory.map((item) => '<option value="' + escapeHtml(item.email || "") + '">' + escapeHtml(item.name || item.email || "") + '</option>');
            const memberCheckboxes = memberDirectory.map((item) =>
              '<label class="category-combobox__option">' +
                '<input type="checkbox" value="' + escapeHtml(item.email || "") + '" data-member-checkbox>' +
                '<span>' + escapeHtml(item.name || item.email || "") + '</span>' +
              '</label>'
            );
            const officeOptions = ['Opcao A', 'Opcao B', 'Opcao C'].map((value) => '<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>');
            const createAuthorMembers = document.getElementById("create-author-members");
            const editAuthorMembers = document.getElementById("edit-author-members");
            const profileEditorialRole = document.getElementById("profile-editorial-role");
            if (createAuthorMembers) {{
              const selected = getMultiSelectValues(createAuthorMembers);
              createAuthorMembers.innerHTML = memberOptions.join("");
              setMultiSelectValues(createAuthorMembers, selected);
            }}
            if (editAuthorMembers) {{
              const selected = getMultiSelectValues(editAuthorMembers);
              editAuthorMembers.innerHTML = memberOptions.join("");
              setMultiSelectValues(editAuthorMembers, selected);
            }}
            document.querySelectorAll("[data-member-options]").forEach((node) => {{
              node.innerHTML = memberCheckboxes.length
                ? memberCheckboxes.join("")
                : '<div class="empty-state empty-state--compact"><p>Nenhum integrante aprovado ainda.</p></div>';
              const box = node.closest("[data-member-combobox]");
              if (box) {{
                syncMemberCombobox(box);
              }}
            }});
            if (profileEditorialRole) {{
              profileEditorialRole.innerHTML = officeOptions.join("");
            }}
          }}

          function renderProfilePreview(payload) {{
            if (!profilePreview) {{
              return;
            }}
            const memberName = String(payload && payload.name || "").trim();
            const editorialRole = String(payload && payload.editorial_role || "").trim();
            const education = String(payload && payload.education || "").trim();
            const photoUrl = String(payload && payload.photo_url || "").trim();
            profilePreview.innerHTML = (
              '<article class="member-directory-card member-directory-card--preview">' +
                (photoUrl ? '<figure class="member-directory-card__photo"><img src="' + escapeHtml(photoUrl) + '" alt="' + escapeHtml(memberName || "Perfil") + '"></figure>' : '') +
                '<div class="member-directory-card__body">' +
                  '<h3>' + escapeHtml(memberName || "Seu nome") + '</h3>' +
                  '<p>' + escapeHtml(editorialRole || "Cargo na revista") + '</p>' +
                  '<span>' + escapeHtml(education || "Formacao nao informada.") + '</span>' +
                '</div>' +
              '</article>'
            );
          }}

          function syncAuthorFieldWithMembers(form) {{
            return;
          }}

          function activateMemberComboboxes() {{
            document.querySelectorAll("[data-member-combobox]").forEach((box) => {{
              const select = box.querySelector('select[name="author_members"]');
              const toggle = box.querySelector(".category-combobox__toggle");
              const menu = box.querySelector(".category-combobox__menu");
              const search = box.querySelector("[data-member-search]");
              if (!select || !toggle || !menu) {{
                return;
              }}

              syncMemberCombobox(box);

              toggle.addEventListener("click", () => {{
                const nextOpen = menu.hidden;
                document.querySelectorAll("[data-member-combobox] .category-combobox__menu").forEach((node) => {{
                  node.hidden = true;
                  const owner = node.closest("[data-member-combobox]");
                  if (owner) {{
                    owner.classList.remove("is-open");
                    owner.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                  }}
                }});
                menu.hidden = !nextOpen;
                box.classList.toggle("is-open", nextOpen);
                toggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
                if (nextOpen && search) {{
                  search.focus();
                }}
              }});

              box.addEventListener("change", (event) => {{
                const target = event.target;
                if (!(target instanceof HTMLInputElement) || !target.matches("[data-member-checkbox]")) {{
                  return;
                }}
                const lookup = new Set(
                  Array.from(box.querySelectorAll("[data-member-checkbox]:checked")).map((item) => item.value)
                );
                Array.from(select.options).forEach((option) => {{
                  option.selected = lookup.has(option.value);
                }});
                syncMemberCombobox(box);
                const form = box.closest("form");
                if (form) {{
                  syncAuthorFieldWithMembers(form);
                  clearStatus(form === editForm ? editStatus : createStatus);
                }}
              }});

              if (search) {{
                search.addEventListener("input", () => {{
                  const query = normalizeInlineText(search.value).toLowerCase();
                  box.querySelectorAll(".category-combobox__option").forEach((option) => {{
                    const text = normalizeInlineText(option.textContent || "").toLowerCase();
                    option.classList.toggle("is-hidden", Boolean(query) && !text.includes(query));
                  }});
                }});
              }}
            }});

            document.addEventListener("click", (event) => {{
              if (event.target.closest("[data-member-combobox]")) {{
                return;
              }}
              document.querySelectorAll("[data-member-combobox] .category-combobox__menu").forEach((menu) => {{
                menu.hidden = true;
                const box = menu.closest("[data-member-combobox]");
                if (box) {{
                  box.classList.remove("is-open");
                  box.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                }}
              }});
            }});
          }}

          function activateCategoryComboboxes() {{
            document.querySelectorAll("[data-category-combobox]").forEach((box) => {{
              const form = box.closest("form");
              const select = form ? form.querySelector('select[name="categories"]') : null;
              const toggle = box.querySelector(".category-combobox__toggle");
              const menu = box.querySelector(".category-combobox__menu");
              const search = box.querySelector("[data-category-search]");
              if (!form || !select || !toggle || !menu) {{
                return;
              }}

              syncCategoryCombobox(form);

              toggle.addEventListener("click", () => {{
                const nextOpen = menu.hidden;
                document.querySelectorAll("[data-category-combobox] .category-combobox__menu").forEach((node) => {{
                  node.hidden = true;
                  const owner = node.closest("[data-category-combobox]");
                  if (owner) {{
                    owner.classList.remove("is-open");
                    owner.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                  }}
                }});
                menu.hidden = !nextOpen;
                box.classList.toggle("is-open", nextOpen);
                toggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
                if (nextOpen && search) {{
                  search.focus();
                }}
              }});

              box.querySelectorAll("[data-category-checkbox]").forEach((input) => {{
                input.addEventListener("change", () => {{
                  const lookup = new Set(
                    Array.from(box.querySelectorAll("[data-category-checkbox]:checked")).map((item) => item.value)
                  );
                  Array.from(select.options).forEach((option) => {{
                    option.selected = lookup.has(option.value);
                  }});
                  syncCategoryCombobox(form);
                  clearStatus(form === editForm ? editStatus : createStatus);
                }});
              }});

              if (search) {{
                search.addEventListener("input", () => {{
                  const query = normalizeInlineText(search.value).toLowerCase();
                  box.querySelectorAll(".category-combobox__option").forEach((option) => {{
                    const text = normalizeInlineText(option.textContent || "").toLowerCase();
                    option.classList.toggle("is-hidden", Boolean(query) && !text.includes(query));
                  }});
                }});
              }}
            }});

            document.addEventListener("click", (event) => {{
              if (event.target.closest("[data-category-combobox]")) {{
                return;
              }}
              document.querySelectorAll("[data-category-combobox] .category-combobox__menu").forEach((menu) => {{
                menu.hidden = true;
                const box = menu.closest("[data-category-combobox]");
                if (box) {{
                  box.classList.remove("is-open");
                  box.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                }}
              }});
            }});
          }}

          function currentEditState() {{
            const blocks = syncEditBodyFields();
            const titleField = formField(editForm, "title");
            const authorField = formField(editForm, "author");
            const authorMembersField = formField(editForm, "author_members");
            const summaryField = formField(editForm, "summary");
            const tagsField = formField(editForm, "tags");
            const hashtagsField = formField(editForm, "hashtags");
            return {{
              title: titleField ? titleField.value.trim() : "",
              author: authorField ? authorField.value.trim() : "",
              authorMembers: getMultiSelectValues(authorMembersField),
              summary: summaryField ? summaryField.value.trim() : "",
              body: editBodyInput.value.trim(),
              bodyHtml: editBodyHtmlInput.value.trim(),
              bodyBlocks: JSON.stringify(blocks),
              tags: tagsField ? tagsField.value.trim() : "",
              hashtags: hashtagsField ? hashtagsField.value.trim() : "",
              categories: getCheckedValues(editForm)
            }};
          }}

          function sameState(left, right) {{
            return JSON.stringify(left) === JSON.stringify(right);
          }}

          function setActiveTab(name) {{
            memberTabs.forEach((button) => {{
              const active = button.dataset.memberTab === name;
              button.classList.toggle("is-active", active);
            }});
            memberTabPanels.forEach((panel) => {{
              const active = panel.dataset.memberTabPanel === name;
              panel.classList.toggle("is-active", active);
              panel.hidden = false;
              panel.style.display = active ? "block" : "none";
              panel.setAttribute("aria-hidden", active ? "false" : "true");
            }});
          }}

          function restrictedTabNames() {{
            return ["approvals", "logs", "members"];
          }}

          function syncRestrictedTabs() {{
            memberTabs.forEach((button) => {{
              const restricted = restrictedTabNames().includes(String(button.dataset.memberTab || "")) && (!member || member.role !== "admin");
              button.classList.toggle("is-restricted", restricted);
              button.title = restricted ? "Disponivel apenas para o Conselho Editorial." : "";
            }});
          }}

          function downloadEditorFile(filename, content, mime) {{
            const blob = new Blob([content], {{ type: mime }});
            const href = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = href;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(href), 150);
          }}

          function bindFontSizeControl(editor, select) {{
            if (!editor || !select) {{
              return;
            }}
            const sync = (range) => {{
              const editorHasFocus = typeof editor.hasFocus === "function" ? editor.hasFocus() : false;
              if (range === null || !editorHasFocus) {{
                select.value = "17px";
                return;
              }}
              const activeRange = range || (typeof editor.getSelection === "function" ? editor.getSelection() : null);
              const format = typeof editor.getFormat === "function" ? editor.getFormat(activeRange || undefined) : {{}};
              const current = String(format.size || "").trim();
              if (current && Array.from(select.options).some((option) => option.value === current)) {{
                select.value = current;
              }} else {{
                select.value = "17px";
              }}
            }};
            select.addEventListener("change", () => {{
              const value = String(select.value || "").trim() || "17px";
              editor.format("size", value, "user");
            }});
            editor.on("selection-change", (range) => sync(range));
            editor.on("text-change", () => sync());
            sync();
          }}

          function activateRichEditor() {{
            if (!editBodyEditor || !window.Quill) {{
              return Promise.resolve();
            }}
            if (window.barraventoEditor) {{
              editorReady = Promise.resolve(window.barraventoEditor);
              return editorReady;
            }}
            if (editorReady) {{
              return editorReady;
            }}
            if (editorToolbar) {{
              editorToolbar.remove();
            }}
            registerRichEditorFormats();
            const toolbarOptions = [
              [{{ header: [1, 2, 3, false] }}],
              [{{ font: [] }}],
              ["bold", "italic", "underline", "strike"],
              [{{ script: "sub" }}, {{ script: "super" }}],
              [{{ color: [] }}, {{ background: [] }}],
              [{{ align: [] }}],
              [{{ list: "ordered" }}, {{ list: "bullet" }}, {{ indent: "-1" }}, {{ indent: "+1" }}],
              ["blockquote", "code-block"],
              ["link", "image", "video"],
              ["clean"]
            ];
            const quill = new window.Quill(editBodyEditor, {{
              theme: "snow",
              placeholder: "Escreva o texto aqui com a mesma liberdade de um editor completo.",
              formats: ["header", "font", "size", "bold", "italic", "underline", "strike", "script", "color", "background", "align", "list", "indent", "blockquote", "code-block", "link", "image", "video"],
              modules: {{
                toolbar: toolbarOptions,
                history: {{
                  delay: 350,
                  maxStack: 200,
                  userOnly: true
                }}
              }}
            }});
            window.barraventoEditor = quill;
            editorReady = Promise.resolve(quill);
            if (pendingEditorHtml) {{
              applyHtmlToQuill(quill, pendingEditorHtml);
            }}
            bindFontSizeControl(quill, document.getElementById("edit-font-size"));
            quill.on("text-change", () => {{
              syncEditBodyFields();
              clearStatus(editStatus);
            }});
            quill.root.addEventListener("blur", () => syncEditBodyFields());

            if (editorSpellcheckToggle) {{
              editorSpellcheckToggle.addEventListener("change", () => {{
                const editor = getEditorInstance();
                if (!editor || !editor.root) {{
                  return;
                }}
                editor.root.setAttribute("spellcheck", editorSpellcheckToggle.checked ? "true" : "false");
              }});
            }}
            quill.root.setAttribute("spellcheck", editorSpellcheckToggle && editorSpellcheckToggle.checked ? "true" : "false");

            if (editorPreviewButton) {{
              editorPreviewButton.addEventListener("click", () => {{
                const html = getEditorHtml();
                const preview = window.open("", "_blank", "noopener,noreferrer,width=1100,height=760");
                if (!preview) {{
                  return;
                }}
                preview.document.write("<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><title>Visualizacao do texto</title><style>body{{font-family:Georgia,serif;max-width:900px;margin:40px auto;padding:0 20px;color:#2a201d;line-height:1.8}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #d9d3cb;padding:8px}}blockquote{{border-left:3px solid #8d2f23;padding-left:16px;color:#5a4741}}pre{{background:#f7f1ea;padding:12px;border-radius:12px;overflow:auto}}</style></head><body><h1>" + escapeHtml(editForm.title.value.trim() || "Visualizacao") + "</h1>" + html + "</body></html>");
                preview.document.close();
              }});
            }}

            if (editorExportHtmlButton) {{
              editorExportHtmlButton.addEventListener("click", () => {{
                downloadEditorFile((editForm.title.value.trim() || "texto") + ".html", getEditorHtml(), "text/html;charset=utf-8");
              }});
            }}

            if (editorExportTxtButton) {{
              editorExportTxtButton.addEventListener("click", () => {{
                downloadEditorFile((editForm.title.value.trim() || "texto") + ".txt", htmlToText(getEditorHtml()), "text/plain;charset=utf-8");
              }});
            }}

            syncEditBodyFields();
            return editorReady;
          }}

          function activateCreateRichEditor() {{
            if (!createBodyEditor || !window.Quill) {{
              return Promise.resolve();
            }}
            if (window.barraventoCreateEditor) {{
              createEditorReady = Promise.resolve(window.barraventoCreateEditor);
              return createEditorReady;
            }}
            if (createEditorReady) {{
              return createEditorReady;
            }}
            registerRichEditorFormats();
            const toolbarOptions = [
              [{{ header: [1, 2, 3, false] }}],
              [{{ font: [] }}],
              ["bold", "italic", "underline", "strike"],
              [{{ script: "sub" }}, {{ script: "super" }}],
              [{{ color: [] }}, {{ background: [] }}],
              [{{ align: [] }}],
              [{{ list: "ordered" }}, {{ list: "bullet" }}, {{ indent: "-1" }}, {{ indent: "+1" }}],
              ["blockquote", "code-block"],
              ["link", "image", "video"],
              ["clean"]
            ];
            const quill = new window.Quill(createBodyEditor, {{
              theme: "snow",
              placeholder: "Importe o DOCX e revise o texto aqui antes de publicar.",
              formats: ["header", "font", "size", "bold", "italic", "underline", "strike", "script", "color", "background", "align", "list", "indent", "blockquote", "code-block", "link", "image", "video"],
              modules: {{
                toolbar: toolbarOptions,
                history: {{
                  delay: 350,
                  maxStack: 200,
                  userOnly: true
                }}
              }}
            }});
            window.barraventoCreateEditor = quill;
            createEditorReady = Promise.resolve(quill);
            if (pendingCreateEditorHtml) {{
              applyHtmlToQuill(quill, pendingCreateEditorHtml);
            }}
            bindFontSizeControl(quill, document.getElementById("create-font-size"));
            quill.on("text-change", () => {{
              syncCreateBodyFields();
              clearStatus(createStatus);
            }});
            quill.root.setAttribute("spellcheck", "true");
            syncCreateBodyFields();
            return createEditorReady;
          }}

          function requireMember(statusNode) {{
            if (member) {{
              return true;
            }}
            setStatus(statusNode, "error", "Entre como membro para liberar esta operacao.");
            return false;
          }}

          function formatDateTime(value) {{
            const stamp = String(value || "").trim();
            if (!stamp) {{
              return "";
            }}
            const parsed = new Date(stamp);
            if (Number.isNaN(parsed.getTime())) {{
              return escapeHtml(stamp);
            }}
            return escapeHtml(new Intl.DateTimeFormat("pt-BR", {{
              dateStyle: "long",
              timeStyle: "short"
            }}).format(parsed));
          }}

          function formatMessage(value) {{
            return escapeHtml(value).replace(/\\n/g, "<br>");
          }}

          function submissionKindLabel(kind) {{
            if (kind === "edit") {{
              return "Edicao pendente";
            }}
            if (kind === "delete") {{
              return "Exclusao pendente";
            }}
            return "Inclusao pendente";
          }}

          function submissionApprovalVariant(kind) {{
            if (kind === "edit") {{
              return "edit";
            }}
            if (kind === "delete") {{
              return "delete";
            }}
            return "create";
          }}

          function submissionApproveLabel(kind) {{
            if (kind === "edit") {{
              return "Aprovar edicao";
            }}
            if (kind === "delete") {{
              return "Aprovar exclusao";
            }}
            return "Aprovar inclusao";
          }}

          function submissionRejectLabel(kind) {{
            if (kind === "edit") {{
              return "Recusar edicao";
            }}
            if (kind === "delete") {{
              return "Recusar exclusao";
            }}
            return "Recusar inclusao";
          }}

          function renderNotice(item) {{
            const variant = ["success", "danger"].includes(String(item.variant || "").trim()) ? String(item.variant).trim() : "neutral";
            const metaLabel = item.scope === "private" ? "Retorno do Conselho Editorial" : (item.author_name || "Membro");
            const title = String(item.title || "").trim();
            return (
              '<article class="member-notice member-notice--' + variant + '">' +
                '<div class="member-notice__meta">' +
                  '<strong>' + escapeHtml(metaLabel) + '</strong>' +
                  '<span>' + formatDateTime(item.created_at || "") + '</span>' +
                '</div>' +
                (title ? '<h4 class="member-notice__title">' + escapeHtml(title) + '</h4>' : '') +
                '<p>' + formatMessage(item.message || "") + '</p>' +
              '</article>'
            );
          }}

          function renderDashboard(payload) {{
            const items = payload && Array.isArray(payload.items) ? payload.items : [];
            const totals = payload && payload.totals ? payload.totals : {{ views: 0, pdf_downloads: 0 }};
            const series = payload && Array.isArray(payload.series) ? payload.series : [];
            const locations = payload && Array.isArray(payload.locations) ? payload.locations : [];
            const periodLabel = payload && payload.period ? String(payload.period.label || "") : "Periodo atual";
            const metric = dashboardMetric ? String(dashboardMetric.value || "views") : "views";
            const chartKind = dashboardChartKind ? String(dashboardChartKind.value || "line") : "line";
            if (!items.length) {{
              dashboardList.innerHTML = '<div class="empty-state"><h3>Sem estatisticas ainda</h3><p>Os acessos e downloads vao aparecer aqui conforme o site for usado pelo servidor local.</p></div>';
              return;
            }}
            const metricLabel = metric === "pdf_downloads" ? "Downloads de PDF" : (metric === "locations" ? "Local dos acessos" : "Acessos");
            const metricValue = metric === "pdf_downloads" ? Number(totals.pdf_downloads || 0) : (metric === "locations" ? locations.length : Number(totals.views || 0));
            const activeChart = chartKind === "pie"
              ? renderDashboardPieChart(items, locations, metric)
              : renderDashboardLineChart(items, series, locations, metric);
            dashboardList.innerHTML = (
              '<div class="dashboard-summary">' +
                '<article class="dashboard-kpi"><strong>' + escapeHtml(periodLabel) + '</strong><span>' + escapeHtml(String(totals.views || 0)) + ' acessos</span></article>' +
                '<article class="dashboard-kpi"><strong>Downloads de PDF</strong><span>' + escapeHtml(String(totals.pdf_downloads || 0)) + ' downloads</span></article>' +
                '<article class="dashboard-kpi"><strong>' + escapeHtml(metricLabel) + '</strong><span>' + escapeHtml(String(metricValue || 0)) + (metric === "locations" ? ' locais' : ' no periodo') + '</span></article>' +
              '</div>' +
              '<section class="dashboard-chart-card dashboard-chart-card--solo"><div class="dashboard-chart-card__head"><h4>Grafico de ' + escapeHtml(chartKind === "pie" ? "pizza" : "linha") + '</h4><p>' + escapeHtml(metricLabel) + ' no periodo selecionado.</p></div>' + activeChart + '</section>' +
              '<div class="dashboard-table">' +
                '<div class="dashboard-row dashboard-row--head">' +
                  '<span>Texto</span><span>Acessos</span><span>PDFs</span><span>Publicacao</span>' +
                '</div>' +
                items.map((item) => {{
                  return (
                    '<div class="dashboard-row">' +
                      '<span><a href="' + escapeHtml(item.article_url) + '">' + escapeHtml(item.title) + '</a></span>' +
                      '<span>' + escapeHtml(String(item.views || 0)) + '</span>' +
                      '<span>' + escapeHtml(String(item.pdf_downloads || 0)) + '</span>' +
                      '<span>' + escapeHtml(item.published_label || "") + '</span>' +
                    '</div>'
                  );
                }}).join('') +
              '</div>'
            );
          }}

          function renderDashboardLineChart(items, series, locations, metric) {{
            if (metric === "locations") {{
              if (!locations.length) {{
                return '<div class="empty-state empty-state--compact"><h3>Sem localidade suficiente</h3><p>Quando houver acessos com localidade resolvida, os locais mais recorrentes aparecerao aqui.</p></div>';
              }}
              const width = 420;
              const height = 170;
              const padding = 20;
              const maxValue = Math.max(1, ...locations.map((item) => Number(item.value || 0)));
              const usableWidth = width - padding * 2;
              const usableHeight = height - padding * 2;
              const step = locations.length > 1 ? usableWidth / (locations.length - 1) : 0;
              const pathFor = locations.map((item, index) => {{
                const x = padding + (step * index);
                const y = height - padding - ((Number(item.value || 0) / maxValue) * usableHeight);
                return (index === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2);
              }}).join(' ');
              const labels = locations.map((item) => '<span>' + escapeHtml(String(item.label || '').length > 18 ? String(item.label || '').slice(0, 18) + '...' : String(item.label || '')) + '</span>').join('');
              const legend = locations.map((item) => '<li><i class="dashboard-swatch dashboard-swatch--views"></i><span>' + escapeHtml(item.label || '') + '</span><strong>' + escapeHtml(String(item.value || 0)) + '</strong></li>').join('');
              return (
                '<div class="dashboard-line-chart dashboard-line-chart--compact">' +
                  '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Grafico de linha de acessos por localidade">' +
                    '<path class="dashboard-line-chart__grid" d="M' + padding + ' ' + (height - padding) + ' H' + (width - padding) + '"></path>' +
                    '<path class="dashboard-line-chart__path dashboard-line-chart__path--views" d="' + pathFor + '"></path>' +
                  '</svg>' +
                  '<div class="dashboard-line-chart__legend"><span><i class="dashboard-swatch dashboard-swatch--views"></i>Locais com mais acessos</span></div>' +
                  '<div class="dashboard-line-chart__labels">' + labels + '</div>' +
                  '<ul class="dashboard-pie-chart__legend dashboard-pie-chart__legend--chart">' + legend + '</ul>' +
                '</div>'
              );
            }}
            if (!series.length) {{
              return '<div class="empty-state empty-state--compact"><h3>Sem historico suficiente</h3><p>Os pontos diarios vao aparecer aqui conforme o site for usado.</p></div>';
            }}
            const width = 420;
            const height = 170;
            const padding = 24;
            const key = metric === "pdf_downloads" ? "pdf_downloads" : "views";
            const values = series.map((item) => Number(item[key] || 0));
            const maxValue = Math.max(1, ...values);
            const usableWidth = width - padding * 2;
            const usableHeight = height - padding * 2;
            const step = series.length > 1 ? usableWidth / (series.length - 1) : 0;
            const pathFor = series.map((item, index) => {{
              const x = padding + (step * index);
              const y = height - padding - ((Number(item[key] || 0) / maxValue) * usableHeight);
              return (index === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2);
            }}).join(' ');
            const labels = [series[0], series[Math.floor((series.length - 1) / 2)], series[series.length - 1]]
              .filter(Boolean)
              .map((item) => '<span>' + escapeHtml(formatDateTime(String(item.label || '') + 'T12:00:00')) + '</span>')
              .filter((value, index, list) => list.indexOf(value) === index)
              .join('');
            const detailLegend = metric === "pdf_downloads"
              ? (() => {{
                  const topItems = items
                    .map((item) => ({{
                      label: String(item.title || "").trim(),
                      value: Number(item.pdf_downloads || 0)
                    }}))
                    .filter((item) => item.value > 0)
                    .sort((left, right) => right.value - left.value)
                    .slice(0, 5);
                  if (!topItems.length) {{
                    return '';
                  }}
                  return '<ul class="dashboard-pie-chart__legend dashboard-pie-chart__legend--chart">' + topItems.map((item) => '<li><i class="dashboard-swatch dashboard-swatch--pdfs"></i><span>' + escapeHtml(item.label) + '</span><strong>' + escapeHtml(String(item.value)) + '</strong></li>').join('') + '</ul>';
                }})()
              : '';
            return (
              '<div class="dashboard-line-chart dashboard-line-chart--compact">' +
                '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Grafico de linha do dashboard">' +
                  '<path class="dashboard-line-chart__grid" d="M' + padding + ' ' + (height - padding) + ' H' + (width - padding) + '"></path>' +
                  '<path class="dashboard-line-chart__path ' + (metric === "pdf_downloads" ? 'dashboard-line-chart__path--pdfs' : 'dashboard-line-chart__path--views') + '" d="' + pathFor + '"></path>' +
                '</svg>' +
                '<div class="dashboard-line-chart__legend"><span><i class="dashboard-swatch ' + (metric === "pdf_downloads" ? 'dashboard-swatch--pdfs' : 'dashboard-swatch--views') + '"></i>' + escapeHtml(metric === "pdf_downloads" ? "Downloads de PDF" : "Acessos") + '</span></div>' +
                '<div class="dashboard-line-chart__labels">' + labels + '</div>' +
                detailLegend +
              '</div>'
            );
          }}

          function renderDashboardPieChart(items, locations, metric) {{
            if (metric === "locations") {{
              if (!locations.length) {{
                return '<div class="empty-state empty-state--compact"><h3>Sem localidade suficiente</h3><p>Quando houver acessos com localidade resolvida, a distribuicao por cidade aparecera aqui.</p></div>';
              }}
              const colors = ['#8d2f23', '#c96a2f', '#d8a24e', '#6d8a77', '#3c5f79'];
              const total = locations.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
              let angle = -Math.PI / 2;
              const radius = 82;
              const center = 100;
              const slices = locations.map((item, index) => {{
                const portion = Number(item.value || 0) / total;
                const nextAngle = angle + (Math.PI * 2 * portion);
                const x1 = center + radius * Math.cos(angle);
                const y1 = center + radius * Math.sin(angle);
                const x2 = center + radius * Math.cos(nextAngle);
                const y2 = center + radius * Math.sin(nextAngle);
                const largeArc = portion > 0.5 ? 1 : 0;
                const path = 'M ' + center + ' ' + center + ' L ' + x1.toFixed(2) + ' ' + y1.toFixed(2) + ' A ' + radius + ' ' + radius + ' 0 ' + largeArc + ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + ' Z';
                angle = nextAngle;
                return {{ path, color: colors[index % colors.length], label: item.label, value: item.value }};
              }});
              return (
                '<div class="dashboard-pie-chart">' +
                  '<svg viewBox="0 0 200 200" role="img" aria-label="Grafico de pizza por localidade">' +
                    slices.map((slice) => '<path d="' + slice.path + '" fill="' + slice.color + '"></path>').join('') +
                  '</svg>' +
                  '<ul class="dashboard-pie-chart__legend">' +
                    slices.map((slice) => '<li><i class="dashboard-swatch" style="background:' + slice.color + '"></i><span>' + escapeHtml(slice.label || '') + '</span><strong>' + escapeHtml(String(slice.value || 0)) + '</strong></li>').join('') +
                  '</ul>' +
                '</div>'
              );
            }}
            if (!items.length) {{
              return '<div class="empty-state empty-state--compact"><h3>Sem distribuicao ainda</h3><p>Quando houver acessos no periodo, o grafico aparecera aqui.</p></div>';
            }}
            const colors = ['#8d2f23', '#c96a2f', '#d8a24e', '#6d8a77', '#3c5f79'];
            const key = metric === "pdf_downloads" ? "pdf_downloads" : "views";
            const topItems = items
              .map((item) => ({{
                label: item.title,
                value: Number(item[key] || 0)
              }}))
              .filter((item) => item.value > 0)
              .sort((left, right) => right.value - left.value)
              .slice(0, 5);
            if (!topItems.length) {{
              return '<div class="empty-state empty-state--compact"><h3>Sem distribuicao ainda</h3><p>Quando houver dados nesta modalidade, o grafico aparecera aqui.</p></div>';
            }}
            const total = topItems.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
            let angle = -Math.PI / 2;
            const radius = 82;
            const center = 100;
            const slices = topItems.map((item, index) => {{
              const portion = Number(item.value || 0) / total;
              const nextAngle = angle + (Math.PI * 2 * portion);
              const x1 = center + radius * Math.cos(angle);
              const y1 = center + radius * Math.sin(angle);
              const x2 = center + radius * Math.cos(nextAngle);
              const y2 = center + radius * Math.sin(nextAngle);
              const largeArc = portion > 0.5 ? 1 : 0;
              const path = 'M ' + center + ' ' + center + ' L ' + x1.toFixed(2) + ' ' + y1.toFixed(2) + ' A ' + radius + ' ' + radius + ' 0 ' + largeArc + ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + ' Z';
              angle = nextAngle;
              return {{
                path,
                color: colors[index % colors.length],
                label: item.label,
                value: item.value
              }};
            }});
            return (
              '<div class="dashboard-pie-chart">' +
                '<svg viewBox="0 0 200 200" role="img" aria-label="Grafico de pizza do dashboard">' +
                  slices.map((slice) => '<path d="' + slice.path + '" fill="' + slice.color + '"></path>').join('') +
                '</svg>' +
                '<ul class="dashboard-pie-chart__legend">' +
                  slices.map((slice) => '<li><i class="dashboard-swatch" style="background:' + slice.color + '"></i><span>' + escapeHtml(slice.label || '') + '</span><strong>' + escapeHtml(String(slice.value || 0)) + '</strong></li>').join('') +
                '</ul>' +
              '</div>'
            );
          }}

          function scrollToMemberPanel() {{
            if (window.location.hash !== "#member-panel") {{
              history.replaceState(null, "", "#member-panel");
            }}
            memberPanel.scrollIntoView({{ behavior: "smooth", block: "start" }});
          }}

          function openInitialMemberView() {{
            if (!member) {{
              return;
            }}
            setActiveTab("notices");
            loadNotices().catch((error) => {{
              setStatus(noticeStatus, "error", escapeHtml(error.message));
            }});
          }}

          function renderRegistrationApproval(item) {{
            return (
              '<article class="approval-card">' +
                '<div class="approval-card__header">' +
                  '<div>' +
                    '<span class="approval-card__eyebrow">Cadastro pendente</span>' +
                    '<h4>' + escapeHtml(item.name || item.email || "Cadastro") + '</h4>' +
                  '</div>' +
                  '<span class="approval-card__stamp">' + formatDateTime(item.created_at || "") + '</span>' +
                '</div>' +
                '<div class="approval-card__details">' +
                  '<span>' + escapeHtml(item.email || "") + '</span>' +
                  '<span>' + escapeHtml(item.role_label || "") + '</span>' +
                '</div>' +
                '<div class="approval-card__actions">' +
                  '<button class="button-link approval-action" type="button" data-approve-registration="' + escapeHtml(item.email || "") + '">Aprovar cadastro</button>' +
                '</div>' +
              '</article>'
            );
          }}

          function renderSubmissionApproval(item) {{
            const author = item.requested_by || {{}};
            const previewUrl = String(item.preview_url || "").trim();
            const kind = String(item.kind || "").trim();
            const variant = submissionApprovalVariant(kind);
            return (
              '<article class="approval-card approval-card--' + escapeHtml(variant) + '">' +
                '<div class="approval-card__header">' +
                  '<div>' +
                    '<span class="approval-card__eyebrow">' + escapeHtml(submissionKindLabel(kind)) + '</span>' +
                    '<h4>' + escapeHtml(item.title || item.slug || "Solicitacao") + '</h4>' +
                  '</div>' +
                  '<span class="approval-card__stamp">' + formatDateTime(item.requested_at || "") + '</span>' +
                '</div>' +
                '<div class="approval-card__details">' +
                  '<span>Solicitado por <strong>' + escapeHtml(author.name || author.email || "Membro") + '</strong></span>' +
                  '<span>' + escapeHtml(author.role_label || "") + '</span>' +
                '</div>' +
                '<label class="approval-reason">' +
                  '<span>Motivo da recusa</span>' +
                  '<textarea rows="2" placeholder="Explique brevemente o motivo." data-rejection-reason></textarea>' +
                '</label>' +
                '<div class="approval-card__actions">' +
                  (previewUrl ? '<a class="button-link button-link--ghost approval-action" href="' + escapeHtml(previewUrl) + '" target="_blank" rel="noopener noreferrer">Ver previa</a>' : '') +
                  '<button class="button-link approval-action" type="button" data-approve-submission="' + escapeHtml(item.id || "") + '">' + escapeHtml(submissionApproveLabel(kind)) + '</button>' +
                  '<button class="button-link button-link--ghost button-link--danger approval-action" type="button" data-reject-submission="' + escapeHtml(item.id || "") + '">' + escapeHtml(submissionRejectLabel(kind)) + '</button>' +
                '</div>' +
              '</article>'
            );
          }}

          function applyMemberState(nextMember) {{
            const wasAuthenticated = Boolean(member);
            member = nextMember;
            storePanelMemberState(member);
            const authenticated = Boolean(member);
            const shouldInitializePanel = authenticated && !wasAuthenticated;
            memberPanel.hidden = !authenticated;
            memberSession.hidden = !authenticated;
            memberLock.hidden = authenticated;
            if (memberAuthEntry) {{
              memberAuthEntry.hidden = authenticated;
            }}
            if (authenticated) {{
              memberSummary.innerHTML = "Conectado como <strong>" + escapeHtml(member.email || member.name || "Membro") + "</strong><br>" + escapeHtml(member.role_label || "");
              if (whoFormShell) {{
                whoFormShell.hidden = member.role !== "admin";
              }}
              if (shouldInitializePanel) {{
                openInitialMemberView();
              }}
              clearStatus(memberStatus);
              if (shouldInitializePanel) {{
                window.setTimeout(scrollToMemberPanel, 80);
              }}
            }} else {{
              memberSummary.textContent = "Assim que o login for confirmado, o painel editorial sera aberto abaixo.";
              noticeList.innerHTML = "";
              dashboardList.innerHTML = "";
              logsList.innerHTML = "";
              registrationApprovals.innerHTML = "";
              submissionApprovals.innerHTML = "";
              memberDirectory = [];
              renderMemberSelectOptions();
              renderProfilePreview({{}});
              if (whoFormShell) {{
                whoFormShell.hidden = true;
              }}
              clearStatus(memberStatus);
            }}
            syncRestrictedTabs();
            updateCreateSubmitState();
          }}

          async function readJson(response) {{
            return response.json().catch(() => ({{}}));
          }}

          async function fetchSession() {{
            const response = await fetch("/api/members/session", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            const effectiveMember = payload.authenticated ? payload.member : null;
            applyMemberState(effectiveMember || null);
            if (effectiveMember) {{
              const jobs = [loadNotices(), loadDashboard(), loadProfileData(), refreshArticles()];
              if (effectiveMember && effectiveMember.role === "admin") {{
                jobs.push(loadApprovals());
                jobs.push(loadLogs());
              }}
              await Promise.allSettled(jobs);
            }} else if (window.location.protocol !== "file:") {{
              window.location.replace(loginPageHref);
            }}
            return payload;
          }}

          async function submitJson(endpoint, payload) {{
            const response = await fetch(endpoint, {{
              method: "POST",
              credentials: "same-origin",
              headers: {{
                "Content-Type": "application/json"
              }},
              body: JSON.stringify(payload)
            }});
            const body = await readJson(response);
            if (!response.ok || !body.ok) {{
              throw new Error(body.error || "Nao foi possivel concluir a operacao.");
            }}
            return body;
          }}

          function fillEditForm(slug) {{
            const article = articleMap.get(slug);
            if (!article) {{
              editForm.reset();
              if (editDocxImportInput) {{
                editDocxImportInput.value = "";
              }}
              setEditorHtml("");
              setCheckedValues(editForm, []);
              editSnapshot = null;
              return;
            }}
            const titleField = formField(editForm, "title");
            const authorField = formField(editForm, "author");
            const authorMembersField = formField(editForm, "author_members");
            const summaryField = formField(editForm, "summary");
            const tagsField = formField(editForm, "tags");
            const hashtagsField = formField(editForm, "hashtags");
            if (editDocxImportInput) {{
              editDocxImportInput.value = "";
            }}
            if (editDocxInput) {{
              editDocxInput.value = "";
            }}
            if (titleField) titleField.value = article.title || "";
            if (authorField) authorField.value = article.author_text || article.author || "";
            setMultiSelectValues(authorMembersField, (article.author_members || []).map((item) => item.email || ""));
            if (summaryField) summaryField.value = article.summary || "";
            setEditorHtml(article.body_html || renderLegacyMarkup(article.body_editor || ""));
            if (tagsField) tagsField.value = csv(article.tags || []);
            if (hashtagsField) hashtagsField.value = csv(article.hashtags || []);
            setCheckedValues(editForm, article.categories || []);
            editSnapshot = currentEditState();
          }}

          function validateCategories(form, statusNode) {{
            if (getCheckedValues(form).length > 0) {{
              return true;
            }}
            setStatus(statusNode, "error", "Selecione pelo menos uma categoria.");
            return false;
          }}

          function validateRequiredTitle(form, statusNode) {{
            const titleField = formField(form, "title");
            const title = String(titleField ? titleField.value : "").trim();
            if (title) {{
              if (titleField) {{
                titleField.value = title;
              }}
              return true;
            }}
            setStatus(statusNode, "error", "Informe o titulo do texto.");
            if (titleField) {{
              titleField.focus();
            }}
            return false;
          }}

          function validateEditBody() {{
            const blocks = syncEditBodyFields();
            if (blocks.length > 0) {{
              return true;
            }}
            setStatus(editStatus, "error", "Escreva o corpo do texto antes de salvar a edicao.");
            return false;
          }}

          function validateCreateBody() {{
            const blocks = syncCreateBodyFields();
            if (blocks.length > 0) {{
              return true;
            }}
            setStatus(createStatus, "error", "Importe o DOCX e revise o corpo do texto antes de publicar.");
            return false;
          }}

          function populateSelect() {{
            const options = ['<option value="">Escolha um texto</option>'].concat(
              articles.map((article) => '<option value="' + escapeHtml(article.slug) + '">' + escapeHtml(article.title) + '</option>')
            );
            editSelect.innerHTML = options.join("");
          }}

          function setArticles(nextArticles) {{
            articles = Array.isArray(nextArticles) ? repairValue(nextArticles) : [];
            articleMap = new Map(articles.map((item) => [item.slug, item]));
            const previousValue = editSelect ? String(editSelect.value || "") : "";
            populateSelect();
            if (editSelect && previousValue && articleMap.has(previousValue)) {{
              editSelect.value = previousValue;
              fillEditForm(previousValue);
            }} else if (editSelect) {{
              editSelect.value = "";
              fillEditForm("");
            }}
          }}

          async function refreshArticles() {{
            if (!member) {{
              return;
            }}
            const response = await fetch("/api/members/articles", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401) {{
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel atualizar a lista de textos.");
            }}
            setArticles(payload.items || []);
          }}

          async function loadProfileData() {{
            if (!member || !profileForm) {{
              return;
            }}
            const response = await fetch("/api/members/profile", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401) {{
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel carregar o perfil.");
            }}
            memberDirectory = Array.isArray(payload.directory) ? payload.directory : [];
            renderMemberSelectOptions();
            if (payload.member) {{
              const memberPayload = payload.member;
              const nameField = formField(profileForm, "name");
              const roleField = formField(profileForm, "editorial_role");
              const educationField = formField(profileForm, "education");
              if (nameField) nameField.value = memberPayload.name || "";
              if (roleField) roleField.value = memberPayload.editorial_role || "Opcao A";
              if (educationField) educationField.value = memberPayload.education || "";
              renderProfilePreview(memberPayload);
            }}
            if (whoFormShell) {{
              whoFormShell.hidden = !(member && member.role === "admin");
            }}
            if (whoForm && payload.who) {{
              const titleField = formField(whoForm, "title");
              const summaryField = formField(whoForm, "summary");
              const bodyField = formField(whoForm, "body");
              if (titleField) titleField.value = payload.who.title || "";
              if (summaryField) summaryField.value = payload.who.summary || "";
              if (bodyField) bodyField.value = payload.who.body || "";
            }}
          }}

          async function loadNotices() {{
            if (!member) {{
              noticeList.innerHTML = "";
              return;
            }}
            const response = await fetch("/api/members/notices", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401) {{
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel carregar os recados.");
            }}
            noticeList.innerHTML = (payload.items || []).length
              ? payload.items.map(renderNotice).join('')
              : '<div class="empty-state"><h3>Sem recados ainda</h3><p>Os avisos para os membros vao aparecer aqui.</p></div>';
          }}

          async function loadDashboard() {{
            if (!member) {{
              dashboardList.innerHTML = "";
              return;
            }}
            const period = dashboardPeriod ? encodeURIComponent(dashboardPeriod.value || "30") : "30";
            const response = await fetch("/api/members/dashboard?period=" + period, {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401) {{
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel carregar o dashboard.");
            }}
            dashboardPayload = payload;
            renderDashboard(payload);
          }}

          async function loadApprovals() {{
            if (!member || member.role !== "admin") {{
              registrationApprovals.innerHTML = "";
              submissionApprovals.innerHTML = "";
              return;
            }}
            const response = await fetch("/api/members/approvals", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401 || response.status === 403) {{
              await fetchSession();
              throw new Error(payload.error || "Acesso restrito as aprovacoes.");
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel carregar as aprovacoes.");
            }}
            registrationApprovals.innerHTML = (payload.registrations || []).length
              ? payload.registrations.map(renderRegistrationApproval).join('')
              : '<div class="empty-state"><h3>Sem cadastros pendentes</h3><p>Quando surgir um novo cadastro aguardando liberacao, ele aparecera aqui.</p></div>';
            submissionApprovals.innerHTML = (payload.submissions || []).length
              ? payload.submissions.map(renderSubmissionApproval).join('')
              : '<div class="empty-state"><h3>Sem publicacoes pendentes</h3><p>Quando um revisor enviar um texto, ele aparecera aqui para aprovacao.</p></div>';
          }}

          function renderLogItem(item) {{
            return '<article class="member-log-entry">' +
              '<div class="member-log-entry__meta">' +
                '<strong>' + escapeHtml(item.at || '') + '</strong>' +
                '<span>' + escapeHtml(item.kind || '') + '</span>' +
              '</div>' +
              '<p>' + escapeHtml(item.message || '') + '</p>' +
              '<div class="member-log-entry__details">' +
                '<span>' + escapeHtml(item.email || '') + '</span>' +
                '<span>' + escapeHtml(item.role || '') + '</span>' +
                '<span>' + escapeHtml(item.ip || '') + '</span>' +
              '</div>' +
            '</article>';
          }}

          async function loadLogs() {{
            if (!member || member.role !== "admin") {{
              logsList.innerHTML = "";
              return;
            }}
            const response = await fetch("/api/members/logs?limit=200", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401 || response.status === 403) {{
              await fetchSession();
              throw new Error(payload.error || "Acesso restrito aos logs.");
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel carregar os logs.");
            }}
            logsList.innerHTML = (payload.items || []).length
              ? payload.items.map(renderLogItem).join('')
              : '<div class="empty-state"><h3>Sem logs ainda</h3><p>Os acessos e as acoes dos membros vao aparecer aqui.</p></div>';
          }}

          async function submitForm(form, endpoint, statusNode) {{
            const data = new FormData(form);
            const response = await fetch(endpoint, {{
              method: "POST",
              body: data,
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (response.status === 401) {{
              await fetchSession();
            }}
            if (!response.ok || !payload.ok) {{
              throw new Error(payload.error || "Nao foi possivel concluir a operacao.");
            }}
            if (payload.pending) {{
              setStatus(
                statusNode,
                "success",
                escapeHtml(payload.message || "Solicitacao enviada para aprovacao.") + "<br><strong>" + escapeHtml(payload.title || "Texto pendente") + "</strong>"
              );
              form.reset();
              syncCategoryCombobox(form);
              setMultiSelectValues(formField(form, "author_members"), []);
              if (form === createForm) {{
                if (createDocxImportInput) {{
                  createDocxImportInput.value = "";
                }}
                setCreateEditorHtml("");
                updateCreateSubmitState();
              }}
              if (form === editForm) {{
                if (editDocxImportInput) {{
                  editDocxImportInput.value = "";
                }}
                setEditorHtml("");
                setCheckedValues(editForm, []);
                editSnapshot = null;
                editSelect.value = "";
              }}
              if (member && member.role === "admin") {{
                loadApprovals().catch(() => {{
                  setStatus(approvalsStatus, "error", "Nao foi possivel atualizar a fila de aprovacoes.");
                }});
              }}
              refreshArticles().catch(() => {{
                setStatus(editStatus, "error", "Nao foi possivel atualizar a lista de textos.");
              }});
              return;
            }}
            setStatus(
              statusNode,
              "success",
              "Concluido com sucesso.<br><strong>" + escapeHtml(payload.title || "Texto atualizado") + "</strong><br><a href=\\"" + escapeHtml(payload.article_url || "/") + "\\">Abrir pagina</a>"
            );
            refreshArticles().catch(() => {{
              setStatus(editStatus, "error", "Nao foi possivel atualizar a lista de textos.");
            }});
            window.setTimeout(() => window.location.reload(), 1200);
          }}

          if (window.location.protocol === "file:") {{
            setStatus(loginStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O login nao funciona em <code>file://</code>.");
            setStatus(registerStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O cadastro nao funciona em <code>file://</code>.");
            setStatus(createStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O envio nao funciona em <code>file://</code>.");
            setStatus(editStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. A edicao nao funciona em <code>file://</code>.");
            setStatus(profileStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O perfil nao funciona em <code>file://</code>.");
            setStatus(whoStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O Quem Somos nao funciona em <code>file://</code>.");
          }}

          activateCategoryComboboxes();
          activateMemberComboboxes();
          if (createDocxInput) {{
            createDocxInput.addEventListener("change", () => {{
              if (createDocxImportInput) {{
                createDocxImportInput.value = "";
              }}
              updateCreateSubmitState();
            }});
          }}
          if (editDocxInput) {{
            editDocxInput.addEventListener("change", () => {{
              if (editDocxImportInput) {{
                editDocxImportInput.value = "";
              }}
            }});
          }}
          activateRichEditor();
          activateCreateRichEditor();
          populateSelect();
          renderMemberSelectOptions();
          setEditorHtml("");
          setCreateEditorHtml("");
          if (createForm) {{
            createForm.addEventListener("input", updateCreateSubmitState);
            createForm.addEventListener("change", updateCreateSubmitState);
          }}
          [createForm, editForm].forEach((form) => {{
            const select = formField(form, "author_members");
            if (select) {{
              select.addEventListener("change", () => syncAuthorFieldWithMembers(form));
            }}
          }});
          updateCreateSubmitState();
          syncRestrictedTabs();
          fetchSession().catch(() => {{
            applyMemberState(null);
            setStatus(loginStatus, "error", "Nao foi possivel verificar a sessao de membro.");
          }});

          memberTabs.forEach((button) => {{
            button.addEventListener("click", async () => {{
              if (!member) {{
                return;
              }}
              const target = button.dataset.memberTab;
              if (restrictedTabNames().includes(String(target || "")) && member.role !== "admin") {{
                setStatus(memberStatus, "error", "Esta aba e restrita ao Conselho Editorial.");
                return;
              }}
              setActiveTab(target);
              if (target === "notices") {{
                try {{
                  await loadNotices();
                }} catch (error) {{
                  setStatus(noticeStatus, "error", escapeHtml(error.message));
                }}
              }}
              if (target === "dashboard") {{
                try {{
                  await loadDashboard();
                }} catch (error) {{
                  setStatus(dashboardStatus, "error", escapeHtml(error.message));
                }}
              }}
              if (target === "edit") {{
                try {{
                  await refreshArticles();
                }} catch (error) {{
                  setStatus(editStatus, "error", escapeHtml(error.message));
                }}
              }}
              if (target === "profile") {{
                try {{
                  await loadProfileData();
                }} catch (error) {{
                  setStatus(profileStatus, "error", escapeHtml(error.message));
                }}
              }}
              if (target === "approvals") {{
                try {{
                  await loadApprovals();
                }} catch (error) {{
                  setStatus(approvalsStatus, "error", escapeHtml(error.message));
                }}
              }}
              if (target === "logs") {{
                try {{
                  await loadLogs();
                }} catch (error) {{
                  setStatus(logsStatus, "error", escapeHtml(error.message));
                }}
              }}
            }});
          }});

          if (openProfileTabButton) {{
            openProfileTabButton.addEventListener("click", async () => {{
              if (!member) {{
                return;
              }}
              setActiveTab("profile");
              try {{
                await loadProfileData();
              }} catch (error) {{
                setStatus(profileStatus, "error", escapeHtml(error.message));
              }}
            }});
          }}

          loginForm.addEventListener("submit", async (event) => {{
            event.preventDefault();
            if (window.location.protocol === "file:") {{
              return;
            }}
            setStatus(loginStatus, "pending", "Entrando...");
            try {{
              const payload = await submitJson("/api/members/login", {{
                email: formField(loginForm, "email").value.trim(),
                password: formField(loginForm, "password").value
              }});
              storePanelMemberState(payload.member || null);
              loginForm.reset();
              setStatus(loginStatus, "success", "Acesso liberado para <strong>" + escapeHtml(payload.member.name || payload.member.email) + "</strong>.");
              window.location.assign(panelPageHref);
            }} catch (error) {{
              setStatus(loginStatus, "error", escapeHtml(error.message));
            }}
          }});

          registerForm.addEventListener("submit", async (event) => {{
            event.preventDefault();
            if (window.location.protocol === "file:") {{
              return;
            }}
            if (formField(registerForm, "password").value !== formField(registerForm, "password_confirm").value) {{
              setStatus(registerStatus, "error", "A confirmacao da senha precisa ser igual a senha informada.");
              return;
            }}
            setStatus(registerStatus, "pending", "Cadastrando membro...");
            try {{
              const payload = await submitJson("/api/members/register", {{
                name: formField(registerForm, "name").value.trim(),
                email: formField(registerForm, "email").value.trim(),
                role: formField(registerForm, "role").value,
                password: formField(registerForm, "password").value
              }});
              registerForm.reset();
              setStatus(registerStatus, "success", "Cadastro enviado para aprovacao do Conselho Editorial.<br><strong>" + escapeHtml(payload.member.name || payload.member.email) + "</strong>");
            }} catch (error) {{
              setStatus(registerStatus, "error", escapeHtml(error.message));
            }}
          }});

          if (profileForm) {{
            profileForm.addEventListener("submit", async (event) => {{
              event.preventDefault();
              if (window.location.protocol === "file:" || !requireMember(profileStatus)) {{
                return;
              }}
              setStatus(profileStatus, "pending", "Salvando perfil...");
              try {{
                const response = await fetch("/api/members/profile", {{
                  method: "POST",
                  body: new FormData(profileForm),
                  credentials: "same-origin"
                }});
                const payload = await readJson(response);
                if (!response.ok || !payload.ok) {{
                  throw new Error(payload.error || "Nao foi possivel salvar o perfil.");
                }}
                applyMemberState(payload.member || member);
                memberDirectory = Array.isArray(payload.directory) ? payload.directory : memberDirectory;
                renderMemberSelectOptions();
                renderProfilePreview(payload.member || {{}});
                setStatus(profileStatus, "success", "Perfil atualizado com sucesso.");
              }} catch (error) {{
                setStatus(profileStatus, "error", escapeHtml(error.message));
              }}
            }});
          }}

          if (whoForm) {{
            whoForm.addEventListener("submit", async (event) => {{
              event.preventDefault();
              if (window.location.protocol === "file:" || !requireMember(whoStatus)) {{
                return;
              }}
              setStatus(whoStatus, "pending", "Salvando Quem Somos...");
              try {{
                await submitJson("/api/members/who", {{
                  title: formField(whoForm, "title").value.trim(),
                  summary: formField(whoForm, "summary").value.trim(),
                  body: formField(whoForm, "body").value.trim()
                }});
                setStatus(whoStatus, "success", "Pagina Quem Somos atualizada.");
              }} catch (error) {{
                setStatus(whoStatus, "error", escapeHtml(error.message));
              }}
            }});
          }}

          noticeForm.addEventListener("submit", async (event) => {{
            event.preventDefault();
            if (window.location.protocol === "file:" || !requireMember(noticeStatus)) {{
              return;
            }}
            setStatus(noticeStatus, "pending", "Publicando recado...");
            try {{
              await submitJson("/api/members/notices", {{
                message: formField(noticeForm, "message").value
              }});
              noticeForm.reset();
              setStatus(noticeStatus, "success", "Recado publicado com sucesso.");
              await loadNotices();
              setActiveTab("notices");
            }} catch (error) {{
              setStatus(noticeStatus, "error", escapeHtml(error.message));
            }}
          }});

          editSelect.addEventListener("change", () => {{
            fillEditForm(editSelect.value);
            clearStatus(editStatus);
          }});

          dashboardRefresh.addEventListener("click", async () => {{
            if (!requireMember(dashboardStatus)) {{
              return;
            }}
            setStatus(dashboardStatus, "pending", "Atualizando dashboard...");
            try {{
              await loadDashboard();
              setStatus(dashboardStatus, "success", "Dashboard atualizado.");
            }} catch (error) {{
              setStatus(dashboardStatus, "error", escapeHtml(error.message));
            }}
          }});

          if (dashboardPeriod) {{
            dashboardPeriod.addEventListener("change", async () => {{
              if (!requireMember(dashboardStatus)) {{
                return;
              }}
              setStatus(dashboardStatus, "pending", "Atualizando filtro do dashboard...");
              try {{
                await loadDashboard();
                setStatus(dashboardStatus, "success", "Dashboard filtrado.");
              }} catch (error) {{
                setStatus(dashboardStatus, "error", escapeHtml(error.message));
              }}
            }});
          }}

          [dashboardChartKind, dashboardMetric].forEach((control) => {{
            if (!control) {{
              return;
            }}
            control.addEventListener("change", () => {{
              if (dashboardPayload) {{
                renderDashboard(dashboardPayload);
              }}
            }});
          }});

          approvalsRefresh.addEventListener("click", async () => {{
            if (!requireMember(approvalsStatus)) {{
              return;
            }}
            setStatus(approvalsStatus, "pending", "Atualizando aprovacoes...");
            try {{
              await loadApprovals();
              setStatus(approvalsStatus, "success", "Fila de aprovacoes atualizada.");
            }} catch (error) {{
              setStatus(approvalsStatus, "error", escapeHtml(error.message));
            }}
          }});

          if (logsRefresh) {{
            logsRefresh.addEventListener("click", async () => {{
              if (!requireMember(logsStatus)) {{
                return;
              }}
              setStatus(logsStatus, "pending", "Atualizando logs...");
              try {{
                await loadLogs();
                setStatus(logsStatus, "success", "Logs atualizados.");
              }} catch (error) {{
                setStatus(logsStatus, "error", escapeHtml(error.message));
              }}
            }});
          }}

          createForm.addEventListener("submit", async (event) => {{
            event.preventDefault();
            const createRequirements = describeCreateRequirements();
            if (!createRequirements.valid) {{
              setStatus(createStatus, "error", escapeHtml(createRequirements.message));
              updateCreateSubmitState();
              return;
            }}
            if (window.location.protocol === "file:" || !requireMember(createStatus) || !validateRequiredTitle(createForm, createStatus) || !validateCategories(createForm, createStatus) || !validateCreateBody()) {{
              return;
            }}
            setStatus(createStatus, "pending", "Publicando texto...");
            try {{
              await submitForm(createForm, "/api/upload", createStatus);
            }} catch (error) {{
              setStatus(createStatus, "error", escapeHtml(error.message));
            }}
          }});

          async function importDocxIntoEditor({{ form, fileInput, importInput, statusNode, setEditor, successMessage, titleFallback = false, readyEditor = null }}) {{
            if (window.location.protocol === "file:" || !requireMember(statusNode)) {{
              return;
            }}
            const file = fileInput && fileInput.files ? fileInput.files[0] : null;
            if (!file) {{
              setStatus(statusNode, "error", "Escolha um arquivo DOCX para importar.");
              return;
            }}
            setStatus(statusNode, "pending", "Salvando e importando o DOCX para a caixa de edicao...");
            try {{
              const data = new FormData();
              data.append("docx", file);
              const response = await fetch("/api/docx-import", {{
                method: "POST",
                body: data,
                credentials: "same-origin"
              }});
              const payload = await readJson(response);
              if (!response.ok || !payload.ok) {{
                throw new Error(payload.error || "Nao foi possivel importar o DOCX.");
              }}
              if (importInput) {{
                importInput.value = payload.import_id || "";
              }}
              const titleField = formField(form, "title");
              const authorField = formField(form, "author");
              if (titleField && (!titleField.value.trim() || titleFallback)) {{
                titleField.value = payload.title || "";
              }}
              if (authorField && (!authorField.value.trim() || titleFallback) && payload.author) {{
                authorField.value = payload.author;
              }}
              if (typeof readyEditor === "function") {{
                await readyEditor();
              }}
              setEditor(payload.body_html || "");
              if (form === createForm) {{
                syncCreateBodyFields();
              }} else {{
                syncEditBodyFields();
              }}
              setStatus(statusNode, "success", successMessage || "DOCX salvo e importado para a caixa de edicao.");
            }} catch (error) {{
              setStatus(statusNode, "error", escapeHtml(error.message));
            }}
          }}

          createImportDocxButton.addEventListener("click", async () => {{
            await importDocxIntoEditor({{
              form: createForm,
              fileInput: createDocxInput,
              importInput: createDocxImportInput,
              statusNode: createStatus,
              setEditor: setCreateEditorHtml,
              readyEditor: activateCreateRichEditor,
              successMessage: "DOCX salvo no site e importado para a caixa de edicao. Revise e publique o texto final."
            }});
          }});

          editForm.addEventListener("submit", async (event) => {{
            event.preventDefault();
            if (window.location.protocol === "file:") {{
              return;
            }}
            if (!requireMember(editStatus)) {{
              return;
            }}
            if (!editSelect.value) {{
              setStatus(editStatus, "error", "Escolha um texto para editar.");
              return;
            }}
            if (!validateRequiredTitle(editForm, editStatus)) {{
              return;
            }}
            if (!validateCategories(editForm, editStatus)) {{
              return;
            }}
            if (!validateEditBody()) {{
              return;
            }}
            const currentState = currentEditState();
            const docxChanged = Boolean((editDocxInput && editDocxInput.files && editDocxInput.files[0]) || (editDocxImportInput && editDocxImportInput.value));
            const imageChanged = Boolean(editForm.image.files[0]);
            if (!docxChanged && !imageChanged && sameState(currentState, editSnapshot)) {{
              setStatus(editStatus, "error", "Nenhuma alteracao foi feita. A edicao nao sera executada.");
              return;
            }}
            setStatus(editStatus, "pending", "Salvando edicao...");
            try {{
              await submitForm(editForm, "/api/edit", editStatus);
            }} catch (error) {{
              setStatus(editStatus, "error", escapeHtml(error.message));
            }}
          }});

          editImportDocxButton.addEventListener("click", async () => {{
            await importDocxIntoEditor({{
              form: editForm,
              fileInput: editDocxInput,
              importInput: editDocxImportInput,
              statusNode: editStatus,
              setEditor: setEditorHtml,
              readyEditor: activateRichEditor,
              titleFallback: true,
              successMessage: "Novo DOCX salvo no site e carregado na caixa de edicao. Salve a edicao para enviar para aprovacao."
            }});
          }});

          deleteArticleButton.addEventListener("click", async () => {{
            if (window.location.protocol === "file:") {{
              return;
            }}
            if (!requireMember(editStatus)) {{
              return;
            }}
            if (!editSelect.value) {{
              setStatus(editStatus, "error", "Escolha um texto para excluir.");
              return;
            }}
            if (!window.confirm("Deseja enviar a exclusao deste texto para aprovacao?")) {{
              return;
            }}
            setStatus(editStatus, "pending", "Enviando exclusao...");
            try {{
              await submitJson("/api/delete", {{
                slug: editSelect.value
              }});
              editForm.reset();
              setEditorHtml("");
              setCheckedValues(editForm, []);
              setMultiSelectValues(formField(editForm, "author_members"), []);
              editSnapshot = null;
              editSelect.value = "";
              setStatus(editStatus, "success", "Exclusao enviada para aprovacao.");
              await refreshArticles();
              if (member && member.role === "admin") {{
                await loadApprovals();
              }}
            }} catch (error) {{
              setStatus(editStatus, "error", escapeHtml(error.message));
            }}
          }});

          logoutButton.addEventListener("click", async () => {{
            if (window.location.protocol === "file:") {{
              return;
            }}
            setStatus(memberStatus, "pending", "Encerrando sessao...");
            try {{
              await submitJson("/api/members/logout", {{}});
              applyMemberState(null);
              noticeForm.reset();
              editForm.reset();
              createForm.reset();
              if (profileForm) {{
                profileForm.reset();
              }}
              if (whoForm) {{
                whoForm.reset();
              }}
              setEditorHtml("");
              setCheckedValues(editForm, []);
              setCheckedValues(createForm, []);
              setMultiSelectValues(formField(editForm, "author_members"), []);
              setMultiSelectValues(formField(createForm, "author_members"), []);
              renderProfilePreview({{}});
              editSnapshot = null;
              editSelect.value = "";
              clearStatus(createStatus);
              clearStatus(editStatus);
              clearStatus(profileStatus);
              clearStatus(whoStatus);
              clearStatus(noticeStatus);
              clearStatus(dashboardStatus);
              window.location.assign(loginPageHref);
            }} catch (error) {{
              setStatus(memberStatus, "error", escapeHtml(error.message));
            }}
          }});

          document.addEventListener("click", async (event) => {{
            const registrationButton = event.target.closest("[data-approve-registration]");
            if (registrationButton) {{
              if (!requireMember(approvalsStatus)) {{
                return;
              }}
              setStatus(approvalsStatus, "pending", "Aprovando cadastro...");
              try {{
                await submitJson("/api/members/approvals/registrations/approve", {{
                  email: registrationButton.dataset.approveRegistration
                }});
                await loadApprovals();
                setStatus(approvalsStatus, "success", "Cadastro aprovado com sucesso.");
              }} catch (error) {{
                setStatus(approvalsStatus, "error", escapeHtml(error.message));
              }}
              return;
            }}

            const submissionButton = event.target.closest("[data-approve-submission]");
            if (submissionButton) {{
              if (!requireMember(approvalsStatus)) {{
                return;
              }}
              setStatus(approvalsStatus, "pending", "Aprovando publicacao...");
              try {{
                await submitJson("/api/members/approvals/submissions/approve", {{
                  id: submissionButton.dataset.approveSubmission
                }});
                await loadApprovals();
                await loadDashboard();
                window.setTimeout(() => window.location.reload(), 600);
                setStatus(approvalsStatus, "success", "Publicacao aprovada com sucesso.");
              }} catch (error) {{
                setStatus(approvalsStatus, "error", escapeHtml(error.message));
              }}
              return;
            }}

            const rejectionButton = event.target.closest("[data-reject-submission]");
            if (rejectionButton) {{
              if (!requireMember(approvalsStatus)) {{
                return;
              }}
              const approvalCard = rejectionButton.closest(".approval-card");
              const reasonField = approvalCard ? approvalCard.querySelector("[data-rejection-reason]") : null;
              const reason = reasonField ? String(reasonField.value || "").trim() : "";
              if (reason.length < 3) {{
                setStatus(approvalsStatus, "error", "Informe um motivo curto para a recusa.");
                if (reasonField) {{
                  reasonField.focus();
                }}
                return;
              }}
              setStatus(approvalsStatus, "pending", "Recusando publicacao...");
              try {{
                await submitJson("/api/members/approvals/submissions/reject", {{
                  id: rejectionButton.dataset.rejectSubmission,
                  reason
                }});
                await loadApprovals();
                setStatus(approvalsStatus, "success", "Publicacao recusada com sucesso.");
              }} catch (error) {{
                setStatus(approvalsStatus, "error", escapeHtml(error.message));
              }}
            }}
          }});
        }})();
      </script>
    </main>
"""
    return render_shell(
        page_title="Painel de Membros",
        description="Painel restrito para publicar, editar e acompanhar textos da Revista Barravento.",
        css_path=f"{root_prefix}styles/site.css",
        icon_path=site_logo_href(root_prefix),
        body_class="members-page members-page--panel",
        content=content,
        page_path="publicar.html" if not root_prefix else page_path_from_root(root_prefix, "painel/index.html"),
        robots_content="noindex,nofollow,noarchive,nosnippet",
    )


def render_member_login_page(*, root_prefix: str = "") -> str:
    links = page_links(root_prefix)
    content = f"""{render_header(root_prefix, date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner">
        <div class="container">
          <span class="eyebrow">Membros</span>
          <h2>Entrar na area de membros</h2>
          <p>Se a sessao ja estiver ativa, o site leva voce direto ao painel editorial.</p>
        </div>
      </section>

      <section class="section">
        <div class="container editor-grid members-grid">
          <section class="upload-card upload-card--main">
            <div class="card-header">
              <h3>Acesso de membro</h3>
              <p>Entre com o e-mail e a senha aprovados para abrir o painel de membros.</p>
            </div>
            <form id="login-form" class="upload-form">
              <label class="field">
                <span>E-mail</span>
                <input id="login-email" name="email" type="email" autocomplete="username" required>
              </label>

              <label class="field">
                <span>Senha</span>
                <input id="login-password" name="password" type="password" autocomplete="current-password" required>
              </label>

              <div class="upload-actions">
                <button class="button-link" type="submit">Entrar</button>
              </div>
              <div class="upload-status" id="login-status" role="status" aria-live="polite"></div>
            </form>
          </section>
        </div>
      </section>

      <script>
        (() => {{
          const loginForm = document.getElementById("login-form");
          const loginStatus = document.getElementById("login-status");
          const loginEmailInput = loginForm ? loginForm.querySelector('[name="email"]') : null;
          const loginPasswordInput = loginForm ? loginForm.querySelector('[name="password"]') : null;
          const panelPageHref = {json.dumps(links["members_panel"])};
          const resolvedPanelPageHref = (() => {{
            try {{
              return new URL(panelPageHref, window.location.href).toString();
            }} catch (_error) {{
              return "/painel/#member-panel";
            }}
          }})();
          let toastHost = null;

          function escapeHtml(value) {{
            return String(value).replace(/[&<>"']/g, (char) => {{
              const map = {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}};
              return map[char] || char;
            }});
          }}

          function getToastHost() {{
            if (toastHost && document.body.contains(toastHost)) {{
              return toastHost;
            }}
            toastHost = document.createElement("div");
            toastHost.className = "member-toast-host";
            toastHost.setAttribute("aria-live", "polite");
            toastHost.setAttribute("aria-atomic", "false");
            document.body.appendChild(toastHost);
            return toastHost;
          }}

          function showToast(kind, html) {{
            const host = getToastHost();
            const toast = document.createElement("article");
            toast.className = "member-toast member-toast--" + kind;
            toast.innerHTML = '<div class="member-toast__body">' + html + '</div><button class="member-toast__close" type="button" aria-label="Fechar notificacao">Fechar</button>';
            host.appendChild(toast);
            const close = () => {{
              toast.classList.add("is-leaving");
              window.setTimeout(() => {{
                if (toast.parentNode) {{
                  toast.parentNode.removeChild(toast);
                }}
              }}, 220);
            }};
            const closeButton = toast.querySelector(".member-toast__close");
            if (closeButton) {{
              closeButton.addEventListener("click", close);
            }}
            const timeout = kind === "error" ? 5200 : (kind === "pending" ? 2400 : 3600);
            window.setTimeout(close, timeout);
          }}

          function setStatus(node, kind, html) {{
            node.className = "upload-status is-" + kind;
            node.innerHTML = html;
            if (node && node.dataset && node.dataset.popupStatus === "true" && html) {{
              showToast(kind, html);
            }}
          }}

          loginStatus.dataset.popupStatus = "true";

          async function readJson(response) {{
            return response.json().catch(() => ({{}}));
          }}

          async function submitJson(endpoint, payload) {{
            const response = await fetch(endpoint, {{
              method: "POST",
              credentials: "same-origin",
              headers: {{
                "Content-Type": "application/json"
              }},
              body: JSON.stringify(payload)
            }});
            const body = await readJson(response);
            if (!response.ok || !body.ok) {{
              throw new Error(body.error || "Nao foi possivel concluir a operacao.");
            }}
            return body;
          }}

          async function fetchSession() {{
            const response = await fetch("/api/members/session", {{
              credentials: "same-origin"
            }});
            const payload = await readJson(response);
            if (payload.authenticated) {{
              window.location.replace(resolvedPanelPageHref);
            }}
            return payload;
          }}

          function goToPanel() {{
            window.location.href = resolvedPanelPageHref;
            window.setTimeout(() => {{
              if (window.location.href !== resolvedPanelPageHref) {{
                window.location.assign(resolvedPanelPageHref);
              }}
            }}, 40);
            window.setTimeout(() => {{
              if (window.location.href !== resolvedPanelPageHref) {{
                window.location.replace(resolvedPanelPageHref);
              }}
            }}, 160);
          }}

          async function waitForAuthenticatedSession(expectedEmail) {{
            for (let attempt = 0; attempt < 8; attempt += 1) {{
              try {{
                const payload = await fetchSession();
                const sessionEmail = String(payload && payload.member && payload.member.email || "").trim().toLowerCase();
                const targetEmail = String(expectedEmail || "").trim().toLowerCase();
                if (payload && payload.authenticated && (!targetEmail || sessionEmail === targetEmail)) {{
                  return true;
                }}
              }} catch (_error) {{
              }}
              await new Promise((resolve) => window.setTimeout(resolve, 180));
            }}
            return false;
          }}

          if (window.location.protocol === "file:") {{
            setStatus(loginStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code> ou pelo servidor hospedado. O login nao funciona em <code>file://</code>.");
            return;
          }}

          fetchSession().catch(() => {{
            setStatus(loginStatus, "error", "Nao foi possivel verificar a sessao de membro.");
          }});

          loginForm.addEventListener("submit", async (event) => {{
            event.preventDefault();
            setStatus(loginStatus, "pending", "Entrando...");
            try {{
              const payload = await submitJson("/api/members/login", {{
                email: loginEmailInput ? loginEmailInput.value.trim() : "",
                password: loginPasswordInput ? loginPasswordInput.value : ""
              }});
              loginForm.reset();
              setStatus(loginStatus, "success", "Acesso liberado para <strong>" + escapeHtml(payload.member.name || payload.member.email) + "</strong>.");
              await waitForAuthenticatedSession(payload && payload.member ? payload.member.email : "");
              goToPanel();
            }} catch (error) {{
              setStatus(loginStatus, "error", escapeHtml(error.message));
            }}
          }});
        }})();
      </script>
    </main>
"""
    return render_shell(
        page_title="Acesso de Membros",
        description="Pagina de login e cadastro para acessar o painel de membros da Revista Barravento.",
        css_path=f"{root_prefix}styles/site.css",
        icon_path=site_logo_href(root_prefix),
        body_class="members-page members-page--login",
        content=content,
        page_path=page_path_from_root(root_prefix, "membros/index.html"),
        robots_content="noindex,nofollow,noarchive,nosnippet",
    )


def render_search_page(articles: list[Article]) -> str:
    search_data = json_for_script([serialize_article_for_client(article, "../") for article in articles])
    content = f"""{render_header('../', date_label=format_long_date(datetime.now()))}
    <main>
      <section class="page-banner">
        <div class="container">
          <span class="eyebrow">Busca</span>
          <h2>Buscar no acervo</h2>
          <p>Pesquise por titulos, resumos, tags, hashtags e categorias.</p>
        </div>
      </section>

      <section class="section">
        <div class="container">
          <div id="search-summary" class="search-summary"></div>
          <div id="search-results" class="article-grid article-grid--wide"></div>
        </div>
      </section>

      <script id="search-data" type="application/json">{search_data}</script>
      <script>
        (() => {{
          const input = document.querySelector('.header-search input[name="q"]');
          const summary = document.getElementById("search-summary");
          const results = document.getElementById("search-results");
          const articles = JSON.parse(document.getElementById("search-data").textContent);
          const params = new URLSearchParams(window.location.search);
          const query = (params.get("q") || "").trim();

          if (input) {{
            input.value = query;
          }}

          function slugify(value) {{
            return value.toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
          }}

          function haystack(article) {{
            return [
              article.title,
              article.summary,
              (article.categories || []).join(" "),
              (article.tags || []).join(" "),
              (article.hashtags || []).join(" ")
            ].join(" ").toLowerCase();
          }}

          function categoryBadges(article) {{
            return '<div class="category-badges">' + (article.categories || []).map((category) => {{
              return '<a class="category-badge" href="../categorias/' + slugify(category) + '/">' + category + '</a>';
            }}).join("") + '</div>';
          }}

          function renderCard(article) {{
            return `
              <article class="article-card">
                <a class="article-card__image" href="${{article.article_url}}">
                  <img src="${{article.image_url}}" alt="${{article.image_alt}}">
                </a>
                <div class="article-card__body">
                  ${{categoryBadges(article)}}
                  <div class="meta-row">
                    <span>${{article.published_label}}</span>
                    <span>${{article.reading_time}} min</span>
                  </div>
                  <h3><a href="${{article.article_url}}">${{article.title}}</a></h3>
                  <p>${{article.summary}}</p>
                  <a class="article-card__link" href="${{article.article_url}}">Ler texto</a>
                </div>
              </article>
            `;
          }}

          if (!query) {{
            summary.textContent = "Digite um termo na busca do topo para localizar textos.";
            results.innerHTML = '<div class="empty-state"><h3>Busca vazia</h3><p>Procure por categorias, titulos, tags ou hashtags.</p></div>';
            return;
          }}

          const lowered = query.toLowerCase();
          const matches = articles.filter((article) => haystack(article).includes(lowered));
          summary.textContent = matches.length === 1
            ? '1 resultado para "' + query + '".'
            : matches.length + ' resultados para "' + query + '".';
          results.innerHTML = matches.length > 0
            ? matches.map(renderCard).join("")
            : '<div class="empty-state"><h3>Nenhum resultado encontrado</h3><p>Tente outro termo na busca do topo.</p></div>';
        }})();
      </script>
    </main>
"""
    return render_shell(
        page_title="Busca",
        description="Busca local por titulos, categorias, tags e hashtags.",
        css_path="../styles/site.css",
        icon_path=site_logo_href("../"),
        body_class="search-page",
        content=content,
        page_path="busca/index.html",
        robots_content="index,follow",
    )


def render_cookie_policy_page() -> str:
    blocks = [
        "Esta Politica de Cookies explica como a Revista Barravento usa cookies e tecnologias semelhantes em conformidade com a Lei Geral de Protecao de Dados Pessoais (LGPD) e com as orientacoes da ANPD.",
        "Usamos um cookie estritamente necessario chamado barravento_member_session para autenticar membros, proteger a area restrita e manter a sessao ativa apos o login. Esse cookie e HTTPOnly, possui SameSite=Lax, usa o caminho raiz do site e permanece ativo por ate sete dias ou ate o encerramento da sessao.",
        "Tambem usamos armazenamento local do navegador para registrar, apenas com seu consentimento, leituras de textos e organizar a secao de mais lidos. Essas chaves locais sao barravento-read-counts e barravento-read-stamp:<slug>. Elas sao opcionais, ficam desativadas por padrao e podem ser apagadas quando voce rejeita os cookies de desempenho.",
        "Guardamos sua escolha na chave local barravento-cookie-preferences para lembrar se voce aceitou ou recusou os recursos opcionais. Esse registro e necessario para preservar sua preferencia e evitar a reapresentacao constante do banner.",
        "Voce pode aceitar, rejeitar ou personalizar os itens opcionais no banner inicial e revisar essa decisao a qualquer momento no botao Cookies disponivel no site.",
        "Atualmente nao utilizamos cookies opcionais de publicidade comportamental nem cookies opcionais de terceiros para rastreamento comercial. Se isso mudar, esta politica e o banner serao atualizados antes da ativacao desses recursos.",
        "Para exercer direitos previstos na LGPD ou tirar duvidas sobre privacidade e cookies, utilize os canais apresentados na pagina de Contato da revista.",
    ]
    return render_static_page(
        title="Politica de Cookies",
        eyebrow="Privacidade",
        summary="Informacoes claras sobre cookies, tecnologias semelhantes, finalidades e como revisar suas preferencias.",
        blocks=blocks,
        root_prefix="../",
        body_class="static-page",
    )


def render_article_page(article: Article) -> str:
    published = format_long_date(article.published_at)
    body_html = render_article_body(article)
    author_markup = article_author_links(article, "../../")
    author_names: list[str] = []
    seen_author_keys: set[str] = set()
    for text_part in split_author_parts(article.author_text):
        text_key = author_key(text_part)
        if text_part and text_key not in seen_author_keys:
            author_names.append(text_part)
            seen_author_keys.add(text_key)
    for item in (article.author_members or []):
        name = str(item.get("name", "")).strip()
        name_key = author_key(name)
        if name and name_key not in seen_author_keys:
            author_names.append(name)
            seen_author_keys.add(name_key)
    seo_authors = author_names or [article.author or SITE_NAME]
    read_tracking_script = f"""
      <script>
        (() => {{
          if (!window.BarraventoConsent || !window.BarraventoConsent.hasPerformanceConsent()) {{
            return;
          }}
          const storageKey = "barravento-read-counts";
          const monthlyStorageKey = "barravento-read-counts-monthly";
          const stampKey = "barravento-read-stamp:{escape(article.slug)}";
          const slug = "{escape(article.slug)}";
          const now = Date.now();
          const cooldown = 30 * 60 * 1000;
          const monthKey = new Date(now).toISOString().slice(0, 7);

          let lastRead = 0;
          try {{
            lastRead = Number(localStorage.getItem(stampKey) || 0);
          }} catch (error) {{
            return;
          }}

          if (now - lastRead < cooldown) {{
            return;
          }}

          let counts = {{}};
          try {{
            counts = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
          }} catch (error) {{
            counts = {{}};
          }}

          let monthlyCounts = {{}};
          try {{
            monthlyCounts = JSON.parse(localStorage.getItem(monthlyStorageKey) || "{{}}");
          }} catch (error) {{
            monthlyCounts = {{}};
          }}

          counts[slug] = Number(counts[slug] || 0) + 1;
          const currentMonth = monthlyCounts[monthKey] && typeof monthlyCounts[monthKey] === "object" ? monthlyCounts[monthKey] : {{}};
          currentMonth[slug] = Number(currentMonth[slug] || 0) + 1;
          monthlyCounts[monthKey] = currentMonth;
          localStorage.setItem(storageKey, JSON.stringify(counts));
          localStorage.setItem(monthlyStorageKey, JSON.stringify(monthlyCounts));
          localStorage.setItem(stampKey, String(now));
        }})();
      </script>"""
    content = f"""{render_header('../../', date_label=published)}
    <main>
      <section class="page-banner article-banner">
        <div class="container">
          <div class="article-banner__inner">
            <span class="eyebrow">Texto</span>
            {render_category_badges(article.categories, '../../')}
            <h2>{escape(article.title)}</h2>
            <p>{escape(article.summary)}</p>
            <div class="meta-row">
              <span>{author_markup}</span>
              <span>{article.reading_time} min de leitura</span>
              <span>{escape(published)}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="container article-layout">
          <article>
            <figure class="article-figure">
              <img src="{image_src(article, '../../')}" alt="{escape(article.image_alt)}">
              <figcaption>{escape(article.image_caption)}</figcaption>
            </figure>
            <div class="article-body">
{body_html}
            </div>
          </article>

          <aside class="article-sidebar">
            <section class="sidebar-card">
              <h3>Categorias</h3>
              {render_category_badges(article.categories, '../../', klass='category-badges category-badges--stacked')}
            </section>

            <section class="sidebar-card">
              <h3>Creditos</h3>
              <div class="article-credits">
                <div class="article-credit-item">
                  <span class="muted-label article-credit-label">autor</span>
                  <span class="article-credit-value">{author_markup}</span>
                </div>
                <div class="article-credit-item">
                  <span class="muted-label article-credit-label">publicacao</span>
                  <span class="article-credit-value">{escape(published)}</span>
                </div>
              </div>
              <p><a class="article-card__link article-pdf-link category-badge" href="{pdf_href(article, '../../')}" download aria-label="Baixar PDF">Baixar PDF</a></p>
            </section>
{render_tag_cloud("Tags", article.tags, '../../')}{render_tag_cloud("Hashtags", article.hashtags, '../../')}            <section class="sidebar-card">
              <h3>Navegacao</h3>
              <p><a class="article-card__link" href="../../index.html">Voltar para a capa</a></p>
            </section>
          </aside>
        </div>
      </section>
{read_tracking_script}
    </main>
"""
    return render_shell(
        page_title=article.title,
        description=article.summary,
        css_path="../../styles/site.css",
        icon_path=site_logo_href("../../"),
        body_class="article-page",
        content=content,
        page_path=f"artigos/{article.slug}/index.html",
        seo_type="article",
        keywords=article.categories + article.tags + article.hashtags + seo_authors,
        image_path=image_src(article, ""),
        seo_json_ld=[
            {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": article.title,
                "description": article.summary,
                "datePublished": article.published_at.isoformat(),
                "dateModified": article.published_at.isoformat(),
                "author": [
                    {"@type": "Person", "name": author_name}
                    for author_name in seo_authors
                ],
                "publisher": {
                    "@type": "Organization",
                    "name": SITE_NAME,
                    "logo": {
                        "@type": "ImageObject",
                        "url": absolute_site_url(DEFAULT_SOCIAL_IMAGE),
                    },
                },
                "mainEntityOfPage": absolute_site_url(f"artigos/{article.slug}/index.html"),
                "image": [absolute_site_url(image_src(article, ""))],
                "articleSection": article.categories,
                "keywords": ", ".join(article.tags + article.hashtags + article.categories),
                "inLanguage": "pt-BR",
            },
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": absolute_site_url("")},
                    {"@type": "ListItem", "position": 2, "name": article.title, "item": absolute_site_url(f"artigos/{article.slug}/index.html")},
                ],
            },
        ],
    )


def process_input_documents() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for incoming in sorted(INPUT_DIR.glob("*.docx")):
        target = PROCESSED_DIR / incoming.name
        if target.exists():
            target.unlink()
        shutil.move(str(incoming), str(target))

        sidecar_in = sidecar_path(incoming)
        sidecar_out = sidecar_path(target)
        if sidecar_in.exists():
            if sidecar_out.exists():
                sidecar_out.unlink()
            shutil.move(str(sidecar_in), str(sidecar_out))

        timestamp = datetime.now().timestamp()
        os.utime(target, (timestamp, timestamp))


def clear_stale_directories(parent: Path, valid_children: set[str]) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    for child in parent.iterdir():
        if child.is_dir() and child.name not in valid_children:
            shutil.rmtree(child)


def clear_stale_pdf_files(valid_names: set[str]) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for child in PDF_DIR.glob("*.pdf"):
        if child.name not in valid_names:
            child.unlink()


def rebuild_text_backup_archive(articles: list[Article]) -> None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    temp_archive = TEXT_BACKUP_ARCHIVE.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for article in sorted(articles, key=lambda item: item.slug):
            docx_path = PROCESSED_DIR / f"{article.slug}.docx"
            html_path = ARTICLES_DIR / article.slug / "index.html"
            if docx_path.exists():
                archive.write(docx_path, arcname=str(docx_path.relative_to(ROOT)).replace("\\", "/"))
            if html_path.exists():
                archive.write(html_path, arcname=str(html_path.relative_to(ROOT)).replace("\\", "/"))
    temp_archive.replace(TEXT_BACKUP_ARCHIVE)


def render_robots_txt() -> str:
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /painel/",
        "Disallow: /membros/",
        "Disallow: /publicar.html",
    ]
    if SITE_PUBLIC_URL:
        lines.append(f"Sitemap: {SITE_PUBLIC_URL}/sitemap.xml")
    return "\n".join(lines) + "\n"


def render_sitemap_xml(articles: list[Article]) -> str:
    if not SITE_PUBLIC_URL:
        return ""
    urls: list[tuple[str, str]] = [
        (absolute_site_url(""), datetime.now().date().isoformat()),
        (absolute_site_url("busca/index.html"), datetime.now().date().isoformat()),
        (absolute_site_url("quem-somos/index.html"), datetime.now().date().isoformat()),
        (absolute_site_url("contato/index.html"), datetime.now().date().isoformat()),
    ]
    for category in CATEGORY_OPTIONS:
        urls.append((absolute_site_url(f"categorias/{slugify(category)}/index.html"), datetime.now().date().isoformat()))
    for article in articles:
        urls.append((absolute_site_url(f"artigos/{article.slug}/index.html"), article.published_at.date().isoformat()))
    for member in load_member_profiles():
        urls.append((absolute_site_url(f"perfis/{member.profile_slug}/index.html"), datetime.now().date().isoformat()))
    body = "\n".join(
        f"  <url><loc>{escape(loc)}</loc><lastmod>{lastmod}</lastmod></url>"
        for loc, lastmod in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )


def build_site() -> list[Article]:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    CATEGORY_DIR.mkdir(parents=True, exist_ok=True)
    WHO_DIR.mkdir(parents=True, exist_ok=True)
    CONTACT_DIR.mkdir(parents=True, exist_ok=True)
    SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    MEMBERS_DIR.mkdir(parents=True, exist_ok=True)
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_POLICY_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    custom_site_logo = ROOT / SITE_LOGO_FILE
    if custom_site_logo.exists():
        shutil.copy2(custom_site_logo, ASSETS_DIR / SITE_LOGO_FILE)
    custom_site_symbol = ROOT / SITE_SYMBOL_FILE
    if custom_site_symbol.exists():
        shutil.copy2(custom_site_symbol, ASSETS_DIR / SITE_SYMBOL_FILE)
    if SITE_BRAND_FONT_SOURCE.exists():
        shutil.copy2(SITE_BRAND_FONT_SOURCE, ASSETS_DIR / SITE_BRAND_FONT_FILE)
    process_input_documents()

    articles = [extract_article(docx_file) for docx_file in PROCESSED_DIR.glob("*.docx")]
    articles.sort(key=lambda item: item.published_at, reverse=True)
    member_profiles = load_member_profiles()
    enrich_article_member_links(articles, member_profiles)
    sync_submission_author_links(member_profiles)
    sync_member_article_links(articles)
    member_profiles = load_member_profiles()

    clear_stale_directories(ARTICLES_DIR, {article.slug for article in articles})
    clear_stale_directories(CATEGORY_DIR, {slugify(category) for category in CATEGORY_OPTIONS})
    clear_stale_directories(PROFILE_DIR, {member.profile_slug for member in member_profiles})
    clear_stale_pdf_files({f"{article.slug}.pdf" for article in articles})

    for article in articles:
        target_dir = ARTICLES_DIR / article.slug
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "index.html").write_text(render_article_page(article), encoding="utf-8")
        create_article_pdf(article)

    for category in CATEGORY_OPTIONS:
        category_dir = CATEGORY_DIR / slugify(category)
        category_dir.mkdir(parents=True, exist_ok=True)
        category_articles = [article for article in articles if category in article.categories]
        (category_dir / "index.html").write_text(
            render_category_page(category, category_articles),
            encoding="utf-8",
        )
    for member in member_profiles:
        profile_dir = PROFILE_DIR / member.profile_slug
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "index.html").write_text(render_profile_page(member, articles), encoding="utf-8")

    who_html = render_who_page(member_profiles)
    contact_html = render_static_page(
        title="Contato",
        eyebrow="Institucional",
        summary="Pagina propria para divulgar os canais oficiais da revista.",
        blocks=[
            "Use esta pagina para inserir e-mail, telefone, redes sociais ou formulario de contato.",
            "O menu superior continuara apontando para esta pagina em todas as secoes do site.",
        ],
        root_prefix="../",
        body_class="static-page",
    )
    cookie_policy_html = render_cookie_policy_page()

    (WHO_DIR / "index.html").write_text(who_html, encoding="utf-8")
    (CONTACT_DIR / "index.html").write_text(contact_html, encoding="utf-8")
    (COOKIE_POLICY_DIR / "index.html").write_text(cookie_policy_html, encoding="utf-8")
    (SEARCH_DIR / "index.html").write_text(render_search_page(articles), encoding="utf-8")
    (SITE_DIR / "index.html").write_text(render_home_page(articles), encoding="utf-8")
    (SITE_DIR / "publicar.html").write_text(render_upload_page(articles), encoding="utf-8")
    (MEMBERS_DIR / "index.html").write_text(render_member_login_page(root_prefix="../"), encoding="utf-8")
    (PANEL_DIR / "index.html").write_text(render_upload_page(articles, root_prefix="../"), encoding="utf-8")
    (SITE_DIR / "robots.txt").write_text(render_robots_txt(), encoding="utf-8")
    sitemap_xml = render_sitemap_xml(articles)
    if sitemap_xml:
        (SITE_DIR / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")
    rebuild_text_backup_archive(articles)
    return articles


def main() -> None:
    articles = build_site()
    print(f"Site atualizado com {len(articles)} artigo(s).")


if __name__ == "__main__":
    main()
