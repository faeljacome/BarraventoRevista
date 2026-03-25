const cookieParser = require("cookie-parser");
const crypto = require("crypto");
const express = require("express");
const fs = require("fs");
const mammoth = require("mammoth");
const path = require("path");
const multer = require("multer");
const { spawnSync } = require("child_process");

const ROOT = __dirname;
const SITE_DIR = path.join(ROOT, "site");
const TINYMCE_DIR = path.join(ROOT, "node_modules", "tinymce");
const CKEDITOR_DIR = path.join(ROOT, "node_modules", "@ckeditor", "ckeditor5-build-decoupled-document", "build");
const QUILL_DIST_DIR = path.join(ROOT, "node_modules", "quill", "dist");
const PROCESSED_DIR = path.join(ROOT, "conteudo", "processados");
const INPUT_DIR = path.join(ROOT, "conteudo", "entrada-docx");
const UPLOADS_DIR = path.join(SITE_DIR, "uploads");
const DATA_DIR = path.join(ROOT, "dados");
const MEMBERS_FILE = path.join(DATA_DIR, "membros.json");
const NOTICES_FILE = path.join(DATA_DIR, "recados.json");
const STATS_FILE = path.join(DATA_DIR, "estatisticas.json");
const SUBMISSIONS_FILE = path.join(DATA_DIR, "submissoes.json");
const SUBMISSIONS_DIR = path.join(DATA_DIR, "submissoes");
const DOCX_IMPORTS_DIR = path.join(DATA_DIR, "docx-imports");

const SESSION_COOKIE_NAME = "barravento_member_session";
const SESSION_MAX_AGE = 1000 * 60 * 60 * 24 * 7;
const PASSWORD_ROUNDS = 240000;
const ALLOWED_IMAGE_SUFFIXES = new Set([".jpg", ".jpeg", ".png", ".webp"]);
const CATEGORY_OPTIONS = new Set([
  "Editoriais",
  "Entrevistas",
  "Política e Crítica Econômica",
  "Ideologia, Arte e Cultura",
  "Traduções",
  "Teoria em Movimento",
  "Textos literários"
]);

const CATEGORY_CANONICAL = [
  "Editoriais",
  "Entrevistas",
  "Pol\u00edtica e Cr\u00edtica Econ\u00f4mica",
  "Ideologia, Arte e Cultura",
  "Tradu\u00e7\u00f5es",
  "Teoria em Movimento",
  "Textos liter\u00e1rios"
];
const ROLE_LABELS = {
  admin: "Conselho Editorial",
  reviewer: "Revisor"
};
const DEFAULT_MEMBER_ROLE = "reviewer";

const sessions = new Map();
const upload = multer({ storage: multer.memoryStorage() });
const app = express();

app.use(cookieParser());
app.use(express.json({ limit: "2mb" }));
app.use(express.urlencoded({ extended: true }));

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function readJsonFile(filePath, fallback) {
  if (!fs.existsSync(filePath)) {
    return fallback;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJsonFile(filePath, payload) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf8");
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function validateEmail(value) {
  const email = normalizeEmail(value);
  const [local, domain] = email.split("@");
  if (!local || !domain || !domain.includes(".")) {
    throw createError(400, "Informe um e-mail valido.");
  }
  return email;
}

function validateName(value) {
  const name = String(value || "").trim();
  if (name.length < 2) {
    throw createError(400, "Informe o nome do membro.");
  }
  return name;
}

function validatePassword(value) {
  const password = String(value || "").trim();
  if (password.length < 8) {
    throw createError(400, "A senha precisa ter pelo menos 8 caracteres.");
  }
  return password;
}

function createError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function hashPassword(password, saltHex) {
  const salt = saltHex ? Buffer.from(saltHex, "hex") : crypto.randomBytes(16);
  const digest = crypto.pbkdf2Sync(password, salt, PASSWORD_ROUNDS, 32, "sha256");
  return {
    password_salt: salt.toString("hex"),
    password_hash: digest.toString("hex")
  };
}

function verifyPassword(password, member) {
  if (!member || !member.password_salt || !member.password_hash) {
    return false;
  }
  const digest = hashPassword(password, member.password_salt).password_hash;
  return crypto.timingSafeEqual(Buffer.from(digest, "hex"), Buffer.from(member.password_hash, "hex"));
}

function normalizeMemberRole(value) {
  const role = String(value || "").trim().toLowerCase();
  return ROLE_LABELS[role] ? role : DEFAULT_MEMBER_ROLE;
}

function publicMemberPayload(member) {
  const role = normalizeMemberRole(member.role);
  return {
    name: String(member.name || "").trim(),
    email: normalizeEmail(member.email),
    created_at: String(member.created_at || "").trim(),
    role,
    role_label: ROLE_LABELS[role],
    approved: Boolean(member.approved),
    approved_at: String(member.approved_at || "").trim()
  };
}

function readMembers() {
  const raw = readJsonFile(MEMBERS_FILE, {});
  const members = raw.members && typeof raw.members === "object" ? raw.members : raw;
  if (!members || typeof members !== "object") {
    return {};
  }

  const normalized = {};
  for (const [key, value] of Object.entries(members)) {
    if (!value || typeof value !== "object") {
      continue;
    }
    const email = normalizeEmail(value.email || key);
    if (!email) {
      continue;
    }
    normalized[email] = {
      name: String(value.name || "").trim(),
      email,
      password_salt: String(value.password_salt || "").trim(),
      password_hash: String(value.password_hash || "").trim(),
      created_at: String(value.created_at || "").trim(),
      role: normalizeMemberRole(value.role),
      approved: value.approved === undefined ? true : String(value.approved).trim().toLowerCase() !== "false",
      approved_at: String(value.approved_at || "").trim()
    };
  }
  return normalized;
}

function writeMembers(members) {
  writeJsonFile(MEMBERS_FILE, { members });
}

function pendingMemberRegistrations() {
  return Object.values(readMembers())
    .filter((member) => !member.approved)
    .map((member) => publicMemberPayload(member))
    .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
}

function approveMemberRegistration(email) {
  const normalizedEmail = validateEmail(email);
  const members = readMembers();
  const member = members[normalizedEmail];
  if (!member) {
    throw createError(404, "Cadastro de membro nao encontrado.");
  }
  if (member.approved) {
    throw createError(400, "Este cadastro ja foi aprovado.");
  }
  member.approved = true;
  member.approved_at = new Date().toISOString().slice(0, 19);
  members[normalizedEmail] = member;
  writeMembers(members);
  return publicMemberPayload(member);
}

function createSession(email) {
  const token = crypto.randomBytes(24).toString("base64url");
  sessions.set(token, {
    email: normalizeEmail(email),
    expiresAt: Date.now() + SESSION_MAX_AGE
  });
  return token;
}

function currentMember(req) {
  const token = req.cookies[SESSION_COOKIE_NAME];
  if (!token) {
    return null;
  }
  const session = sessions.get(token);
  if (!session) {
    return null;
  }
  if (session.expiresAt <= Date.now()) {
    sessions.delete(token);
    return null;
  }
  const members = readMembers();
  const member = members[session.email];
  if (!member || !member.approved) {
    sessions.delete(token);
    return null;
  }
  return publicMemberPayload(member);
}

function requireMember(req, _res, next) {
  const member = currentMember(req);
  if (!member) {
    next(createError(401, "Acesso restrito a membros. Entre com e-mail e senha para continuar."));
    return;
  }
  req.member = member;
  next();
}

function requireAdmin(req, _res, next) {
  if (req.member && req.member.role === "admin") {
    next();
    return;
  }
  next(createError(403, "Acesso restrito ao Conselho Editorial."));
}

function slugify(value) {
  const ascii = String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
  return ascii || "artigo";
}

function parseCsvList(raw) {
  const value = Array.isArray(raw) ? raw.join(",") : String(raw || "");
  return value
    .replace(/;/g, ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, list) => list.indexOf(item) === index);
}

function normalizeHashtags(values) {
  return values
    .map((value) => String(value || "").trim().replace(/^#/, ""))
    .map((value) => slugify(value))
    .filter(Boolean)
    .map((value) => `#${value}`)
    .filter((item, index, list) => list.indexOf(item) === index);
}

function arrayValue(raw) {
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item || "").trim()).filter(Boolean);
  }
  if (raw === undefined || raw === null || raw === "") {
    return [];
  }
  return [String(raw).trim()].filter(Boolean);
}

