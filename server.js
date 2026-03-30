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
const PYTHON_VENDOR_DIR = path.join(ROOT, ".python-packages");
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
const DOCX_IMPORT_TTL_MS = 1000 * 60 * 60 * 24;
const NOTICE_RETENTION_MS = 1000 * 60 * 60 * 24 * 60;
const DASHBOARD_HISTORY_DAYS = 365;
const GEO_LOOKUP_URL = "https://ipwho.is/";
const GEO_LOOKUP_TIMEOUT_MS = 2500;
const geoLookupCache = new Map();

const SESSION_COOKIE_NAME = "barravento_member_session";
const SESSION_MAX_AGE = 1000 * 60 * 60 * 24 * 7;
const PASSWORD_ROUNDS = 240000;
const DOCX_MAX_BYTES = 8 * 1024 * 1024;
const IMAGE_MAX_BYTES = 10 * 1024 * 1024;
const MULTIPART_FILE_MAX_BYTES = Math.max(DOCX_MAX_BYTES, IMAGE_MAX_BYTES);
const ALLOWED_IMAGE_SUFFIXES = new Set([".jpg", ".jpeg", ".png", ".webp"]);
const DOCX_MIME_TYPES = new Set([
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/octet-stream",
  "application/zip"
]);
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
const rateLimitBuckets = new Map();
const uploadDocx = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: DOCX_MAX_BYTES,
    files: 1,
    fields: 10
  }
});
const uploadArticle = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: MULTIPART_FILE_MAX_BYTES,
    files: 2,
    fields: 30
  }
});
const app = express();

app.disable("x-powered-by");
app.use(cookieParser());
app.use(express.json({ limit: "2mb" }));
app.use(express.urlencoded({ extended: true, limit: "200kb" }));
app.use((req, res, next) => {
  const secureRequest = req.secure || String(req.headers["x-forwarded-proto"] || "").toLowerCase() === "https";
  const csp = [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'self'",
    "form-action 'self'",
    "img-src 'self' data: https:",
    "font-src 'self' data: https:",
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self' 'unsafe-inline'",
    "connect-src 'self' https://ipwho.is",
    "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com https://player.vimeo.com"
  ].join("; ");
  res.setHeader("Content-Security-Policy", csp);
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "SAMEORIGIN");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  if (secureRequest) {
    res.setHeader("Strict-Transport-Security", "max-age=15552000; includeSubDomains");
  }
  if (req.path.startsWith("/api/members/") || req.path.startsWith("/membros/previas/")) {
    res.setHeader("Cache-Control", "no-store");
  }
  next();
});

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

function bucketKeyFromRequest(req) {
  const forwarded = req.headers["x-forwarded-for"];
  return normalizeClientIp(forwarded || req.ip || req.socket?.remoteAddress || "") || "desconhecido";
}

function createRateLimiter({ name, windowMs, max, message }) {
  return (req, _res, next) => {
    const now = Date.now();
    const key = `${name}:${bucketKeyFromRequest(req)}`;
    const current = rateLimitBuckets.get(key);
    const active = current && current.resetAt > now
      ? current
      : { count: 0, resetAt: now + windowMs };
    active.count += 1;
    rateLimitBuckets.set(key, active);

    if (rateLimitBuckets.size > 5000) {
      for (const [entryKey, entry] of rateLimitBuckets.entries()) {
        if (!entry || entry.resetAt <= now) {
          rateLimitBuckets.delete(entryKey);
        }
      }
    }

    if (active.count > max) {
      const retryAfterSeconds = Math.max(1, Math.ceil((active.resetAt - now) / 1000));
      next(Object.assign(createError(429, message), { retryAfter: retryAfterSeconds }));
      return;
    }
    next();
  };
}

function startsWithBytes(buffer, bytes) {
  if (!Buffer.isBuffer(buffer) || !Array.isArray(bytes) || buffer.length < bytes.length) {
    return false;
  }
  return bytes.every((byte, index) => buffer[index] === byte);
}

function hasZipSignature(buffer) {
  return (
    startsWithBytes(buffer, [0x50, 0x4b, 0x03, 0x04]) ||
    startsWithBytes(buffer, [0x50, 0x4b, 0x05, 0x06]) ||
    startsWithBytes(buffer, [0x50, 0x4b, 0x07, 0x08])
  );
}

function validateDocxFile(file, { required = false } = {}) {
  if (!file || !file.buffer?.length) {
    if (required) {
      throw createError(400, "Selecione um arquivo .docx para continuar.");
    }
    return null;
  }
  const originalname = sanitizeDocxName(file.originalname);
  const mimetype = String(file.mimetype || "").trim().toLowerCase();
  if (mimetype && !DOCX_MIME_TYPES.has(mimetype)) {
    throw createError(400, "Envie apenas arquivos DOCX validos.");
  }
  if (Number(file.size || file.buffer.length || 0) > DOCX_MAX_BYTES) {
    throw createError(413, "O arquivo DOCX excede o limite de 8 MB.");
  }
  if (!hasZipSignature(file.buffer)) {
    throw createError(400, "O arquivo enviado nao parece ser um DOCX valido.");
  }
  const hasContentTypes = file.buffer.includes(Buffer.from("[Content_Types].xml"));
  const hasWordDocument = file.buffer.includes(Buffer.from("word/document.xml"));
  if (!hasContentTypes || !hasWordDocument) {
    throw createError(400, "O arquivo enviado nao parece ser um DOCX valido.");
  }
  return { ...file, originalname };
}