function repairMojibakeText(value) {
  const text = String(value || "").trim();
  if (!text || !/[ÃÂ]/.test(text)) {
    return text;
  }
  try {
    return Buffer.from(text, "latin1").toString("utf8").trim();
  } catch {
    return text;
  }
}

function parseCategories(raw) {
  const lookup = new Map(CATEGORY_CANONICAL.map((item) => [slugify(item), item]));
  const categories = arrayValue(raw)
    .map((item) => {
      const direct = lookup.get(slugify(item));
      if (direct) {
        return direct;
      }
      const repaired = repairMojibakeText(item);
      return lookup.get(slugify(repaired)) || "";
    })
    .filter(Boolean)
    .filter((item, index, list) => list.indexOf(item) === index);
  if (!categories.length) {
    throw createError(400, "Selecione pelo menos uma categoria.");
  }
  return categories;
}

function sanitizeDocxName(filename) {
  const safeName = path.basename(filename || "");
  if (path.extname(safeName).toLowerCase() !== ".docx") {
    throw createError(400, "Envie apenas arquivos .docx.");
  }
  return safeName;
}

function requireArticleTitle(value) {
  const title = String(value || "").trim();
  if (!title) {
    throw createError(400, "Informe o titulo do texto.");
  }
  return title;
}

async function previewDocxFile(file) {
  if (!file || !file.buffer?.length) {
    throw createError(400, "Selecione um arquivo .docx para importar.");
  }
  sanitizeDocxName(file.originalname);
  const [htmlResult, textResult] = await Promise.all([
    mammoth.convertToHtml({ buffer: file.buffer }),
    mammoth.extractRawText({ buffer: file.buffer })
  ]);
  const html = sanitizeArticleHtml(htmlResult.value || "");
  const rawText = normalizeEditorValue(textResult.value || "");
  const lines = rawText.split(/\n+/).map((item) => compactWhitespace(item)).filter(Boolean);
  const guessedTitle = lines[0] || path.parse(file.originalname).name;
  const guessedAuthor = /^por[: ]/i.test(lines[1] || "") ? lines[1].replace(/^por[: ]/i, "").trim() : "";
  return {
    ok: true,
    title: guessedTitle,
    author: guessedAuthor,
    body_html: html,
    body: rawText
  };
}

function importedDocxMetaPath(importId) {
  return path.join(DOCX_IMPORTS_DIR, `${path.basename(String(importId || "").trim())}.json`);
}

function importedDocxFilePath(importId) {
  return path.join(DOCX_IMPORTS_DIR, path.basename(String(importId || "").trim()));
}

function saveImportedDocx(file) {
  if (!file || !file.buffer?.length) {
    throw createError(400, "Selecione um arquivo .docx para importar.");
  }
  const originalname = sanitizeDocxName(file.originalname);
  ensureDir(DOCX_IMPORTS_DIR);
  const importId = `${Date.now()}-${crypto.randomBytes(6).toString("hex")}-${slugify(path.parse(originalname).name) || "texto"}.docx`;
  fs.writeFileSync(importedDocxFilePath(importId), file.buffer);
  writeJsonFile(importedDocxMetaPath(importId), {
    import_id: importId,
    originalname,
    created_at: new Date().toISOString().slice(0, 19)
  });
  return {
    import_id: importId,
    originalname
  };
}

function loadImportedDocx(importId) {
  const safeId = path.basename(String(importId || "").trim());
  if (!safeId) {
    return null;
  }
  const docxPath = importedDocxFilePath(safeId);
  if (!fs.existsSync(docxPath)) {
    throw createError(404, "O DOCX importado nao foi encontrado. Importe novamente o arquivo.");
  }
  const metadata = readJsonFile(importedDocxMetaPath(safeId), {});
  const buffer = fs.readFileSync(docxPath);
  return {
    fieldname: "docx",
    originalname: sanitizeDocxName(metadata.originalname || safeId),
    encoding: "7bit",
    mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer,
    size: buffer.length
  };
}

function resolveDocxInput(req, { required = false, message } = {}) {
  const imported = loadImportedDocx(req.body.docx_import_id);
  if (imported) {
    return imported;
  }
  const direct = req.files?.docx?.[0];
  if (direct?.buffer?.length) {
    sanitizeDocxName(direct.originalname);
    return direct;
  }
  if (required) {
    throw createError(400, message || "Selecione um arquivo .docx para continuar.");
  }
  return null;
}

function sanitizeImageName(filename) {
  const suffix = path.extname(path.basename(filename || "")).toLowerCase();
  if (!ALLOWED_IMAGE_SUFFIXES.has(suffix)) {
    throw createError(400, "Envie uma imagem .jpg, .jpeg, .png ou .webp.");
  }
  return suffix;
}

function uniqueArticleSlug(baseSlug) {
  ensureDir(INPUT_DIR);
  ensureDir(PROCESSED_DIR);
  let candidate = baseSlug || "artigo";
  let counter = 2;
  while (
    fs.existsSync(path.join(INPUT_DIR, `${candidate}.docx`)) ||
    fs.existsSync(path.join(PROCESSED_DIR, `${candidate}.docx`)) ||
    fs.existsSync(path.join(INPUT_DIR, `${candidate}.json`)) ||
    fs.existsSync(path.join(PROCESSED_DIR, `${candidate}.json`))
  ) {
    candidate = `${baseSlug}-${counter}`;
    counter += 1;
  }
  return candidate;
}

function setTimestamp(filePath) {
  const now = new Date();
  fs.utimesSync(filePath, now, now);
}

function articleDocxPath(slug) {
  return path.join(PROCESSED_DIR, `${slug}.docx`);
}

function sidecarPath(docxPath) {
  return docxPath.replace(/\.docx$/i, ".json");
}

function articleImageNames(slug) {
  if (!fs.existsSync(UPLOADS_DIR)) {
    return [];
  }
  const matcher = new RegExp(`^${String(slug || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:[-.]|$)`, "i");
  return fs.readdirSync(UPLOADS_DIR).filter((name) => matcher.test(name) && ALLOWED_IMAGE_SUFFIXES.has(path.extname(name).toLowerCase()));
}

function saveUploadedImage(slug, file) {
  ensureDir(UPLOADS_DIR);
  const suffix = sanitizeImageName(file.originalname);
  const stamp = Date.now();
  const targetName = `${slug}-${stamp}${suffix}`;
  const targetPath = path.join(UPLOADS_DIR, targetName);
  for (const existing of articleImageNames(slug)) {
    if (existing !== targetName) {
      fs.unlinkSync(path.join(UPLOADS_DIR, existing));
    }
  }
  fs.writeFileSync(targetPath, file.buffer);
  return targetName;
}

function normalizeEditorValue(value) {
  return String(value || "").replace(/\r\n/g, "\n").trim();
}

function compactWhitespace(value) {
  return String(value || "").replace(/[ \t]+/g, " ").trim();
}

function stripInlineMarkup(value) {
  return compactWhitespace(String(value || "").replace(/\*\*/g, "").replace(/\*/g, ""));
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function editorMarkupToHtml(value) {
  let html = escapeHtml(String(value || ""));
  html = html.replace(/\*\*(.+?)\*\*/gs, "<strong>$1</strong>");
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/gs, "<em>$1</em>");
  html = html.replace(/\[(\d+)\]/g, "<sup>[$1]</sup>");
  return html.replace(/\n/g, "<br>").trim();
}

function decodeHtmlEntities(value) {
  return String(value || "")
    .replace(/&#(\d+);/g, (_match, code) => String.fromCodePoint(Number(code) || 0))
    .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCodePoint(parseInt(code, 16) || 0))
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'");
}