function validateImageFile(file, { required = false } = {}) {
  if (!file || !file.buffer?.length) {
    if (required) {
      throw createError(400, "Selecione uma imagem de capa para publicar.");
    }
    return null;
  }
  const suffix = sanitizeImageName(file.originalname);
  if (Number(file.size || file.buffer.length || 0) > IMAGE_MAX_BYTES) {
    throw createError(413, "A imagem excede o limite de 10 MB.");
  }
  const jpeg = startsWithBytes(file.buffer, [0xff, 0xd8, 0xff]);
  const png = startsWithBytes(file.buffer, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const webp = startsWithBytes(file.buffer, [0x52, 0x49, 0x46, 0x46]) && file.buffer.slice(8, 12).toString("ascii") === "WEBP";
  const validBySuffix = (
    ((suffix === ".jpg" || suffix === ".jpeg") && jpeg) ||
    (suffix === ".png" && png) ||
    (suffix === ".webp" && webp)
  );
  if (!validBySuffix) {
    throw createError(400, "A imagem enviada nao corresponde ao formato informado.");
  }
  return file;
}

const authRateLimit = createRateLimiter({
  name: "auth",
  windowMs: 15 * 60 * 1000,
  max: 10,
  message: "Muitas tentativas de autenticacao. Aguarde alguns minutos e tente novamente."
});

const registerRateLimit = createRateLimiter({
  name: "register",
  windowMs: 60 * 60 * 1000,
  max: 5,
  message: "Muitos cadastros enviados deste endereco. Aguarde um pouco antes de tentar de novo."
});

const docxImportRateLimit = createRateLimiter({
  name: "docx-import",
  windowMs: 15 * 60 * 1000,
  max: 20,
  message: "Muitas importacoes de DOCX em pouco tempo. Aguarde alguns minutos."
});

const memberWriteRateLimit = createRateLimiter({
  name: "member-write",
  windowMs: 15 * 60 * 1000,
  max: 40,
  message: "Muitas operacoes enviadas em pouco tempo. Aguarde um pouco e tente novamente."
});

const approvalRateLimit = createRateLimiter({
  name: "approval-write",
  windowMs: 10 * 60 * 1000,
  max: 60,
  message: "Muitas acoes de aprovacao em pouco tempo. Aguarde alguns instantes."
});

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
  const safeFile = validateDocxFile(file, { required: true });
  const [htmlResult, textResult] = await Promise.all([
    mammoth.convertToHtml(
      { buffer: safeFile.buffer },
      {
        ignoreEmptyParagraphs: false,
        includeDefaultStyleMap: true,
        includeEmbeddedStyleMap: true
      }
    ),
    mammoth.extractRawText({ buffer: safeFile.buffer })
  ]);
  const html = sanitizeArticleHtml(htmlResult.value || "");
  const rawText = normalizeEditorValue(textResult.value || "");
  const lines = rawText.split(/\n+/).map((item) => compactWhitespace(item)).filter(Boolean);
  const guessedTitle = lines[0] || path.parse(safeFile.originalname).name;
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

function cleanupImportedDocx(importId) {
  const safeId = path.basename(String(importId || "").trim());
  if (!safeId) {
    return;
  }
  deleteIfExists(importedDocxFilePath(safeId));
  deleteIfExists(importedDocxMetaPath(safeId));
}

function cleanupExpiredImportedDocx(maxAgeMs = DOCX_IMPORT_TTL_MS) {
  if (!fs.existsSync(DOCX_IMPORTS_DIR)) {
    return;
  }
  const now = Date.now();
  for (const entry of fs.readdirSync(DOCX_IMPORTS_DIR)) {
    const fullPath = path.join(DOCX_IMPORTS_DIR, entry);
    const stat = fs.statSync(fullPath);
    if (!stat.isFile() || !entry.toLowerCase().endsWith(".json")) {
      continue;
    }
    const metadata = readJsonFile(fullPath, {});
    const stamp = String(metadata.last_used_at || metadata.created_at || "").trim();
    const recordedTime = stamp ? new Date(stamp).getTime() : 0;
    const referenceTime = Number.isFinite(recordedTime) && recordedTime > 0 ? recordedTime : stat.mtimeMs;
    if (now - referenceTime <= maxAgeMs) {
      continue;
    }
    const importId = entry.replace(/\.json$/i, "");
    cleanupImportedDocx(importId);
  }

  for (const entry of fs.readdirSync(DOCX_IMPORTS_DIR)) {
    const fullPath = path.join(DOCX_IMPORTS_DIR, entry);
    const stat = fs.statSync(fullPath);
    if (!stat.isFile() || !entry.toLowerCase().endsWith(".docx")) {
      continue;
    }
    if (fs.existsSync(importedDocxMetaPath(entry))) {
      continue;
    }
    if (now - stat.mtimeMs > maxAgeMs) {
      deleteIfExists(fullPath);
    }
  }
}

function saveImportedDocx(file) {
  const safeFile = validateDocxFile(file, { required: true });
  const originalname = safeFile.originalname;
  cleanupExpiredImportedDocx();
  ensureDir(DOCX_IMPORTS_DIR);
  const hash = crypto.createHash("sha256").update(safeFile.buffer).digest("hex").slice(0, 24);
  const importId = `${hash}-${slugify(path.parse(originalname).name) || "texto"}.docx`;
  const docxPath = importedDocxFilePath(importId);
  if (!fs.existsSync(docxPath)) {
    fs.writeFileSync(docxPath, safeFile.buffer);
  }
  writeJsonFile(importedDocxMetaPath(importId), {
    import_id: importId,
    originalname,
    size: safeFile.buffer.length,
    created_at: new Date().toISOString().slice(0, 19),
    last_used_at: new Date().toISOString().slice(0, 19)
  });
  return {
    import_id: importId,
    originalname
  };
}

function loadImportedDocx(importId) {
  cleanupExpiredImportedDocx();
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
  writeJsonFile(importedDocxMetaPath(safeId), {
    import_id: safeId,
    originalname: sanitizeDocxName(metadata.originalname || safeId),
    size: buffer.length,
    created_at: String(metadata.created_at || "").trim() || new Date().toISOString().slice(0, 19),
    last_used_at: new Date().toISOString().slice(0, 19)
  });
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
    return validateDocxFile(imported, { required });
  }
  const direct = req.files?.docx?.[0];
  if (direct?.buffer?.length) {
    return validateDocxFile(direct, { required });
  }
  if (required) {
    throw createError(400, message || "Selecione um arquivo .docx para continuar.");
  }
  return null;
}

function releaseRequestImportedDocx(req) {
  cleanupImportedDocx(req?.body?.docx_import_id);
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
    if (name === "font-weight") {
      if (/^(normal|bold|bolder|lighter|[1-9]00)$/i.test(input)) {
        allowed.push(`${name}:${input.toLowerCase()}`);
      }
      continue;
    }
    if (name === "font-style") {
      if (/^(normal|italic|oblique)$/i.test(input)) {
        allowed.push(`${name}:${input.toLowerCase()}`);
      }
      continue;
    }
    if (name === "text-decoration") {
      const normalized = input.toLowerCase().replace(/\s+/g, " ").trim();
      if (/^(none|underline|line-through|underline line-through|line-through underline)$/.test(normalized)) {
        allowed.push(`${name}:${normalized}`);
      }
      continue;
    }
    if (name === "line-height") {
      if (/^([0-9]+(\.[0-9]+)?)(px|pt|em|rem|%)?$/i.test(input) || /^(normal)$/i.test(input)) {
        allowed.push(`${name}:${input}`);
      }
      continue;
    }
    if (name === "letter-spacing") {
      if (/^-?([0-9]+(\.[0-9]+)?)(px|pt|em|rem)$/i.test(input) || /^(normal)$/i.test(input)) {
        allowed.push(`${name}:${input}`);
      }
      continue;
    }
    if (name === "white-space") {
      if (/^(normal|pre|pre-wrap|pre-line|nowrap)$/i.test(input)) {
        allowed.push(`${name}:${input.toLowerCase()}`);
      }
      continue;
    }
    if (name === "margin-left" || name === "padding-left" || name === "text-indent") {
      if (/^-?([0-9]+(\.[0-9]+)?)(px|pt|em|rem|%)$/i.test(input)) {
        allowed.push(`${name}:${input}`);
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
  const vendorDir = PYTHON_VENDOR_DIR;
  const buildScript = process.platform === "win32" ? "scripts\\gerar_site.py" : "scripts/gerar_site.py";
  const embeddedBootstrap = [
    "import runpy, sys",
    `sys.path.insert(0, r"${vendorDir.replace(/\\/g, "\\\\")}")`,
    `runpy.run_path(r"${path.join(ROOT, buildScript).replace(/\\/g, "\\\\")}", run_name="__main__")`
  ].join("; ");
  const commands = process.platform === "win32"
    ? [
        ["python", [buildScript]],
        ["python3", [buildScript]],
        ["py", ["-3", buildScript]],
        ["C:\\Program Files\\FormatFactory\\FFModules\\python\\python.exe", ["-c", embeddedBootstrap]]
      ]
    : [
        ["python3", [buildScript]],
        ["python", [buildScript]]
      ];

  let lastError = null;
  for (const [command, args] of commands) {
    const result = spawnSync(command, args, {
      cwd: ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONPATH: vendorDir + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : "")
      }
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
  const image = validateImageFile(req.files?.image?.[0], { required: true });

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
  const nowStamp = new Date().toISOString().slice(0, 19);
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
    image_caption: "Imagem enviada na publicacao.",
    created_at: nowStamp,
    updated_at: nowStamp
  };
  if (bodyHtml || bodyBlocks.length || body) {
    const nextBodyBlocks = bodyBlocks.length ? bodyBlocks : blocksToSidecar(body || richHtmlToText(bodyHtml));
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
  const nowStamp = new Date().toISOString().slice(0, 19);

  const newDocx = resolveDocxInput(req);
  const currentDocxBytes = fs.readFileSync(docxPath);
  const docxChanged = Boolean(newDocx && newDocx.buffer && !newDocx.buffer.equals(currentDocxBytes));

  const newImage = validateImageFile(req.files?.image?.[0]);
  let imageChanged = false;
  const currentImageName = currentSidecar.image_file || "";
  const currentImagePath = currentImageName ? path.join(UPLOADS_DIR, currentImageName) : null;
  if (newImage && newImage.buffer?.length) {
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
    image_caption: imageCaption,
    created_at: String(currentSidecar.created_at || "").trim() || nowStamp,
    updated_at: nowStamp
  };

  if (bodyChanged) {
    const nextBodyBlocks = bodyBlocks.length ? bodyBlocks : blocksToSidecar(body || richHtmlToText(bodyHtml));
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
  let changed = false;
  const now = Date.now();
  const kept = items.filter((item) => {
    if (!item || !item.message) {
      changed = true;
      return false;
    }
    const stamp = String(item.created_at || "").trim();
    const createdTime = stamp ? new Date(stamp).getTime() : 0;
    const keep = !createdTime || !Number.isFinite(createdTime) || now - createdTime <= NOTICE_RETENTION_MS;
    if (!keep) {
      changed = true;
    }
    return keep;
  });
  if (changed) {
    writeJsonFile(NOTICES_FILE, { items: kept.slice(0, 200) });
  }
  return kept;
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
    created_at: new Date().toISOString().slice(0, 19),
    scope: "public",
    variant: "neutral"
  };
  const notices = readNotices();
  notices.unshift(notice);
  writeJsonFile(NOTICES_FILE, { items: notices.slice(0, 200) });
  return notice;
}

function memberVisibleNotices(member) {
  const viewerEmail = normalizeEmail(member?.email);
  return readNotices().filter((item) => {
    const scope = String(item.scope || "public").trim().toLowerCase();
    if (scope !== "private") {
      return true;
    }
    return normalizeEmail(item.recipient_email) === viewerEmail;
  });
}

function addSubmissionOutcomeNotice(submission, outcome, reason = "") {
  const recipientEmail = normalizeEmail(submission?.requested_by?.email);
  if (!recipientEmail) {
    return null;
  }
  const normalizedOutcome = outcome === "rejected" ? "rejected" : "approved";
  const normalizedReason = String(reason || "").replace(/\r\n/g, "\n").trim();
  const actionLabel = submission?.kind === "edit"
    ? "edicao"
    : submission?.kind === "delete"
      ? "exclusao"
      : "publicacao";
  const title = String(submission?.title || submission?.slug || submission?.source_name || "Solicitacao").trim();
  const message = normalizedOutcome === "approved"
    ? `Sua ${actionLabel} de "${title}" foi aprovada pelo Conselho Editorial.`
    : `Sua ${actionLabel} de "${title}" foi recusada pelo Conselho Editorial.${normalizedReason ? `\n\nMotivo: ${normalizedReason}` : ""}`;
  const notice = {
    id: crypto.randomBytes(8).toString("hex"),
    message,
    author_name: "Conselho Editorial",
    author_email: "",
    created_at: new Date().toISOString().slice(0, 19),
    scope: "private",
    recipient_email: recipientEmail,
    variant: normalizedOutcome === "approved" ? "success" : "danger",
    title,
    related_submission_id: String(submission?.id || "").trim()
  };
  const notices = readNotices();
  notices.unshift(notice);
  writeJsonFile(NOTICES_FILE, { items: notices.slice(0, 200) });
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

function submissionDirPath(submissionId) {
  return path.join(SUBMISSIONS_DIR, String(submissionId || "").trim());
}

function saveSubmissionFile(submissionId, file, suffixOverride) {
  if (!file || !file.buffer?.length) {
    return "";
  }
  const targetDir = submissionDirPath(submissionId);
  ensureDir(targetDir);
  const suffix = suffixOverride || path.extname(file.originalname || "");
  const safeBase = slugify(path.parse(file.originalname || "arquivo").name);
  const targetName = `${safeBase}${suffix}`;
  fs.writeFileSync(path.join(targetDir, targetName), file.buffer);
  return targetName;
}

function submissionPreviewFilePath(submissionId) {
  return path.join(submissionDirPath(submissionId), "preview.html");
}

function submissionPreviewAssetUrl(submissionId, filename) {
  const safeId = encodeURIComponent(String(submissionId || "").trim());
  const safeName = encodeURIComponent(path.basename(String(filename || "").trim()));
  if (!safeId || !safeName) {
    return "";
  }
  return `/membros/previas/submissoes/${safeId}/arquivo/${safeName}`;
}

function renderSubmissionPreviewBlocks(bodyBlocks) {
  const blocks = parseBodyBlocksField(bodyBlocks);
  if (!blocks.length) {
    return "";
  }
  return blocks.map((block) => {
    const alignClass = block.align && block.align !== "left" ? ` article-body__block--${block.align}` : "";
    if (block.kind === "heading") {
      const level = Math.max(1, Math.min(3, Number(block.level || 2) || 2));
      return `<h${level + 1} class="article-body__heading${alignClass}">${escapeHtml(block.text || "")}</h${level + 1}>`;
    }
    if (block.kind === "divider") {
      return '<hr class="article-body__divider">';
    }
    if (block.kind === "quote") {
      return `<blockquote class="article-body__quote${alignClass}">${block.html || `<p>${escapeHtml(block.text || "")}</p>`}</blockquote>`;
    }
    if (block.kind === "list") {
      return `<div class="article-body__list${alignClass}">${block.html || ""}</div>`;
    }
    return `<p class="article-body__paragraph${alignClass}">${block.html || escapeHtml(block.text || "")}</p>`;
  }).join("\n");
}

function resolveSubmissionPreviewImage(submission) {
  const imageFile = String(submission.image_file || "").trim();
  if (imageFile) {
    return submissionPreviewAssetUrl(submission.id, imageFile);
  }
  const slug = slugify(submission.slug);
  if (!slug) {
    return "";
  }
  const currentArticle = loadArticleBySlug(slug);
  if (!currentArticle || !currentArticle.image_file) {
    return "";
  }
  return `/${currentArticle.image_scope || "uploads"}/${encodeURIComponent(currentArticle.image_file)}`;
}

function buildSubmissionPreviewHtml(submission) {
  const title = String(submission.title || submission.slug || submission.source_name || "Sem titulo").trim();
  const author = String(submission.author || "").trim();
  const summary = String(submission.summary || "").trim();
  const categories = Array.isArray(submission.categories) ? submission.categories.filter(Boolean) : [];
  const requestedBy = submission.requested_by && typeof submission.requested_by === "object" ? submission.requested_by : {};
  const requestedAt = String(submission.requested_at || "").trim();
  const previewImage = resolveSubmissionPreviewImage(submission);
  const bodyHtml = sanitizeArticleHtml(submission.body_html || "");
  const renderedBlocks = renderSubmissionPreviewBlocks(submission.body_blocks || []);
  const articleBody = bodyHtml || renderedBlocks || "<p>Previa indisponivel para esta solicitacao.</p>";
  const categoryBadges = categories.length
    ? categories.map((category) => `<span class="category-badge">${escapeHtml(category)}</span>`).join("")
    : "";

  return `<!DOCTYPE html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Previa interna | ${escapeHtml(title)}</title>
    <link rel="stylesheet" href="/styles/site.css">
    <style>
      body.preview-page { background: #f6f1eb; }
      .preview-shell { padding: 32px 0 64px; }
      .preview-banner { margin-bottom: 24px; padding: 18px 22px; border: 1px solid rgba(141, 47, 35, 0.16); border-radius: 18px; background: rgba(255, 255, 255, 0.92); color: #4d342d; }
      .preview-banner strong { display: block; margin-bottom: 4px; color: #8d2f23; font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase; }
      .preview-banner p { margin: 0; }
      .preview-meta { display: flex; flex-wrap: wrap; gap: 12px 18px; margin-top: 10px; font-size: 0.95rem; color: #6d554c; }
      .preview-meta span { white-space: nowrap; }
      .preview-summary { margin: 18px 0 0; font-size: 1.05rem; color: #4b3a34; }
      .preview-categories { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 0; }
      .preview-cover { margin: 24px 0 0; }
      .preview-cover img { width: 100%; max-height: 520px; object-fit: cover; border-radius: 24px; display: block; }
      .article-body__block--center, .article-body__paragraph--center, .article-body__heading--center, .article-body__quote--center, .article-body__list--center { text-align: center; }
      .article-body__block--right, .article-body__paragraph--right, .article-body__heading--right, .article-body__quote--right, .article-body__list--right { text-align: right; }
      .article-body__block--justify, .article-body__paragraph--justify, .article-body__heading--justify, .article-body__quote--justify, .article-body__list--justify { text-align: justify; }
      .article-body__divider { margin: 2.5rem 0; border: 0; border-top: 1px solid rgba(141, 47, 35, 0.18); }
      .article-body__quote { margin: 2rem 0; padding-left: 20px; border-left: 3px solid #8d2f23; color: #5c4540; }
      .article-body__list ul, .article-body__list ol { padding-left: 1.4rem; }
    </style>
  </head>
  <body class="preview-page">
    <main class="preview-shell">
      <div class="container">
        <section class="preview-banner">
          <strong>Previa interna para aprovacao</strong>
          <p>Este HTML pertence a uma submissao pendente e nao fica visivel no site publico ate a aprovacao do Conselho Editorial.</p>
          <div class="preview-meta">
            <span>Solicitado por: ${escapeHtml(requestedBy.name || requestedBy.email || "Membro")}</span>
            <span>Perfil: ${escapeHtml(requestedBy.role_label || requestedBy.role || "membro")}</span>
            <span>Enviado em: ${escapeHtml(requestedAt)}</span>
          </div>
        </section>

        <article class="article-page">
          <header class="article-hero">
            <div class="article-hero__copy">
              ${categoryBadges ? `<div class="preview-categories">${categoryBadges}</div>` : ""}
              <h1>${escapeHtml(title)}</h1>
              ${author ? `<p class="article-hero__author">${escapeHtml(author)}</p>` : ""}
              ${summary ? `<p class="preview-summary">${escapeHtml(summary)}</p>` : ""}
            </div>
            ${previewImage ? `<figure class="preview-cover"><img src="${escapeHtml(previewImage)}" alt="${escapeHtml(title)}"></figure>` : ""}
          </header>
          <section class="article-body prose">
            ${articleBody}
          </section>
        </article>
      </div>
    </main>
  </body>
</html>`;
}

function writeSubmissionPreview(submission) {
  if (!submission || typeof submission !== "object") {
    return "";
  }
  if (!["create", "edit"].includes(String(submission.kind || "").trim())) {
    return "";
  }
  const targetDir = submissionDirPath(submission.id);
  ensureDir(targetDir);
  const previewPath = submissionPreviewFilePath(submission.id);
  fs.writeFileSync(previewPath, buildSubmissionPreviewHtml(submission), "utf8");
  return previewPath;
}

function compactSubmissionPayload(payload) {
  const next = { ...(payload || {}) };
  const bodyBlocks = parseBodyBlocksField(next.body_blocks || []);
  if (bodyBlocks.length) {
    next.body_blocks = bodyBlocks;
    delete next.body;
    delete next.body_html;
  }
  return next;
}

function clearSubmissionArtifacts(submission) {
  if (!submission || typeof submission !== "object") {
    return submission;
  }
  deleteIfExists(submissionDirPath(submission.id));
  const next = { ...submission };
  delete next.docx_file;
  delete next.image_file;
  return next;
}

function cleanupStoredSubmissions() {
  const items = readSubmissions();
  let changed = false;
  const nextItems = items.map((item) => {
    let next = compactSubmissionPayload(item);
    if (JSON.stringify(next) !== JSON.stringify(item)) {
      changed = true;
    }
    if (String(next.status || "pending") !== "pending") {
      const cleaned = clearSubmissionArtifacts(next);
      if (JSON.stringify(cleaned) !== JSON.stringify(next)) {
        changed = true;
      }
      return cleaned;
    }
    return next;
  });
  if (changed) {
    writeSubmissions(nextItems);
  }
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
    ...compactSubmissionPayload(payload)
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
  writeSubmissionPreview(submission);
  writeSubmissions(items);
  return submission;
}

function createArticleSubmission(req, member) {
  const docx = resolveDocxInput(req, { required: true, message: "Selecione um arquivo .docx para publicar." });
  const image = validateImageFile(req.files?.image?.[0], { required: true });
  const title = requireArticleTitle(req.body.title);
  const categories = parseCategories(req.body.categories);
  const body = normalizeEditorValue(req.body.body);
  const bodyHtml = sanitizeArticleHtml(req.body.body_html);
  const bodyBlocks = parseBodyBlocksField(req.body.body_blocks_json);
  const nextBodyBlocks = bodyBlocks.length ? bodyBlocks : blocksToSidecar(body || richHtmlToText(bodyHtml));
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
  releaseRequestImportedDocx(req);
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

  const newImage = validateImageFile(req.files?.image?.[0]);
  let imageChanged = false;
  const currentImageName = currentSidecar.image_file || "";
  const currentImagePath = currentImageName ? path.join(UPLOADS_DIR, currentImageName) : null;
  if (newImage && newImage.buffer?.length) {
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
      body_blocks: bodyBlocks.length ? bodyBlocks : blocksToSidecar(body || richHtmlToText(bodyHtml)),
      categories,
      tags,
      hashtags
    },
    docx: newDocx,
    image: newImage
  });
  releaseRequestImportedDocx(req);

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
  const targetPath = path.join(submissionDirPath(submission.id), storedName);
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
  items[index] = clearSubmissionArtifacts(compactSubmissionPayload(submission));
  writeSubmissions(items);
  return result;
}

function rejectSubmissionItem(submissionId) {
  const items = readSubmissions();
  const index = items.findIndex((item) => String(item.id || "") === String(submissionId || ""));
  if (index < 0) {
    throw createError(404, "Solicitacao pendente nao encontrada.");
  }

  const submission = items[index];
  if (String(submission.status || "pending") !== "pending") {
    throw createError(400, "Esta solicitacao ja foi processada.");
  }

  submission.status = "rejected";
  submission.rejected_at = new Date().toISOString().slice(0, 19);
  items[index] = clearSubmissionArtifacts(compactSubmissionPayload(submission));
  writeSubmissions(items);
  return {
    ok: true,
    id: String(submission.id || "").trim(),
    title: String(submission.title || submission.slug || submission.source_name || "Sem titulo").trim()
  };
}

function readStats() {
  const raw = readJsonFile(STATS_FILE, { articles: {} });
  const source = raw.articles && typeof raw.articles === "object" ? raw.articles : {};
  const normalized = {};
  for (const [slug, entry] of Object.entries(source)) {
    if (!entry || typeof entry !== "object") {
      continue;
    }
    const views = Number(entry.views || 0);
    const pdfDownloads = Number(entry.pdf_downloads || 0);
    const updatedAt = String(entry.updated_at || "").trim();
    const dailySource = entry.daily && typeof entry.daily === "object" ? entry.daily : {};
    const locationsSource = entry.locations && typeof entry.locations === "object" ? entry.locations : {};
    const dailyLocationsSource = entry.daily_locations && typeof entry.daily_locations === "object" ? entry.daily_locations : {};
    const daily = {};
    const locations = {};
    const dailyLocations = {};
    for (const [dateKey, dayEntry] of Object.entries(dailySource)) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateKey || "")) || !dayEntry || typeof dayEntry !== "object") {
        continue;
      }
      daily[dateKey] = {
        views: Number(dayEntry.views || 0),
        pdf_downloads: Number(dayEntry.pdf_downloads || 0)
      };
    }
    for (const [locationKey, count] of Object.entries(locationsSource)) {
      if (!String(locationKey || "").trim()) {
        continue;
      }
      locations[locationKey] = Number(count || 0);
    }
    for (const [dateKey, locationEntry] of Object.entries(dailyLocationsSource)) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateKey || "")) || !locationEntry || typeof locationEntry !== "object") {
        continue;
      }
      dailyLocations[dateKey] = {};
      for (const [locationKey, count] of Object.entries(locationEntry)) {
        if (!String(locationKey || "").trim()) {
          continue;
        }
        dailyLocations[dateKey][locationKey] = Number(count || 0);
      }
    }
    if (!Object.keys(daily).length && updatedAt && (views > 0 || pdfDownloads > 0)) {
      daily[updatedAt.slice(0, 10)] = {
        views,
        pdf_downloads: pdfDownloads
      };
    }
    normalized[slug] = {
      views,
      pdf_downloads: pdfDownloads,
      updated_at: updatedAt,
      daily,
      locations: pruneLocationTotals(locations),
      daily_locations: Object.fromEntries(
        Object.entries(dailyLocations)
          .sort((left, right) => left[0].localeCompare(right[0]))
          .slice(-DASHBOARD_HISTORY_DAYS)
          .map(([dayKey, locationEntry]) => [dayKey, pruneLocationTotals(locationEntry, 80)])
      )
    };
  }
  return normalized;
}