function sanitizeUrl(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (/^(https?:|mailto:|#|\/)/i.test(text)) {
    return text;
  }
  if (/^[\w.-]+@[\w.-]+\.[a-z]{2,}$/i.test(text)) {
    return `mailto:${text}`;
  }
  if (/^[\w.-]+\.[a-z]{2,}/i.test(text)) {
    return `https://${text}`;
  }
  return "";
}

function sanitizeImageSource(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (/^data:image\/[a-z0-9.+-]+;base64,[a-z0-9+/=\s]+$/i.test(text)) {
    return text.replace(/\s+/g, "");
  }
  if (/^(https?:|\/)/i.test(text)) {
    return text;
  }
  return "";
}

function sanitizeEmbedSource(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (/^(https?:)?\/\/(www\.)?(youtube\.com|youtube-nocookie\.com|youtu\.be|player\.vimeo\.com)\//i.test(text)) {
    return text.startsWith("//") ? `https:${text}` : text;
  }
  return "";
}

function sanitizeInlineStyle(value) {
  const allowed = [];
  const chunks = String(value || "").split(";");
  for (const chunk of chunks) {
    const [rawName, ...rawRest] = chunk.split(":");
    const name = String(rawName || "").trim().toLowerCase();
    const input = rawRest.join(":").trim();
    if (!name || !input) {
      continue;
    }
    if (name === "text-align") {
      const normalized = input.toLowerCase();
      if (["left", "center", "right", "justify"].includes(normalized)) {
        allowed.push(`${name}:${normalized}`);
      }
      continue;
    }
    if (name === "color" || name === "background-color") {
      if (/^(#[0-9a-f]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z-]+)$/i.test(input)) {
        allowed.push(`${name}:${input}`);
      }
      continue;
    }
    if (name === "font-size") {
      if (/^([0-9]{1,3}(\.[0-9]+)?)(px|pt|em|rem|%)$/i.test(input) || /^(xx-small|x-small|small|medium|large|x-large|xx-large)$/i.test(input)) {
        allowed.push(`${name}:${input}`);
      }
      continue;
    }
    if (name === "font-family") {
      const safeFamily = input.replace(/[^a-z0-9,\- "'_]/gi, "").trim();
      if (safeFamily) {
        allowed.push(`${name}:${safeFamily}`);
      }
      continue;
    }
  }
  return allowed.join("; ");
}

function sanitizeRichHtml(value, allowedTags) {
  let html = String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, "")
    .trim();

  html = html.replace(/<\/?([a-z0-9]+)\b([^>]*)>/gi, (match, rawTag, rawAttrs) => {
    const tag = String(rawTag || "").toLowerCase();
    if (!allowedTags.has(tag)) {
      return "";
    }
    if (match.startsWith("</")) {
      return `</${tag}>`;
    }
    if (tag === "br") {
      return "<br>";
    }
    if (tag === "a") {
      const hrefMatch = String(rawAttrs || "").match(/\bhref\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const href = sanitizeUrl(hrefMatch ? hrefMatch[2] || hrefMatch[3] || hrefMatch[4] || "" : "");
      if (!href) {
        return "";
      }
      return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">`;
    }
    return `<${tag}>`;
  });

  return html.replace(/(<br>\s*){3,}/gi, "<br><br>").trim();
}

function sanitizeArticleHtml(value) {
  const allowedTags = new Set([
    "p", "br", "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "span", "a", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "hr", "table", "thead", "tbody", "tr", "th", "td",
    "pre", "code", "div", "img", "iframe"
  ]);

  let html = String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, "")
    .trim();

  html = html.replace(/<\/?([a-z0-9]+)\b([^>]*)>/gi, (match, rawTag, rawAttrs) => {
    const tag = String(rawTag || "").toLowerCase();
    if (!allowedTags.has(tag)) {
      return "";
    }
    if (match.startsWith("</")) {
      return `</${tag}>`;
    }

    const attrs = [];
    const styleMatch = String(rawAttrs || "").match(/\bstyle\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
    const style = sanitizeInlineStyle(styleMatch ? styleMatch[2] || styleMatch[3] || styleMatch[4] || "" : "");
    if (style) {
      attrs.push(`style="${escapeHtml(style)}"`);
    }

    if (tag === "a") {
      const hrefMatch = String(rawAttrs || "").match(/\bhref\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const href = sanitizeUrl(hrefMatch ? hrefMatch[2] || hrefMatch[3] || hrefMatch[4] || "" : "");
      if (!href) {
        return "";
      }
      attrs.push(`href="${escapeHtml(href)}"`, 'target="_blank"', 'rel="noopener noreferrer"');
    }

    if (tag === "img") {
      const srcMatch = String(rawAttrs || "").match(/\bsrc\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const altMatch = String(rawAttrs || "").match(/\balt\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const src = sanitizeImageSource(srcMatch ? srcMatch[2] || srcMatch[3] || srcMatch[4] || "" : "");
      if (!src) {
        return "";
      }
      attrs.push(`src="${escapeHtml(src)}"`);
      const alt = String(altMatch ? altMatch[2] || altMatch[3] || altMatch[4] || "" : "").trim();
      if (alt) {
        attrs.push(`alt="${escapeHtml(alt)}"`);
      }
      return `<img${attrs.length ? ` ${attrs.join(" ")}` : ""}>`;
    }

    if (tag === "iframe") {
      const srcMatch = String(rawAttrs || "").match(/\bsrc\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const src = sanitizeEmbedSource(srcMatch ? srcMatch[2] || srcMatch[3] || srcMatch[4] || "" : "");
      if (!src) {
        return "";
      }
      attrs.push(
        `src="${escapeHtml(src)}"`,
        'loading="lazy"',
        'referrerpolicy="strict-origin-when-cross-origin"',
        'allowfullscreen="allowfullscreen"'
      );
      return `<iframe${attrs.length ? ` ${attrs.join(" ")}` : ""}>`;
    }

    if (tag === "td" || tag === "th") {
      const colspanMatch = String(rawAttrs || "").match(/\bcolspan\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const rowspanMatch = String(rawAttrs || "").match(/\browspan\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const colspan = Number(colspanMatch ? colspanMatch[2] || colspanMatch[3] || colspanMatch[4] || 1 : 1);
      const rowspan = Number(rowspanMatch ? rowspanMatch[2] || rowspanMatch[3] || rowspanMatch[4] || 1 : 1);
      if (colspan > 1 && colspan < 100) {
        attrs.push(`colspan="${colspan}"`);
      }
      if (rowspan > 1 && rowspan < 100) {
        attrs.push(`rowspan="${rowspan}"`);
      }
    }

    return `<${tag}${attrs.length ? ` ${attrs.join(" ")}` : ""}>`;
  });

  return html
    .replace(/(<br>\s*){3,}/gi, "<br><br>")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function richHtmlToText(value) {
  const html = String(value || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|li|blockquote|ul|ol|h[1-6]|tr|table|pre|div)>/gi, "\n");
  return compactWhitespace(decodeHtmlEntities(html.replace(/<[^>]+>/g, " ")));
}

function normalizeBodyBlock(item) {
  if (!item || typeof item !== "object") {
    return null;
  }
  const kind = String(item.kind || "paragraph").trim().toLowerCase();
  const rawAlign = String(item.align || "left").trim().toLowerCase();
  const align = ["left", "center", "right", "justify"].includes(rawAlign) ? rawAlign : "left";

  if (kind === "heading") {
    const text = compactWhitespace(String(item.text || ""));
    if (!text) {
      return null;
    }
    const level = Math.max(1, Math.min(3, Number(item.level || 2) || 2));
    return { kind: "heading", text, level, html: "", align };
  }

  if (kind === "divider") {
    return { kind: "divider", text: "---", level: 0, html: "", align: "left" };
  }

  if (kind === "list") {
    const html = sanitizeRichHtml(String(item.html || ""), new Set(["ul", "ol", "li", "strong", "b", "em", "i", "u", "a", "br", "sup"]));
    const text = richHtmlToText(html || String(item.text || ""));
    if (!text || !html) {
      return null;
    }
    return {
      kind: "list",
      text,
      level: Number(item.level || 0) > 0 ? 1 : 0,
      html,
      align
    };
  }

  if (kind === "quote") {
    let html = sanitizeRichHtml(String(item.html || ""), new Set(["p", "strong", "b", "em", "i", "u", "a", "br", "sup"]));
    if (html && !/<p>/i.test(html)) {
      html = `<p>${html}</p>`;
    }
    const text = richHtmlToText(html || String(item.text || ""));
    if (!text) {
      return null;
    }
    return {
      kind: "quote",
      text,
      level: 0,
      html: html || `<p>${editorMarkupToHtml(String(item.text || ""))}</p>`,
      align
    };
  }

  const html = sanitizeRichHtml(String(item.html || ""), new Set(["strong", "b", "em", "i", "u", "a", "br", "sup"]));
  const text = richHtmlToText(html || String(item.text || ""));
  if (!text) {
    return null;
  }
  return {
    kind: "paragraph",
    text,
    level: 0,
    html: html || editorMarkupToHtml(String(item.text || "")),
    align
  };
}

function parseBodyBlocksField(raw) {
  if (!raw) {
    return [];
  }
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map((item) => normalizeBodyBlock(item)).filter(Boolean);
  } catch {
    return [];
  }
}

function blocksToSidecar(markup) {
  const chunks = normalizeEditorValue(markup).split(/\n\s*\n/g);
  const blocks = [];
  for (const chunk of chunks) {
    const value = chunk.trim();
    if (!value) {
      continue;
    }
    if (value.startsWith("### ")) {
      blocks.push({ kind: "heading", text: compactWhitespace(value.slice(4)), level: 3, html: "" });
      continue;
    }
    if (value.startsWith("## ")) {
      blocks.push({ kind: "heading", text: compactWhitespace(value.slice(3)), level: 2, html: "" });
      continue;
    }
    if (value.startsWith("# ")) {
      blocks.push({ kind: "heading", text: compactWhitespace(value.slice(2)), level: 1, html: "" });
      continue;
    }
    const text = stripInlineMarkup(value.replace(/\n/g, " "));
    if (!text) {
      continue;
    }
    blocks.push({
      kind: "paragraph",
      text,
      level: 0,
      html: editorMarkupToHtml(value)
    });
  }
  return blocks;
}

function loadUploadPageArticles() {
  const candidates = [
    path.join(SITE_DIR, "painel", "index.html"),
    path.join(SITE_DIR, "publicar.html")
  ];
  const uploadPage = candidates.find((candidate) => fs.existsSync(candidate));
  if (!uploadPage) {
    return [];
  }
  const html = fs.readFileSync(uploadPage, "utf8");
  const match = html.match(/<script id="articles-data" type="application\/json">([\s\S]*?)<\/script>/i);
  if (!match) {
    return [];
  }
  try {
    return JSON.parse(match[1]);
  } catch {
    return [];
  }
}

function loadArticleBySlug(slug) {
  return loadUploadPageArticles().find((item) => item.slug === slug) || null;
}

function formatLongDate(dateLike) {
  const moment = new Date(dateLike);
  const months = [
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
    "dezembro"
  ];
  return `${String(moment.getDate()).padStart(2, "0")} de ${months[moment.getMonth()]} de ${moment.getFullYear()}`;
}

function runBuildScript() {
  const commands = process.platform === "win32"
    ? [
        ["python", ["scripts\\gerar_site.py"]],
        ["py", ["-3", "scripts\\gerar_site.py"]]
      ]
    : [
        ["python3", ["scripts/gerar_site.py"]],
        ["python", ["scripts/gerar_site.py"]]
      ];

  let lastError = null;
  for (const [command, args] of commands) {
    const result = spawnSync(command, args, {
      cwd: ROOT,
      encoding: "utf8"
    });
    if (!result.error && result.status === 0) {
      return;
    }
    lastError = result.error || new Error(result.stderr || result.stdout || "Falha ao atualizar o site.");
  }
  throw createError(
    500,
    `O servidor Node nao conseguiu atualizar o site. Verifique se o Python e as dependencias de requirements.txt estao instalados neste ambiente. ${lastError ? String(lastError.message || lastError) : ""}`.trim()
  );
}

function buildResponse(slug, fallbackTitle, message) {
  const article = loadArticleBySlug(slug);
  return {
    ok: true,
    message,
    title: article ? article.title : fallbackTitle || slug,
    slug,
    article_url: `/artigos/${slug}/`,
    home_url: "/"
  };
}

function deleteIfExists(targetPath) {
  if (!targetPath || !fs.existsSync(targetPath)) {
    return;
  }
  fs.rmSync(targetPath, { recursive: true, force: true });
}

function deleteArticle(slug) {
  const targetSlug = slugify(slug);
  if (!targetSlug) {
    throw createError(400, "Escolha um texto para excluir.");
  }
  const docxPath = articleDocxPath(targetSlug);
  if (!fs.existsSync(docxPath)) {
    throw createError(404, "O texto selecionado para exclusao nao existe mais.");
  }

  const currentSidecar = readJsonFile(sidecarPath(docxPath), {});
  const imageName = String(currentSidecar.image_file || "").trim();
  if (imageName) {
    deleteIfExists(path.join(UPLOADS_DIR, imageName));
  }
  for (const imageFile of articleImageNames(targetSlug)) {
    deleteIfExists(path.join(UPLOADS_DIR, imageFile));
  }

  deleteIfExists(docxPath);
  deleteIfExists(sidecarPath(docxPath));
  deleteIfExists(path.join(SITE_DIR, "artigos", targetSlug));
  deleteIfExists(path.join(SITE_DIR, "pdfs", `${targetSlug}.pdf`));

  const stats = readStats();
  if (stats[targetSlug]) {
    delete stats[targetSlug];
    writeStats(stats);
  }

  runBuildScript();
  return {
    ok: true,
    message: "Texto excluido com sucesso.",
    slug: targetSlug,
    home_url: "/"
  };
}

function deleteArticleSubmission(req, member) {
  const slug = slugify(req.body.slug);
  if (!slug) {
    throw createError(400, "Escolha um texto para excluir.");
  }
  const docxPath = articleDocxPath(slug);
  if (!fs.existsSync(docxPath)) {
    throw createError(404, "O texto selecionado para exclusao nao existe mais.");
  }
  const currentArticle = loadArticleBySlug(slug);
  const submission = createPendingSubmission({
    kind: "delete",
    member,
    payload: {
      slug,
      title: currentArticle?.title || slug
    }
  });
  return {
    ok: true,
    pending: true,
    message: "Exclusao enviada para aprovacao do Conselho Editorial.",
    submission_id: submission.id,
    title: currentArticle?.title || slug
  };
}

function createArticle(req) {
  const docx = resolveDocxInput(req, { required: true, message: "Selecione um arquivo .docx para publicar." });
  const image = req.files?.image?.[0];
  if (!image || !image.buffer?.length) {
    throw createError(400, "Selecione uma imagem de capa para publicar.");
  }

  const title = requireArticleTitle(req.body.title);
  const categories = parseCategories(req.body.categories);
  const baseSlug = slugify(path.parse(sanitizeDocxName(docx.originalname)).name);
  const slug = uniqueArticleSlug(baseSlug);
  const docxPath = articleDocxPath(slug);
  ensureDir(PROCESSED_DIR);
  fs.writeFileSync(docxPath, docx.buffer);
  setTimestamp(docxPath);

  const imageName = saveUploadedImage(slug, image);
  const body = normalizeEditorValue(req.body.body);
  const bodyHtml = sanitizeArticleHtml(req.body.body_html);
  const bodyBlocks = parseBodyBlocksField(req.body.body_blocks_json);
  const metadata = {
    title,
    author: String(req.body.author || "").trim(),
    summary: String(req.body.summary || "").trim(),
    categories,
    tags: parseCsvList(req.body.tags),
    hashtags: normalizeHashtags(parseCsvList(req.body.hashtags)),
    image_scope: "uploads",
    image_file: imageName,
    image_alt: path.parse(image.originalname).name,
    image_caption: "Imagem enviada na publicacao."
  };
  if (bodyHtml || bodyBlocks.length || body) {
    const nextBodyBlocks = bodyBlocks.length ? bodyBlocks : blocksToSidecar(body);
    if (!nextBodyBlocks.length) {
      throw createError(400, "Escreva o corpo do texto antes de publicar.");
    }
    metadata.body_html = bodyHtml || "";
    metadata.body_blocks = nextBodyBlocks;
  }
  fs.writeFileSync(sidecarPath(docxPath), JSON.stringify(metadata, null, 2), "utf8");
  runBuildScript();
  return buildResponse(slug, metadata.title || slug, "Arquivo publicado com sucesso.");
}

function editArticle(req) {
  const slug = slugify(req.body.slug);
  if (!slug) {
    throw createError(400, "Escolha um texto para editar.");
  }

  const docxPath = articleDocxPath(slug);
  if (!fs.existsSync(docxPath)) {
    throw createError(404, "O texto selecionado para edicao nao existe mais.");
  }

  const currentArticle = loadArticleBySlug(slug);
  if (!currentArticle) {
    throw createError(404, "Nao foi possivel localizar o texto selecionado no site atual.");
  }

  const currentSidecar = readJsonFile(sidecarPath(docxPath), {});
  const categories = parseCategories(req.body.categories);
  const title = requireArticleTitle(req.body.title);
  const author = String(req.body.author || "").trim();
  const summary = String(req.body.summary || "").trim();
  const tags = parseCsvList(req.body.tags);
  const hashtags = normalizeHashtags(parseCsvList(req.body.hashtags));
  const body = normalizeEditorValue(req.body.body);
  const bodyHtml = sanitizeArticleHtml(req.body.body_html);
  const bodyBlocks = parseBodyBlocksField(req.body.body_blocks_json);

  const newDocx = resolveDocxInput(req);
  const currentDocxBytes = fs.readFileSync(docxPath);
  const docxChanged = Boolean(newDocx && newDocx.buffer && !newDocx.buffer.equals(currentDocxBytes));

  const newImage = req.files?.image?.[0];
  let imageChanged = false;
  const currentImageName = currentSidecar.image_file || "";
  const currentImagePath = currentImageName ? path.join(UPLOADS_DIR, currentImageName) : null;
  if (newImage && newImage.buffer?.length) {
    sanitizeImageName(newImage.originalname);
    imageChanged = !currentImagePath || !fs.existsSync(currentImagePath) || !newImage.buffer.equals(fs.readFileSync(currentImagePath));
  }

  const currentBodyBlocks = parseBodyBlocksField(currentArticle.body_blocks || []);
  const currentBodyHtml = sanitizeArticleHtml(currentArticle.body_html || "");
  const bodyChanged = bodyHtml
    ? bodyHtml !== currentBodyHtml
    : bodyBlocks.length
      ? JSON.stringify(bodyBlocks) !== JSON.stringify(currentBodyBlocks)
      : body !== normalizeEditorValue(currentArticle.body_editor || "");
  const metadataChanged = (
    title !== String(currentArticle.title || "") ||
    author !== String(currentArticle.author || "") ||
    summary !== String(currentArticle.summary || "") ||
    bodyChanged ||
    JSON.stringify(categories) !== JSON.stringify(currentArticle.categories || []) ||
    JSON.stringify(tags) !== JSON.stringify(currentArticle.tags || []) ||
    JSON.stringify(hashtags) !== JSON.stringify(currentArticle.hashtags || [])
  );

  if (!docxChanged && !imageChanged && !metadataChanged) {
    throw createError(400, "Nenhuma alteracao foi feita. A edicao nao sera executada.");
  }

  if (docxChanged && newDocx) {
    fs.writeFileSync(docxPath, newDocx.buffer);
  }

  let imageScope = currentSidecar.image_scope || "uploads";
  let imageFile = currentSidecar.image_file || "";
  let imageAlt = currentSidecar.image_alt || currentArticle.title;
  let imageCaption = currentSidecar.image_caption || "Imagem atualizada na edicao.";

  if (imageChanged && newImage) {
    imageScope = "uploads";
    imageFile = saveUploadedImage(slug, newImage);
    imageAlt = path.parse(newImage.originalname).name;
    imageCaption = "Imagem atualizada na edicao.";
  }

  const metadata = {
    title,
    author,
    summary,
    categories,
    tags,
    hashtags,
    image_scope: imageScope,
    image_file: imageFile,
    image_alt: imageAlt,
    image_caption: imageCaption
  };

  if (bodyChanged) {
    const nextBodyBlocks = bodyBlocks.length ? bodyBlocks : blocksToSidecar(body);
    if (!nextBodyBlocks.length) {
      throw createError(400, "Escreva o corpo do texto antes de salvar a edicao.");
    }
    metadata.body_html = bodyHtml || "";
    metadata.body_blocks = nextBodyBlocks;
  } else if (currentSidecar.body_blocks) {
    metadata.body_html = String(currentSidecar.body_html || "").trim();
    metadata.body_blocks = currentSidecar.body_blocks;
  }

  fs.writeFileSync(sidecarPath(docxPath), JSON.stringify(metadata, null, 2), "utf8");
  setTimestamp(docxPath);
  runBuildScript();
  return buildResponse(slug, title || currentArticle.title, "Arquivo atualizado com sucesso.");
}

function readNotices() {
  const raw = readJsonFile(NOTICES_FILE, { items: [] });
  const items = Array.isArray(raw.items) ? raw.items : [];
  return items.filter((item) => item && item.message);
}

function addNotice(member, message) {
  const normalized = String(message || "").replace(/\r\n/g, "\n").trim();
  if (normalized.length < 2) {
    throw createError(400, "Escreva um recado antes de publicar.");
  }
  const notice = {
    id: crypto.randomBytes(8).toString("hex"),
    message: normalized,
    author_name: member.name || "Membro",
    author_email: member.email || "",
    created_at: new Date().toISOString().slice(0, 19)
  };
  const notices = readNotices();
  notices.unshift(notice);
  writeJsonFile(NOTICES_FILE, { items: notices.slice(0, 100) });
  return notice;
}

function readSubmissions() {
  const raw = readJsonFile(SUBMISSIONS_FILE, { items: [] });
  const items = Array.isArray(raw.items) ? raw.items : [];
  return items.filter((item) => item && typeof item === "object");
}

function writeSubmissions(items) {
  writeJsonFile(SUBMISSIONS_FILE, { items });
}

function pendingSubmissionItems() {
  return readSubmissions()
    .filter((item) => String(item.status || "pending") === "pending")
    .sort((left, right) => String(right.requested_at || "").localeCompare(String(left.requested_at || "")));
}

function saveSubmissionFile(submissionId, file, suffixOverride) {
  if (!file || !file.buffer?.length) {
    return "";
  }
  const targetDir = path.join(SUBMISSIONS_DIR, submissionId);
  ensureDir(targetDir);
  const suffix = suffixOverride || path.extname(file.originalname || "");
  const safeBase = slugify(path.parse(file.originalname || "arquivo").name);
  const targetName = `${safeBase}${suffix}`;
  fs.writeFileSync(path.join(targetDir, targetName), file.buffer);
  return targetName;
}

function fieldCsvText(values) {
  return (Array.isArray(values) ? values : []).filter(Boolean).join(", ");
}

function submissionRequester(member) {
  return {
    name: String(member.name || "").trim(),
    email: normalizeEmail(member.email),
    role: normalizeMemberRole(member.role),
    role_label: ROLE_LABELS[normalizeMemberRole(member.role)]
  };
}

function createPendingSubmission({ kind, member, payload, docx, image }) {
  const submissionId = crypto.randomBytes(8).toString("hex");
  const submission = {
    id: submissionId,
    kind,
    status: "pending",
    requested_at: new Date().toISOString().slice(0, 19),
    requested_by: submissionRequester(member),
    ...payload
  };

  if (docx && docx.buffer?.length) {
    submission.docx_filename = docx.originalname;
    submission.docx_file = saveSubmissionFile(submissionId, docx, ".docx");
  }
  if (image && image.buffer?.length) {
    submission.image_filename = image.originalname;
    submission.image_file = saveSubmissionFile(submissionId, image, path.extname(image.originalname));
  }

  const items = readSubmissions();
  items.push(submission);
  writeSubmissions(items);
  return submission;
}

function createArticleSubmission(req, member) {
  const docx = resolveDocxInput(req, { required: true, message: "Selecione um arquivo .docx para publicar." });
  const image = req.files?.image?.[0];
  if (!image || !image.buffer?.length) {
    throw createError(400, "Selecione uma imagem de capa para publicar.");
  }

  sanitizeImageName(image.originalname);
  const title = requireArticleTitle(req.body.title);
  const categories = parseCategories(req.body.categories);
  const body = normalizeEditorValue(req.body.body);
  const bodyHtml = sanitizeArticleHtml(req.body.body_html);
  const bodyBlocks = parseBodyBlocksField(req.body.body_blocks_json);
  const nextBodyBlocks = bodyBlocks.length ? bodyBlocks : blocksToSidecar(body);
  if (!nextBodyBlocks.length) {
    throw createError(400, "Escreva o corpo do texto antes de publicar.");
  }
  const payload = {
    title,
    author: String(req.body.author || "").trim(),
    summary: String(req.body.summary || "").trim(),
    body,
    body_html: bodyHtml,
    body_blocks: nextBodyBlocks,
    categories,
    tags: parseCsvList(req.body.tags),
    hashtags: normalizeHashtags(parseCsvList(req.body.hashtags)),
    source_name: docx.originalname
  };
  const submission = createPendingSubmission({
    kind: "create",
    member,
    payload,
    docx,
    image
  });
  return {
    ok: true,
    pending: true,
    message: "Texto enviado para aprovacao do Conselho Editorial.",
    submission_id: submission.id,
    title: payload.title || path.parse(docx.originalname).name
  };
}

function editArticleSubmission(req, member) {
  const slug = slugify(req.body.slug);
  if (!slug) {
    throw createError(400, "Escolha um texto para editar.");
  }

  const docxPath = articleDocxPath(slug);
  if (!fs.existsSync(docxPath)) {
    throw createError(404, "O texto selecionado para edicao nao existe mais.");
  }

  const currentArticle = loadArticleBySlug(slug);
  if (!currentArticle) {
    throw createError(404, "Nao foi possivel localizar o texto selecionado no site atual.");
  }

  const currentSidecar = readJsonFile(sidecarPath(docxPath), {});
  const categories = parseCategories(req.body.categories);
  const title = requireArticleTitle(req.body.title);
  const author = String(req.body.author || "").trim();
  const summary = String(req.body.summary || "").trim();
  const tags = parseCsvList(req.body.tags);
  const hashtags = normalizeHashtags(parseCsvList(req.body.hashtags));
  const body = normalizeEditorValue(req.body.body);
  const bodyHtml = sanitizeArticleHtml(req.body.body_html);
  const bodyBlocks = parseBodyBlocksField(req.body.body_blocks_json);

  const newDocx = resolveDocxInput(req);
  const currentDocxBytes = fs.readFileSync(docxPath);
  const docxChanged = Boolean(newDocx && newDocx.buffer && !newDocx.buffer.equals(currentDocxBytes));

  const newImage = req.files?.image?.[0];
  let imageChanged = false;
  const currentImageName = currentSidecar.image_file || "";
  const currentImagePath = currentImageName ? path.join(UPLOADS_DIR, currentImageName) : null;
  if (newImage && newImage.buffer?.length) {
    sanitizeImageName(newImage.originalname);
    imageChanged = !currentImagePath || !fs.existsSync(currentImagePath) || !newImage.buffer.equals(fs.readFileSync(currentImagePath));
  }

  const currentBodyBlocks = parseBodyBlocksField(currentArticle.body_blocks || []);
  const currentBodyHtml = sanitizeArticleHtml(currentArticle.body_html || "");
  const bodyChanged = bodyHtml
    ? bodyHtml !== currentBodyHtml
    : bodyBlocks.length
      ? JSON.stringify(bodyBlocks) !== JSON.stringify(currentBodyBlocks)
      : body !== normalizeEditorValue(currentArticle.body_editor || "");
  const metadataChanged = (
    title !== String(currentArticle.title || "") ||
    author !== String(currentArticle.author || "") ||
    summary !== String(currentArticle.summary || "") ||
    bodyChanged ||
    JSON.stringify(categories) !== JSON.stringify(currentArticle.categories || []) ||
    JSON.stringify(tags) !== JSON.stringify(currentArticle.tags || []) ||
    JSON.stringify(hashtags) !== JSON.stringify(currentArticle.hashtags || [])
  );

  if (!docxChanged && !imageChanged && !metadataChanged) {
    throw createError(400, "Nenhuma alteracao foi feita. A edicao nao sera executada.");
  }

  const submission = createPendingSubmission({
    kind: "edit",
    member,
    payload: {
      slug,
      title,
      author,
      summary,
      body,
      body_html: bodyHtml,
      body_blocks: bodyBlocks,
      categories,
      tags,
      hashtags
    },
    docx: newDocx,
    image: newImage
  });

  return {
    ok: true,
    pending: true,
    message: "Edicao enviada para aprovacao do Conselho Editorial.",
    submission_id: submission.id,
    title: title || currentArticle.title
  };
}

function submissionFile(submission, key) {
  const storedName = String(submission[`${key}_file`] || "").trim();
  if (!storedName) {
    return null;
  }
  const targetPath = path.join(SUBMISSIONS_DIR, String(submission.id || "").trim(), storedName);
  if (!fs.existsSync(targetPath)) {
    return null;
  }
  return {
    originalname: String(submission[`${key}_filename`] || storedName).trim(),
    buffer: fs.readFileSync(targetPath)
  };
}

function approveSubmissionItem(submissionId) {
  const items = readSubmissions();
  const index = items.findIndex((item) => String(item.id || "") === String(submissionId || ""));
  if (index < 0) {
    throw createError(404, "Solicitacao pendente nao encontrada.");
  }

  const submission = items[index];
  if (String(submission.status || "pending") !== "pending") {
    throw createError(400, "Esta solicitacao ja foi processada.");
  }

  let result;
  if (submission.kind === "create") {
    const docx = submissionFile(submission, "docx");
    const image = submissionFile(submission, "image");
    if (!docx || !image) {
      throw createError(400, "Arquivos da publicacao pendente nao estao mais disponiveis.");
    }
    result = createArticle({
      body: {
        title: submission.title || "",
        author: submission.author || "",
        summary: submission.summary || "",
        body: submission.body || "",
        body_html: submission.body_html || "",
        body_blocks_json: JSON.stringify(submission.body_blocks || []),
        categories: submission.categories || [],
        tags: fieldCsvText(submission.tags || []),
        hashtags: fieldCsvText(submission.hashtags || [])
      },
      files: {
        docx: [docx],
        image: [image]
      }
    });
  } else if (submission.kind === "edit") {
    const files = {};
    const docx = submissionFile(submission, "docx");
    const image = submissionFile(submission, "image");
    if (docx) {
      files.docx = [docx];
    }
    if (image) {
      files.image = [image];
    }
    result = editArticle({
      body: {
        slug: submission.slug || "",
        title: submission.title || "",
        author: submission.author || "",
        summary: submission.summary || "",
        body: submission.body || "",
        body_html: submission.body_html || "",
        body_blocks_json: JSON.stringify(submission.body_blocks || []),
        categories: submission.categories || [],
        tags: fieldCsvText(submission.tags || []),
        hashtags: fieldCsvText(submission.hashtags || [])
      },
      files
    });
  } else if (submission.kind === "delete") {
    result = deleteArticle(submission.slug || "");
  } else {
    throw createError(400, "Tipo de solicitacao pendente invalido.");
  }

  submission.status = "approved";
  submission.approved_at = new Date().toISOString().slice(0, 19);
  items[index] = submission;
  writeSubmissions(items);
  return result;
}

function readStats() {
  const raw = readJsonFile(STATS_FILE, { articles: {} });
  return raw.articles && typeof raw.articles === "object" ? raw.articles : {};
}

function writeStats(stats) {
  writeJsonFile(STATS_FILE, { articles: stats });
}

function recordStat(slug, kind) {
  if (!slug || !["views", "pdf_downloads"].includes(kind)) {
    return;
  }
  const stats = readStats();
  const entry = stats[slug] || { views: 0, pdf_downloads: 0, updated_at: "" };
  entry[kind] = Number(entry[kind] || 0) + 1;
  entry.updated_at = new Date().toISOString().slice(0, 19);
  stats[slug] = entry;
  writeStats(stats);
}

function articleSlugFromRequestPath(requestPath) {
  const parts = String(requestPath || "").split("/").filter(Boolean);
  if (parts[0] !== "artigos" || parts.length < 2) {
    return null;
  }
  if (parts.length === 2 || (parts.length === 3 && parts[2] === "index.html")) {
    return parts[1];
  }
  return null;
}

function pdfSlugFromRequestPath(requestPath) {
  const parts = String(requestPath || "").split("/").filter(Boolean);
  if (parts[0] !== "pdfs" || parts.length !== 2 || !parts[1].toLowerCase().endsWith(".pdf")) {
    return null;
  }
  return path.parse(parts[1]).name;
}

function dashboardRows() {
  const stats = readStats();
  const rows = loadUploadPageArticles().map((article) => {
    const entry = stats[article.slug] || {};
    return {
      slug: article.slug,
      title: article.title,
      views: Number(entry.views || 0),
      pdf_downloads: Number(entry.pdf_downloads || 0),
      published_label: article.published_label || formatLongDate(Date.now()),
      article_url: article.article_url || `/artigos/${article.slug}/`,
      pdf_url: article.pdf_url || `/pdfs/${article.slug}.pdf`
    };
  });
  rows.sort((left, right) => {
    if (right.views !== left.views) {
      return right.views - left.views;
    }
    if (right.pdf_downloads !== left.pdf_downloads) {
      return right.pdf_downloads - left.pdf_downloads;
    }
    return left.title.localeCompare(right.title, "pt-BR");
  });
  return rows;
}

app.get("/api/members/session", (req, res) => {
  const member = currentMember(req);
  res.json({
    ok: true,
    authenticated: Boolean(member),
    member
  });
});

app.post("/api/members/register", (req, res, next) => {
  try {
    const name = validateName(req.body.name);
    const email = validateEmail(req.body.email);
    const password = validatePassword(req.body.password);
    const role = normalizeMemberRole(req.body.role);
    const members = readMembers();
    if (members[email]) {
      throw createError(409, "Ja existe um membro cadastrado com este e-mail.");
    }
    members[email] = {
      name,
      email,
      ...hashPassword(password),
      created_at: new Date().toISOString().slice(0, 19),
      role,
      approved: false,
      approved_at: ""
    };
    writeMembers(members);
    res.status(201).json({
      ok: true,
      message: "Cadastro enviado para aprovacao do Conselho Editorial.",
      member: publicMemberPayload(members[email])
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/members/login", (req, res, next) => {
  try {
    const email = validateEmail(req.body.email);
    const password = validatePassword(req.body.password);
    const members = readMembers();
    const member = members[email];
    if (!verifyPassword(password, member)) {
      throw createError(401, "E-mail ou senha invalidos.");
    }
    if (!member.approved) {
      throw createError(403, "Cadastro aguardando aprovacao do Conselho Editorial.");
    }
    const token = createSession(email);
    res.cookie(SESSION_COOKIE_NAME, token, {
      httpOnly: true,
      sameSite: "lax",
      maxAge: SESSION_MAX_AGE
    });
    res.json({
      ok: true,
      message: "Login realizado com sucesso.",
      member: publicMemberPayload(member)
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/members/logout", (req, res) => {
  const token = req.cookies[SESSION_COOKIE_NAME];
  if (token) {
    sessions.delete(token);
  }
  res.clearCookie(SESSION_COOKIE_NAME);
  res.json({
    ok: true,
    authenticated: false,
    member: null
  });
});

app.get("/api/members/notices", requireMember, (_req, res) => {
  res.json({
    ok: true,
    items: readNotices()
  });
});

app.post("/api/members/notices", requireMember, (req, res, next) => {
  try {
    const item = addNotice(req.member, req.body.message);
    res.status(201).json({
      ok: true,
      message: "Recado publicado com sucesso.",
      item
    });
  } catch (error) {
    next(error);
  }
});

app.get("/api/members/dashboard", requireMember, (_req, res) => {
  res.json({
    ok: true,
    items: dashboardRows()
  });
});

app.get("/api/members/approvals", requireMember, requireAdmin, (req, res) => {
  const submissions = pendingSubmissionItems().map((item) => ({
    id: String(item.id || "").trim(),
    kind: String(item.kind || "").trim(),
    title: String(item.title || item.slug || item.source_name || "Sem titulo").trim(),
    slug: String(item.slug || "").trim(),
    requested_at: String(item.requested_at || "").trim(),
    requested_by: item.requested_by || {},
    categories: Array.isArray(item.categories) ? item.categories.filter(Boolean) : []
  }));
  res.json({
    ok: true,
    member: req.member,
    registrations: pendingMemberRegistrations(),
    submissions
  });
});

app.post("/api/members/approvals/registrations/approve", requireMember, requireAdmin, (req, res, next) => {
  try {
    const approved = approveMemberRegistration(req.body.email);
    res.json({
      ok: true,
      message: "Cadastro aprovado com sucesso.",
      member: req.member,
      approved_registration: approved
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/members/approvals/submissions/approve", requireMember, requireAdmin, (req, res, next) => {
  try {
    const result = approveSubmissionItem(req.body.id);
    res.json({
      ok: true,
      message: "Publicacao aprovada com sucesso.",
      member: req.member,
      result
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/docx-import", requireMember, upload.single("docx"), async (req, res, next) => {
  try {
    const imported = saveImportedDocx(req.file);
    const payload = await previewDocxFile(req.file);
    res.json({
      ...payload,
      import_id: imported.import_id,
      source_name: imported.originalname
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/docx-preview", requireMember, upload.single("docx"), async (req, res, next) => {
  try {
    const imported = saveImportedDocx(req.file);
    const payload = await previewDocxFile(req.file);
    res.json({
      ...payload,
      import_id: imported.import_id,
      source_name: imported.originalname
    });
  } catch (error) {
    next(error);
  }
});

app.post("/api/upload", requireMember, upload.fields([
  { name: "docx", maxCount: 1 },
  { name: "image", maxCount: 1 }
]), (req, res, next) => {
  try {
    const payload = createArticleSubmission(req, req.member);
    res.status(202).json(payload);
  } catch (error) {
    next(error);
  }
});

app.post("/api/edit", requireMember, upload.fields([
  { name: "docx", maxCount: 1 },
  { name: "image", maxCount: 1 }
]), (req, res, next) => {
  try {
    const payload = editArticleSubmission(req, req.member);
    res.status(202).json(payload);
  } catch (error) {
    next(error);
  }
});

app.post("/api/delete", requireMember, (req, res, next) => {
  try {
    const payload = deleteArticleSubmission(req, req.member);
    res.status(202).json(payload);
  } catch (error) {
    next(error);
  }
});

app.use((req, _res, next) => {
  const articleSlug = articleSlugFromRequestPath(req.path);
  if (articleSlug) {
    recordStat(articleSlug, "views");
  }
  const pdfSlug = pdfSlugFromRequestPath(req.path);
  if (pdfSlug) {
    recordStat(pdfSlug, "pdf_downloads");
  }
  next();
});

app.use("/vendor/tinymce", express.static(TINYMCE_DIR));
app.use("/vendor/ckeditor", express.static(CKEDITOR_DIR));
app.use("/vendor/quill", express.static(QUILL_DIST_DIR));
app.use(express.static(SITE_DIR, { extensions: ["html"] }));

app.get("/", (_req, res) => {
  res.sendFile(path.join(SITE_DIR, "index.html"));
});

app.use((req, res) => {
  res.status(404).json({
    ok: false,
    error: `Rota nao encontrada: ${req.path}`
  });
});

app.use((error, _req, res, _next) => {
  const status = Number(error.status || 500);
  res.status(status).json({
    ok: false,
    error: error.message || "Falha interna no servidor Node."
  });
});

const port = Number(process.env.PORT || 3000);
app.listen(port, () => {
  console.log(`Servidor Node Barravento pronto em http://127.0.0.1:${port}`);
});