function writeStats(stats) {
  writeJsonFile(STATS_FILE, { articles: stats });
}

function pruneDailyStats(daily) {
  const entries = Object.entries(daily || {}).sort((left, right) => left[0].localeCompare(right[0]));
  const trimmed = entries.slice(-DASHBOARD_HISTORY_DAYS);
  return Object.fromEntries(trimmed);
}

function pruneLocationTotals(locations, limit = 250) {
  return Object.fromEntries(
    Object.entries(locations || {})
      .filter((entry) => entry[0] && Number(entry[1] || 0) > 0)
      .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))
      .slice(0, limit)
  );
}

function startOfDay(dateLike = Date.now()) {
  const value = new Date(dateLike);
  value.setHours(0, 0, 0, 0);
  return value;
}

function parseDashboardPeriod(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (value === "all") {
    return { key: "all", days: 0, label: "Todo o periodo" };
  }
  const allowed = new Map([
    ["7", "Ultimos 7 dias"],
    ["30", "Ultimos 30 dias"],
    ["90", "Ultimos 90 dias"],
    ["365", "Ultimos 365 dias"]
  ]);
  if (allowed.has(value)) {
    return { key: value, days: Number(value), label: allowed.get(value) };
  }
  return { key: "30", days: 30, label: "Ultimos 30 dias" };
}

function listPeriodDays(period) {
  const today = startOfDay();
  if (!period.days) {
    return [];
  }
  const days = [];
  for (let offset = period.days - 1; offset >= 0; offset -= 1) {
    const current = new Date(today);
    current.setDate(current.getDate() - offset);
    days.push(current.toISOString().slice(0, 10));
  }
  return days;
}

function normalizeLocationKey(country, region, city) {
  const parts = [country, region, city]
    .map((item) => String(item || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return parts.join("|");
}

function formatLocationLabel(locationKey) {
  return String(locationKey || "")
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean)
    .join(" / ");
}

function normalizeClientIp(rawValue) {
  const source = Array.isArray(rawValue) ? rawValue[0] : String(rawValue || "").split(",")[0] || "";
  const trimmed = String(source || "").trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.replace(/^::ffff:/i, "");
}

function isPrivateIp(ip) {
  if (!ip) {
    return true;
  }
  if (ip === "::1" || ip === "127.0.0.1" || ip === "localhost") {
    return true;
  }
  if (/^10\./.test(ip) || /^192\.168\./.test(ip) || /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip)) {
    return true;
  }
  if (/^fc|^fd|^fe80/i.test(ip)) {
    return true;
  }
  return false;
}

function requestClientIp(req) {
  const forwarded = req.headers["x-forwarded-for"];
  return normalizeClientIp(forwarded || req.ip || req.socket?.remoteAddress || "");
}

async function resolveLocationFromIp(ip) {
  const safeIp = normalizeClientIp(ip);
  if (!safeIp || isPrivateIp(safeIp)) {
    return {
      country: "Local",
      region: "Rede local",
      city: "Desenvolvimento",
      key: "Local|Rede local|Desenvolvimento"
    };
  }
  if (geoLookupCache.has(safeIp)) {
    return geoLookupCache.get(safeIp);
  }
  try {
    const response = await fetch(`${GEO_LOOKUP_URL}${encodeURIComponent(safeIp)}`, {
      signal: AbortSignal.timeout(GEO_LOOKUP_TIMEOUT_MS)
    });
    const payload = await response.json().catch(() => ({}));
    const location = {
      country: String(payload.country_code || payload.country || "Desconhecido").trim() || "Desconhecido",
      region: String(payload.region_code || payload.region || "Sem regiao").trim() || "Sem regiao",
      city: String(payload.city || "Sem cidade").trim() || "Sem cidade"
    };
    location.key = normalizeLocationKey(location.country, location.region, location.city);
    if (geoLookupCache.size > 5000) {
      geoLookupCache.clear();
    }
    geoLookupCache.set(safeIp, location);
    return location;
  } catch {
    const fallback = {
      country: "Desconhecido",
      region: "Desconhecido",
      city: "Desconhecido",
      key: "Desconhecido|Desconhecido|Desconhecido"
    };
    if (geoLookupCache.size > 5000) {
      geoLookupCache.clear();
    }
    geoLookupCache.set(safeIp, fallback);
    return fallback;
  }
}

function articleStatsForPeriod(entry, period) {
  const safeEntry = entry && typeof entry === "object" ? entry : {};
  const daily = safeEntry.daily && typeof safeEntry.daily === "object" ? safeEntry.daily : {};
  if (!period.days) {
    return {
      views: Number(safeEntry.views || 0),
      pdf_downloads: Number(safeEntry.pdf_downloads || 0)
    };
  }
  let views = 0;
  let pdfDownloads = 0;
  for (const dayKey of listPeriodDays(period)) {
    const dayEntry = daily[dayKey] || {};
    views += Number(dayEntry.views || 0);
    pdfDownloads += Number(dayEntry.pdf_downloads || 0);
  }
  return { views, pdf_downloads: pdfDownloads };
}

function articleLocationCountsForPeriod(entry, period) {
  const safeEntry = entry && typeof entry === "object" ? entry : {};
  const locations = safeEntry.locations && typeof safeEntry.locations === "object" ? safeEntry.locations : {};
  const dailyLocations = safeEntry.daily_locations && typeof safeEntry.daily_locations === "object" ? safeEntry.daily_locations : {};
  if (!period.days) {
    return { ...locations };
  }
  const totals = {};
  for (const dayKey of listPeriodDays(period)) {
    const dayLocations = dailyLocations[dayKey] && typeof dailyLocations[dayKey] === "object" ? dailyLocations[dayKey] : {};
    for (const [locationKey, count] of Object.entries(dayLocations)) {
      totals[locationKey] = Number(totals[locationKey] || 0) + Number(count || 0);
    }
  }
  return totals;
}

function dashboardSeries(stats, rows, period) {
  const labels = period.days ? listPeriodDays(period) : (() => {
    const keys = new Set();
    for (const row of rows) {
      const entry = stats[row.slug];
      const daily = entry && typeof entry.daily === "object" ? entry.daily : {};
      Object.keys(daily).forEach((key) => keys.add(key));
    }
    return Array.from(keys).sort((left, right) => left.localeCompare(right)).slice(-DASHBOARD_HISTORY_DAYS);
  })();

  return labels.map((dayKey) => {
    let views = 0;
    let pdfDownloads = 0;
    for (const row of rows) {
      const entry = stats[row.slug];
      const dayEntry = entry && entry.daily ? entry.daily[dayKey] || {} : {};
      views += Number(dayEntry.views || 0);
      pdfDownloads += Number(dayEntry.pdf_downloads || 0);
    }
    return {
      label: dayKey,
      views,
      pdf_downloads: pdfDownloads
    };
  });
}

function dashboardPie(rows) {
  return rows
    .filter((item) => Number(item.views || 0) > 0)
    .slice(0, 5)
    .map((item) => ({
      label: item.title,
      value: Number(item.views || 0)
    }));
}

function dashboardLocations(stats, rows, period) {
  const totals = {};
  for (const row of rows) {
    const entry = stats[row.slug];
    const locationCounts = articleLocationCountsForPeriod(entry, period);
    for (const [locationKey, count] of Object.entries(locationCounts)) {
      totals[locationKey] = Number(totals[locationKey] || 0) + Number(count || 0);
    }
  }
  return Object.entries(totals)
    .filter((entry) => Number(entry[1] || 0) > 0)
    .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))
    .slice(0, 8)
    .map(([key, value]) => ({
      key,
      label: formatLocationLabel(key),
      value: Number(value || 0)
    }));
}

async function recordStat(slug, kind, req) {
  if (!slug || !["views", "pdf_downloads"].includes(kind)) {
    return;
  }
  const stats = readStats();
  const entry = stats[slug] || { views: 0, pdf_downloads: 0, updated_at: "", daily: {}, locations: {}, daily_locations: {} };
  const dayKey = new Date().toISOString().slice(0, 10);
  const dayEntry = entry.daily && typeof entry.daily === "object" ? (entry.daily[dayKey] || { views: 0, pdf_downloads: 0 }) : { views: 0, pdf_downloads: 0 };
  const location = await resolveLocationFromIp(requestClientIp(req));
  const locationKey = normalizeLocationKey(location.country, location.region, location.city);
  const dayLocations = entry.daily_locations && typeof entry.daily_locations === "object"
    ? (entry.daily_locations[dayKey] && typeof entry.daily_locations[dayKey] === "object" ? entry.daily_locations[dayKey] : {})
    : {};
  entry[kind] = Number(entry[kind] || 0) + 1;
  entry.updated_at = new Date().toISOString().slice(0, 19);
  dayEntry[kind] = Number(dayEntry[kind] || 0) + 1;
  entry.daily = pruneDailyStats({
    ...(entry.daily && typeof entry.daily === "object" ? entry.daily : {}),
    [dayKey]: dayEntry
  });
  entry.locations = pruneLocationTotals({
    ...(entry.locations && typeof entry.locations === "object" ? entry.locations : {}),
    [locationKey]: Number((entry.locations && entry.locations[locationKey]) || 0) + 1
  });
  entry.daily_locations = Object.fromEntries(
    Object.entries({
      ...(entry.daily_locations && typeof entry.daily_locations === "object" ? entry.daily_locations : {}),
      [dayKey]: pruneLocationTotals({
        ...dayLocations,
        [locationKey]: Number(dayLocations[locationKey] || 0) + 1
      }, 80)
    })
      .sort((left, right) => left[0].localeCompare(right[0]))
      .slice(-DASHBOARD_HISTORY_DAYS)
  );
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

function dashboardRows(period) {
  const stats = readStats();
  const rows = loadUploadPageArticles().map((article) => {
    const entry = stats[article.slug] || {};
    const filtered = articleStatsForPeriod(entry, period);
    return {
      slug: article.slug,
      title: article.title,
      views: Number(filtered.views || 0),
      pdf_downloads: Number(filtered.pdf_downloads || 0),
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

app.post("/api/members/register", requireMember, requireAdmin, registerRateLimit, (req, res, next) => {
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

app.post("/api/members/login", authRateLimit, (req, res, next) => {
  try {
    const email = validateEmail(req.body.email);
    const password = validatePassword(req.body.password);
    const members = readMembers();
    const member = members[email];
    if (!member || !verifyPassword(password, member) || !member.approved) {
      throw createError(401, "Nao foi possivel concluir o login com essas credenciais.");
    }
    const token = createSession(email);
    const secureCookie = req.secure || String(req.headers["x-forwarded-proto"] || "").toLowerCase() === "https";
    res.cookie(SESSION_COOKIE_NAME, token, {
      httpOnly: true,
      sameSite: "strict",
      secure: secureCookie,
      path: "/",
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
  const secureCookie = req.secure || String(req.headers["x-forwarded-proto"] || "").toLowerCase() === "https";
  res.clearCookie(SESSION_COOKIE_NAME, {
    httpOnly: true,
    sameSite: "strict",
    secure: secureCookie,
    path: "/"
  });
  res.json({
    ok: true,
    authenticated: false,
    member: null
  });
});

app.get("/api/members/notices", requireMember, (req, res) => {
  res.json({
    ok: true,
    items: memberVisibleNotices(req.member)
  });
});

app.post("/api/members/notices", requireMember, memberWriteRateLimit, (req, res, next) => {
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

app.get("/api/members/dashboard", requireMember, (req, res) => {
  const period = parseDashboardPeriod(req.query.period);
  const stats = readStats();
  const items = dashboardRows(period);
  const totals = items.reduce((acc, item) => {
    acc.views += Number(item.views || 0);
    acc.pdf_downloads += Number(item.pdf_downloads || 0);
    return acc;
  }, { views: 0, pdf_downloads: 0 });
  res.json({
    ok: true,
    period,
    totals,
    items,
    series: dashboardSeries(stats, items, period),
    pie: dashboardPie(items),
    locations: dashboardLocations(stats, items, period)
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
    categories: Array.isArray(item.categories) ? item.categories.filter(Boolean) : [],
    preview_url: ["create", "edit"].includes(String(item.kind || "").trim())
      ? `/membros/previas/submissoes/${encodeURIComponent(String(item.id || "").trim())}`
      : (item.slug ? `/artigos/${item.slug}/` : "")
  }));
  res.json({
    ok: true,
    member: req.member,
    registrations: pendingMemberRegistrations(),
    submissions
  });
});

app.post("/api/members/approvals/registrations/approve", requireMember, requireAdmin, approvalRateLimit, (req, res, next) => {
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

app.post("/api/members/approvals/submissions/approve", requireMember, requireAdmin, approvalRateLimit, (req, res, next) => {
  try {
    const result = approveSubmissionItem(req.body.id);
    const items = readSubmissions();
    const approvedItem = items.find((item) => String(item.id || "") === String(req.body.id || ""));
    if (approvedItem) {
      addSubmissionOutcomeNotice(approvedItem, "approved");
    }
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

app.post("/api/members/approvals/submissions/reject", requireMember, requireAdmin, approvalRateLimit, (req, res, next) => {
  try {
    const reason = String(req.body.reason || "").replace(/\r\n/g, "\n").trim();
    if (reason.length < 3) {
      throw createError(400, "Informe um motivo curto para a recusa.");
    }
    const result = rejectSubmissionItem(req.body.id);
    const items = readSubmissions();
    const rejectedItem = items.find((item) => String(item.id || "") === String(req.body.id || ""));
    if (rejectedItem) {
      addSubmissionOutcomeNotice(rejectedItem, "rejected", reason);
    }
    res.json({
      ok: true,
      message: "Publicacao recusada com sucesso.",
      member: req.member,
      result
    });
  } catch (error) {
    next(error);
  }
});

app.get("/membros/previas/submissoes/:id", requireMember, requireAdmin, (req, res, next) => {
  try {
    const submissionId = String(req.params.id || "").trim();
    const submission = readSubmissions().find((item) => String(item.id || "") === submissionId);
    if (!submission || String(submission.status || "pending") !== "pending") {
      throw createError(404, "Previa da submissao nao encontrada.");
    }
    const previewPath = submissionPreviewFilePath(submissionId);
    if (!fs.existsSync(previewPath)) {
      writeSubmissionPreview(submission);
    }
    if (!fs.existsSync(previewPath)) {
      throw createError(404, "Arquivo de previa nao encontrado.");
    }
    res.sendFile(previewPath);
  } catch (error) {
    next(error);
  }
});

app.get("/membros/previas/submissoes/:id/arquivo/:filename", requireMember, requireAdmin, (req, res, next) => {
  try {
    const submissionId = String(req.params.id || "").trim();
    const filename = path.basename(String(req.params.filename || "").trim());
    const submission = readSubmissions().find((item) => String(item.id || "") === submissionId);
    if (!submission || String(submission.status || "pending") !== "pending") {
      throw createError(404, "Arquivo temporario da submissao nao encontrado.");
    }
    const targetPath = path.join(submissionDirPath(submissionId), filename);
    if (!fs.existsSync(targetPath)) {
      throw createError(404, "Arquivo temporario da submissao nao encontrado.");
    }
    res.sendFile(targetPath);
  } catch (error) {
    next(error);
  }
});

app.post("/api/docx-import", requireMember, docxImportRateLimit, uploadDocx.single("docx"), async (req, res, next) => {
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

app.post("/api/docx-preview", requireMember, docxImportRateLimit, uploadDocx.single("docx"), async (req, res, next) => {
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

app.post("/api/upload", requireMember, memberWriteRateLimit, uploadArticle.fields([
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

app.post("/api/edit", requireMember, memberWriteRateLimit, uploadArticle.fields([
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

app.post("/api/delete", requireMember, memberWriteRateLimit, (req, res, next) => {
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
    void recordStat(articleSlug, "views", req);
  }
  const pdfSlug = pdfSlugFromRequestPath(req.path);
  if (pdfSlug) {
    void recordStat(pdfSlug, "pdf_downloads", req);
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
  if (error instanceof multer.MulterError) {
    const message = error.code === "LIMIT_FILE_SIZE"
      ? `O arquivo enviado excede o limite permitido. DOCX: 8 MB. Imagem: 10 MB.`
      : "Nao foi possivel processar o upload enviado.";
    res.status(400).json({
      ok: false,
      error: message
    });
    return;
  }
  const status = Number(error.status || 500);
  if (error.retryAfter) {
    res.setHeader("Retry-After", String(error.retryAfter));
  }
  res.status(status).json({
    ok: false,
    error: error.message || "Falha interna no servidor Node."
  });
});

cleanupExpiredImportedDocx();
cleanupStoredSubmissions();

const port = Number(process.env.PORT || 3000);
app.listen(port, () => {
  console.log(`Servidor Node Barravento pronto em http://127.0.0.1:${port}`);
});
