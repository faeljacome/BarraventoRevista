
        (() => {
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
          const loginPageHref = "../membros/";
          const panelPageHref = "../painel/#member-panel";
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

          function escapeHtml(value) {
            return String(value).replace(/[&<>"']/g, (char) => {
              const map = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
              return map[char] || char;
            });
          }

          function suspiciousScore(value) {
            const matches = String(value || "").match(/[ÃÂâ€™œž¢€]/g);
            return matches ? matches.length : 0;
          }

          function repairText(value) {
            const text = String(value ?? "");
            if (!text || suspiciousScore(text) === 0) {
              return text;
            }
            try {
              const repaired = decodeURIComponent(escape(text));
              return suspiciousScore(repaired) <= suspiciousScore(text) ? repaired : text;
            } catch (_error) {
              return text;
            }
          }

          function repairValue(value) {
            if (typeof value === "string") {
              return repairText(value);
            }
            if (Array.isArray(value)) {
              return value.map((item) => repairValue(item));
            }
            if (value && typeof value === "object") {
              return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, repairValue(item)]));
            }
            return value;
          }

          function getToastHost() {
            if (toastHost && document.body.contains(toastHost)) {
              return toastHost;
            }
            toastHost = document.createElement("div");
            toastHost.className = "member-toast-host";
            toastHost.setAttribute("aria-live", "polite");
            toastHost.setAttribute("aria-atomic", "false");
            document.body.appendChild(toastHost);
            return toastHost;
          }

          function showToast(kind, html) {
            const host = getToastHost();
            const toast = document.createElement("article");
            toast.className = "member-toast member-toast--" + kind;
            toast.innerHTML = '<div class="member-toast__body">' + html + '</div><button class="member-toast__close" type="button" aria-label="Fechar notificacao">Fechar</button>';
            host.appendChild(toast);
            const close = () => {
              toast.classList.add("is-leaving");
              window.setTimeout(() => {
                if (toast.parentNode) {
                  toast.parentNode.removeChild(toast);
                }
              }, 220);
            };
            const closeButton = toast.querySelector(".member-toast__close");
            if (closeButton) {
              closeButton.addEventListener("click", close);
            }
            const timeout = kind === "error" ? 5200 : (kind === "pending" ? 2400 : 3600);
            window.setTimeout(close, timeout);
          }

          function setStatus(node, kind, html) {
            node.className = "upload-status is-" + kind;
            node.innerHTML = html;
            if (node && node.dataset && node.dataset.popupStatus === "true" && html) {
              showToast(kind, html);
            }
          }

          function clearStatus(node) {
            node.className = "upload-status";
            node.innerHTML = "";
          }

          function storePanelMemberState(current) {
            try {
              if (current) {
                localStorage.setItem(panelStateKey, JSON.stringify({
                  member: current,
                  saved_at: new Date().toISOString()
                }));
              } else {
                localStorage.removeItem(panelStateKey);
              }
            } catch (error) {
              return;
            }
          }

          function readStoredPanelMemberState() {
            try {
              const stored = JSON.parse(localStorage.getItem(panelStateKey) || "null");
              if (!stored || typeof stored !== "object" || !stored.member) {
                return null;
              }
              return stored.member;
            } catch (error) {
              return null;
            }
          }

          function describeCreateRequirements() {
            if (!createForm) {
              return { valid: true, message: "" };
            }
            const missing = [];
            const titleField = formField(createForm, "title");
            const imageField = formField(createForm, "image");
            const titleValue = String(titleField ? titleField.value : "").trim();
            const hasDocx = Boolean(createDocxInput && createDocxInput.files && createDocxInput.files[0]);
            const hasImage = Boolean(imageField && imageField.files && imageField.files[0]);
            const hasCategories = getCheckedValues(createForm).length > 0;
            const hasBody = collectEditorBlocks(getCreateEditorHtml()).length > 0;

            if (!member) {
              missing.push("entre como membro");
            }
            if (!hasDocx) {
              missing.push("selecione o DOCX");
            }
            if (!hasImage) {
              missing.push("adicione a imagem de capa");
            }
            if (!hasCategories) {
              missing.push("marque ao menos uma categoria");
            }
            if (!titleValue) {
              missing.push("preencha o titulo");
            }
            if (!hasBody) {
              missing.push("importe e revise o corpo do texto");
            }

            return missing.length
              ? { valid: false, message: "Faltando para publicar: " + missing.join("; ") + "." }
              : { valid: true, message: "" };
          }

          function updateCreateSubmitState() {
            if (!createSubmitActions || !createSubmitButton) {
              return;
            }
            const state = describeCreateRequirements();
            createSubmitButton.disabled = !state.valid;
            createSubmitButton.setAttribute("aria-disabled", state.valid ? "false" : "true");
            createSubmitButton.title = state.message;
            createSubmitActions.title = state.message;
            createSubmitActions.dataset.disabledReason = state.message;
            createSubmitActions.classList.toggle("is-disabled", !state.valid);
          }

          popupStatusNodes.forEach((node) => {
            node.dataset.popupStatus = "true";
          });

          function normalizeInlineText(value) {
            return repairText(String(value || "").replace(/\u00a0/g, " ")).replace(/[ \t]+/g, " ").trim();
          }

          function normalizeMultilineText(value) {
            return repairText(String(value || "").replace(/\r\n/g, "\n").replace(/\u00a0/g, " "));
          }

          function htmlToText(html) {
            const probe = document.createElement("div");
            probe.innerHTML = html;
            return normalizeInlineText(probe.textContent || "");
          }

          function sanitizeUrl(value) {
            const text = String(value || "").trim();
            if (!text) {
              return "";
            }
            if (/^(https?:|mailto:|#|\/)/i.test(text)) {
              return text;
            }
            if (/^[\w.-]+@[\w.-]+\.[A-Za-z]{2,}$/.test(text)) {
              return "mailto:" + text;
            }
            if (/^[\w.-]+\.[A-Za-z]{2,}/.test(text)) {
              return "https://" + text;
            }
            return "";
          }

          function normalizeAlign(value) {
            const text = String(value || "").trim().toLowerCase();
            return ["left", "center", "right", "justify"].includes(text) ? text : "left";
          }

          function detectBlockAlign(node) {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) {
              return "left";
            }
            return normalizeAlign(node.style.textAlign || node.getAttribute("align") || "");
          }

          function sanitizeInlineNodes(nodes) {
            return nodes.map((node) => sanitizeInlineNode(node)).join("");
          }

          function sanitizeInlineStyleValue(value) {
            const allowed = [];
            String(value || "").split(";").forEach((chunk) => {
              const [rawName, ...rawRest] = chunk.split(":");
              const name = String(rawName || "").trim().toLowerCase();
              const input = rawRest.join(":").trim();
              if (!name || !input) {
                return;
              }
              if (name === "text-align") {
                const normalized = input.toLowerCase();
                if (["left", "center", "right", "justify"].includes(normalized)) {
                  allowed.push(name + ":" + normalized);
                }
                return;
              }
              if (name === "color" || name === "background-color") {
                if (/^(#[0-9a-f]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z-]+)$/i.test(input)) {
                  allowed.push(name + ":" + input);
                }
                return;
              }
              if (name === "font-size") {
                if (/^([0-9]{1,3}(\.[0-9]+)?)(px|pt|em|rem|%)$/i.test(input) || /^(xx-small|x-small|small|medium|large|x-large|xx-large)$/i.test(input)) {
                  allowed.push(name + ":" + input);
                }
                return;
              }
              if (name === "font-family") {
                const safeFamily = input.replace(/[^a-z0-9,\- "'_]/gi, "").trim();
                if (safeFamily) {
                  allowed.push(name + ":" + safeFamily);
                }
                return;
              }
              if (name === "font-weight") {
                if (/^(normal|bold|bolder|lighter|[1-9]00)$/i.test(input)) {
                  allowed.push(name + ":" + input.toLowerCase());
                }
                return;
              }
              if (name === "font-style") {
                if (/^(normal|italic|oblique)$/i.test(input)) {
                  allowed.push(name + ":" + input.toLowerCase());
                }
                return;
              }
              if (name === "text-decoration") {
                const normalized = input.toLowerCase().replace(/\s+/g, " ").trim();
                if (/^(none|underline|line-through|underline line-through|line-through underline)$/.test(normalized)) {
                  allowed.push(name + ":" + normalized);
                }
                return;
              }
              if (name === "line-height") {
                if (/^([0-9]+(\.[0-9]+)?)(px|pt|em|rem|%)?$/i.test(input) || /^(normal)$/i.test(input)) {
                  allowed.push(name + ":" + input);
                }
                return;
              }
              if (name === "letter-spacing") {
                if (/^-?([0-9]+(\.[0-9]+)?)(px|pt|em|rem)$/i.test(input) || /^(normal)$/i.test(input)) {
                  allowed.push(name + ":" + input);
                }
                return;
              }
              if (name === "white-space") {
                if (/^(normal|pre|pre-wrap|pre-line|nowrap)$/i.test(input)) {
                  allowed.push(name + ":" + input.toLowerCase());
                }
                return;
              }
              if (name === "margin-left" || name === "padding-left" || name === "text-indent") {
                if (/^-?([0-9]+(\.[0-9]+)?)(px|pt|em|rem|%)$/i.test(input)) {
                  allowed.push(name + ":" + input);
                }
              }
            });
            return allowed.join("; ");
          }

          function sanitizeInlineNode(node) {
            if (node.nodeType === Node.TEXT_NODE) {
              return escapeHtml(node.textContent || "");
            }
            if (node.nodeType !== Node.ELEMENT_NODE) {
              return "";
            }
            const tag = node.tagName.toLowerCase();
            if (tag === "br") {
              return "<br>";
            }
            if (["strong", "b", "em", "i", "u", "sup", "sub", "s", "span", "code"].includes(tag)) {
              const style = sanitizeInlineStyleValue(node.getAttribute("style") || "");
              const attrs = style ? ' style="' + escapeHtml(style) + '"' : "";
              return "<" + tag + attrs + ">" + sanitizeInlineNodes(Array.from(node.childNodes)) + "</" + tag + ">";
            }
            if (tag === "a") {
              const href = sanitizeUrl(node.getAttribute("href") || node.textContent || "");
              const inner = sanitizeInlineNodes(Array.from(node.childNodes)) || escapeHtml(node.textContent || href);
              if (!href) {
                return inner;
              }
              return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + inner + "</a>";
            }
            return sanitizeInlineNodes(Array.from(node.childNodes));
          }

          function serializeFallback(node) {
            const text = normalizeInlineText(node.textContent || "");
            if (!text) {
              return null;
            }
            return {
              kind: "paragraph",
              text,
              level: 0,
              html: escapeHtml(text).replace(/\n/g, "<br>"),
              align: detectBlockAlign(node)
            };
          }

          function serializeParagraph(node) {
            const html = sanitizeInlineNodes(Array.from(node.childNodes)).trim();
            const text = htmlToText(html);
            if (!text) {
              return serializeFallback(node);
            }
            return {
              kind: "paragraph",
              text,
              level: 0,
              html,
              align: detectBlockAlign(node)
            };
          }

          function serializeHeading(node) {
            const text = normalizeInlineText(node.textContent || "");
            if (!text) {
              return null;
            }
            const tag = node.tagName.toLowerCase();
            const level = tag === "h3" ? 3 : tag === "h1" ? 1 : 2;
            return {
              kind: "heading",
              text,
              level,
              html: "",
              align: detectBlockAlign(node)
            };
          }

          function serializeDivider() {
            return {
              kind: "divider",
              text: "---",
              level: 0,
              html: "",
              align: "left"
            };
          }

          function serializeQuote(node) {
            const directParagraphs = Array.from(node.children).filter((child) => child.tagName && child.tagName.toLowerCase() === "p");
            const inner = directParagraphs.length
              ? directParagraphs.map((child) => {
                  const paragraph = serializeParagraph(child);
                  return paragraph ? "<p>" + paragraph.html + "</p>" : "";
                }).join("")
              : (() => {
                  const paragraph = serializeParagraph(node);
                  return paragraph ? "<p>" + paragraph.html + "</p>" : "";
                })();
            const text = htmlToText(inner);
            if (!text) {
              return null;
            }
            return {
              kind: "quote",
              text,
              level: 0,
              html: inner,
              align: detectBlockAlign(node)
            };
          }

          function serializeList(node) {
            const tag = node.tagName.toLowerCase() === "ol" ? "ol" : "ul";
            const items = Array.from(node.children)
              .filter((child) => child.tagName && child.tagName.toLowerCase() === "li")
              .map((child) => sanitizeInlineNodes(Array.from(child.childNodes)).trim())
              .filter(Boolean);
            if (!items.length) {
              return null;
            }
            const html = "<" + tag + ">" + items.map((item) => "<li>" + item + "</li>").join("") + "</" + tag + ">";
            return {
              kind: "list",
              text: items.map((item) => htmlToText(item)).join(" • "),
              level: tag === "ol" ? 1 : 0,
              html,
              align: detectBlockAlign(node)
            };
          }

          function collectEditorBlocks(editorHtml) {
            const blocks = [];
            const probe = document.createElement("div");
            probe.innerHTML = String(editorHtml || "");
            const nodes = Array.from(probe.childNodes);
            if (!nodes.length && normalizeInlineText(probe.textContent || "")) {
              const fallback = serializeParagraph(probe);
              return fallback ? [fallback] : [];
            }

            nodes.forEach((node) => {
              if (node.nodeType === Node.TEXT_NODE) {
                const text = normalizeInlineText(node.textContent || "");
                if (text) {
                  blocks.push({
                    kind: "paragraph",
                    text,
                    level: 0,
                    html: escapeHtml(text)
                  });
                }
                return;
              }
              if (node.nodeType !== Node.ELEMENT_NODE) {
                return;
              }
              const tag = node.tagName.toLowerCase();
              let block = null;
              if (tag === "h1" || tag === "h2" || tag === "h3") {
                block = serializeHeading(node);
              } else if (tag === "hr") {
                block = serializeDivider();
              } else if (tag === "blockquote") {
                block = serializeQuote(node);
              } else if (tag === "ul" || tag === "ol") {
                block = serializeList(node);
              } else if (tag === "div" && node.children.length === 1 && (node.children[0].tagName.toLowerCase() === "ul" || node.children[0].tagName.toLowerCase() === "ol")) {
                block = serializeList(node.children[0]);
                if (block) {
                  block.align = detectBlockAlign(node);
                }
              } else {
                block = serializeFallback(node);
              }
              if (block) {
                blocks.push(block);
              }
            });
            return blocks;
          }

          function inlineHtmlToMarkup(html) {
            let markup = String(html || "").trim();
            markup = markup.replace(/<br\s*\/?>/gi, "\n");
            markup = markup.replace(/<sup>\s*(\[[^\]]+\])\s*<\/sup>/gi, "$1");
            markup = markup.replace(/<a [^>]*href="([^"]+)"[^>]*>(.*?)<\/a>/gi, "$2 ($1)");
            markup = markup.replace(/<(strong|b)>(.*?)<\/\1>/gi, "**$2**");
            markup = markup.replace(/<(em|i)>(.*?)<\/\1>/gi, "*$2*");
            markup = markup.replace(/<u>(.*?)<\/u>/gi, "$1");
            markup = markup.replace(/<[^>]+>/g, "");
            return normalizeMultilineText(markup).trim();
          }

          function blocksToLegacyMarkup(blocks) {
            return blocks.map((block) => {
              if (block.kind === "heading") {
                const prefix = block.level >= 3 ? "### " : block.level === 1 ? "# " : "## ";
                return prefix + normalizeInlineText(block.text);
              }
              if (block.kind === "list") {
                const probe = document.createElement("div");
                probe.innerHTML = block.html || "";
                const items = Array.from(probe.querySelectorAll("li"))
                  .map((item, index) => {
                    const text = normalizeInlineText(item.textContent || "");
                    return block.level > 0 ? String(index + 1) + ". " + text : "- " + text;
                  })
                  .filter(Boolean);
                return items.join("\n");
              }
              if (block.kind === "quote") {
                return inlineHtmlToMarkup(block.html || block.text)
                  .split("\n")
                  .map((line) => line ? "> " + line : ">")
                  .join("\n");
              }
              return inlineHtmlToMarkup(block.html || block.text);
            }).filter(Boolean).join("\n\n").trim();
          }

          function renderLegacyMarkup(markup) {
            const value = normalizeMultilineText(markup).trim();
            if (!value) {
              return "";
            }
            return value.split(/\n\s*\n/g).map((chunk) => {
              const piece = chunk.trim();
              if (!piece) {
                return "";
              }
              if (piece.startsWith("### ")) {
                return "<h3>" + escapeHtml(piece.slice(4)) + "</h3>";
              }
              if (piece.startsWith("## ")) {
                return "<h2>" + escapeHtml(piece.slice(3)) + "</h2>";
              }
              if (piece.startsWith("# ")) {
                return "<h2>" + escapeHtml(piece.slice(2)) + "</h2>";
              }
              if (piece.startsWith("- ")) {
                const items = piece.split("\n").map((line) => line.replace(/^-\s*/, "").trim()).filter(Boolean);
                return "<ul>" + items.map((item) => "<li>" + escapeHtml(item) + "</li>").join("") + "</ul>";
              }
              if (/^>\s*/.test(piece)) {
                const html = piece
                  .split("\n")
                  .map((line) => line.replace(/^>\s?/, ""))
                  .filter(Boolean)
                  .map((line) => "<p>" + escapeHtml(line) + "</p>")
                  .join("");
                return "<blockquote>" + html + "</blockquote>";
              }
              let html = escapeHtml(piece);
              html = html.replace(/\*\*(.+?)\*\*/gs, "<strong>$1</strong>");
              html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/gs, "<em>$1</em>");
              html = html.replace(/\[(\d+)\]/g, "<sup>[$1]</sup>");
              return "<p>" + html.replace(/\n/g, "<br>") + "</p>";
            }).join("");
          }

          function getEditorInstance() {
            return window.barraventoEditor || null;
          }

          function getCreateEditorInstance() {
            return window.barraventoCreateEditor || null;
          }

          function registerRichEditorFormats() {
            if (!window.Quill || window.__barraventoQuillFormatsRegistered) {
              return;
            }
            const sizeStyle = window.Quill.import("attributors/style/size");
            const fontStyle = window.Quill.import("attributors/style/font");
            const alignStyle = window.Quill.import("attributors/style/align");
            sizeStyle.whitelist = ["12px", "14px", "16px", "17px", "18px", "20px", "24px", "28px", "32px", "36px"];
            window.Quill.register(sizeStyle, true);
            window.Quill.register(fontStyle, true);
            window.Quill.register(alignStyle, true);
            window.__barraventoQuillFormatsRegistered = true;
          }

          function getEditorHtml() {
            const editor = getEditorInstance();
            if (editor) {
              return repairText(editor.root.innerHTML);
            }
            return repairText(pendingEditorHtml || editBodyEditor.innerHTML || "");
          }

          function updateEditorSummary(html, blocks) {
            const text = normalizeMultilineText(
              String(html || "")
                .replace(/<br\s*\/?>/gi, "\n")
                .replace(/<\/(p|li|blockquote|ul|ol|h[1-6]|tr|div|pre|table)>/gi, "\n")
                .replace(/<[^>]+>/g, " ")
            ).trim();
            const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
            const chars = text.length;
            const reading = Math.max(1, Math.ceil(words / 220));
            if (editorCharCount) {
              editorCharCount.textContent = String(chars);
            }
            if (editorWordCount) {
              editorWordCount.textContent = String(words);
            }
            if (editorReadingTime) {
              editorReadingTime.textContent = reading + " min";
            }
            if (editorBlockCount) {
              editorBlockCount.textContent = String(blocks.length);
            }
            if (editorStatusText) {
              editorStatusText.textContent = words
                ? "Editor pronto para aprovar, exportar e publicar."
                : "O texto sera preservado com HTML rico e enviado para aprovacao.";
            }
            if (editorSummaryPreview) {
              editorSummaryPreview.textContent = text
                ? text.slice(0, 220) + (text.length > 220 ? "..." : "")
                : "Comece a escrever para ver uma previa curta do conteudo.";
            }
          }

          function serializeEditorHtml(html, bodyInput, bodyHtmlInput, bodyBlocksInput) {
            const blocks = collectEditorBlocks(String(html || "").trim());
            bodyHtmlInput.value = String(html || "").trim();
            bodyBlocksInput.value = JSON.stringify(blocks);
            bodyInput.value = blocksToLegacyMarkup(blocks);
            return blocks;
          }

          function getCreateEditorHtml() {
            const editor = getCreateEditorInstance();
            if (editor) {
              return repairText(editor.root.innerHTML);
            }
            return repairText(pendingCreateEditorHtml || createBodyEditor.innerHTML || "");
          }

          function applyHtmlToQuill(editor, html) {
            if (!editor) {
              return;
            }
            const safeHtml = repairText(String(html || ""));
            if (!safeHtml.trim()) {
              editor.setText("");
              return;
            }
            try {
              const converted = editor.clipboard && typeof editor.clipboard.convert === "function"
                ? editor.clipboard.convert({
                    html: safeHtml,
                    text: htmlToText(safeHtml)
                  })
                : null;
              if (converted && typeof editor.setContents === "function") {
                editor.setContents(converted, "silent");
                if (typeof editor.setSelection === "function") {
                  editor.setSelection(0, 0, "silent");
                }
                return;
              }
            } catch (_error) {}
            try {
              if (editor.clipboard && typeof editor.clipboard.dangerouslyPasteHTML === "function") {
                editor.clipboard.dangerouslyPasteHTML(safeHtml, "silent");
                return;
              }
            } catch (_error) {}
            if (editor.root) {
              editor.root.innerHTML = safeHtml;
            }
          }

          function setCreateEditorHtml(html) {
            pendingCreateEditorHtml = repairText(String(html || ""));
            const editor = getCreateEditorInstance();
            if (editor) {
              applyHtmlToQuill(editor, pendingCreateEditorHtml);
            } else if (createBodyEditor) {
              createBodyEditor.innerHTML = pendingCreateEditorHtml;
            }
            syncCreateBodyFields();
          }

          function syncCreateBodyFields() {
            const blocks = serializeEditorHtml(getCreateEditorHtml(), createBodyInput, createBodyHtmlInput, createBodyBlocksInput);
            updateCreateSubmitState();
            return blocks;
          }

          function setEditorHtml(html) {
            pendingEditorHtml = repairText(String(html || ""));
            const editor = getEditorInstance();
            if (editor) {
              applyHtmlToQuill(editor, pendingEditorHtml);
            } else if (editBodyEditor) {
              editBodyEditor.innerHTML = pendingEditorHtml;
            }
            syncEditBodyFields();
          }

          function syncEditBodyFields() {
            const html = getEditorHtml().trim();
            const blocks = serializeEditorHtml(html, editBodyInput, editBodyHtmlInput, editBodyBlocksInput);
            updateEditorSummary(html, blocks);
            return blocks;
          }

          function syncCategoryCombobox(form) {
            const box = form.querySelector("[data-category-combobox]");
            const select = form.querySelector('select[name="categories"]');
            if (!box || !select) {
              return;
            }
            const selected = Array.from(select.selectedOptions).map((option) => option.value);
            box.querySelectorAll("[data-category-checkbox]").forEach((input) => {
              input.checked = selected.includes(input.value);
            });
            const label = box.querySelector(".category-combobox__label");
            const summary = box.querySelector("[data-category-summary]");
            if (label) {
              label.textContent = !selected.length
                ? "Selecionar categorias"
                : selected.length <= 2
                  ? selected.join(", ")
                  : selected.length + " categorias selecionadas";
            }
            if (summary) {
              summary.hidden = selected.length === 0;
              summary.innerHTML = selected.length
                ? selected.map((item) => '<span class="category-combobox__tag">' + escapeHtml(item) + '</span>').join("")
                : "";
            }
            box.classList.toggle("has-selection", selected.length > 0);
            if (form === createForm) {
              updateCreateSubmitState();
            }
          }

          function setCheckedValues(form, values) {
            const items = new Set(values);
            const select = form.querySelector('select[name="categories"]');
            if (!select) {
              return;
            }
            for (const option of select.options) {
              option.selected = items.has(option.value);
            }
            syncCategoryCombobox(form);
          }

          function getCheckedValues(form) {
            const select = form.querySelector('select[name="categories"]');
            if (!select) {
              return [];
            }
            return Array.from(select.selectedOptions).map((option) => option.value);
          }

          function formField(form, name) {
            return form ? form.querySelector('[name="' + name + '"]') : null;
          }

          function csv(values) {
            return values.join(", ");
          }

          function setMultiSelectValues(select, values) {
            if (!select) {
              return;
            }
            const selected = new Set((Array.isArray(values) ? values : []).map((item) => String(item || "")));
            Array.from(select.options).forEach((option) => {
              option.selected = selected.has(option.value);
            });
            const memberBox = select.closest("[data-member-combobox]");
            if (memberBox) {
              syncMemberCombobox(memberBox);
            }
          }

          function getMultiSelectValues(select) {
            if (!select) {
              return [];
            }
            return Array.from(select.selectedOptions).map((option) => option.value);
          }

          function syncMemberCombobox(box) {
            if (!box) {
              return;
            }
            const select = box.querySelector('select[name="author_members"]');
            if (!select) {
              return;
            }
            const selectedOptions = Array.from(select.selectedOptions);
            const selectedValues = selectedOptions.map((option) => option.value);
            box.querySelectorAll("[data-member-checkbox]").forEach((input) => {
              input.checked = selectedValues.includes(input.value);
            });
            const selectedNames = selectedOptions.map((option) => option.textContent.trim()).filter(Boolean);
            const label = box.querySelector(".category-combobox__label");
            const summary = box.querySelector("[data-member-summary]");
            if (label) {
              label.textContent = !selectedNames.length
                ? "Selecionar integrantes"
                : selectedNames.length <= 2
                  ? selectedNames.join(", ")
                  : selectedNames.length + " integrantes selecionados";
            }
            if (summary) {
              summary.hidden = selectedNames.length === 0;
              summary.innerHTML = selectedNames.length
                ? selectedNames.map((item) => '<span class="category-combobox__tag">' + escapeHtml(item) + '</span>').join("")
                : "";
            }
            box.classList.toggle("has-selection", selectedNames.length > 0);
          }

          function renderMemberSelectOptions() {
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
            if (createAuthorMembers) {
              const selected = getMultiSelectValues(createAuthorMembers);
              createAuthorMembers.innerHTML = memberOptions.join("");
              setMultiSelectValues(createAuthorMembers, selected);
            }
            if (editAuthorMembers) {
              const selected = getMultiSelectValues(editAuthorMembers);
              editAuthorMembers.innerHTML = memberOptions.join("");
              setMultiSelectValues(editAuthorMembers, selected);
            }
            document.querySelectorAll("[data-member-options]").forEach((node) => {
              node.innerHTML = memberCheckboxes.length
                ? memberCheckboxes.join("")
                : '<div class="empty-state empty-state--compact"><p>Nenhum integrante aprovado ainda.</p></div>';
              const box = node.closest("[data-member-combobox]");
              if (box) {
                syncMemberCombobox(box);
              }
            });
            if (profileEditorialRole) {
              profileEditorialRole.innerHTML = officeOptions.join("");
            }
          }

          function renderProfilePreview(payload) {
            if (!profilePreview) {
              return;
            }
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
          }

          function syncAuthorFieldWithMembers(form) {
            const select = formField(form, "author_members");
            const authorField = formField(form, "author");
            if (!select || !authorField) {
              return;
            }
            const selectedNames = Array.from(select.selectedOptions).map((option) => option.textContent.trim()).filter(Boolean);
            if (selectedNames.length) {
              authorField.value = selectedNames.join(", ");
            }
          }

          function activateMemberComboboxes() {
            document.querySelectorAll("[data-member-combobox]").forEach((box) => {
              const select = box.querySelector('select[name="author_members"]');
              const toggle = box.querySelector(".category-combobox__toggle");
              const menu = box.querySelector(".category-combobox__menu");
              const search = box.querySelector("[data-member-search]");
              if (!select || !toggle || !menu) {
                return;
              }

              syncMemberCombobox(box);

              toggle.addEventListener("click", () => {
                const nextOpen = menu.hidden;
                document.querySelectorAll("[data-member-combobox] .category-combobox__menu").forEach((node) => {
                  node.hidden = true;
                  const owner = node.closest("[data-member-combobox]");
                  if (owner) {
                    owner.classList.remove("is-open");
                    owner.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                  }
                });
                menu.hidden = !nextOpen;
                box.classList.toggle("is-open", nextOpen);
                toggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
                if (nextOpen && search) {
                  search.focus();
                }
              });

              box.addEventListener("change", (event) => {
                const target = event.target;
                if (!(target instanceof HTMLInputElement) || !target.matches("[data-member-checkbox]")) {
                  return;
                }
                const lookup = new Set(
                  Array.from(box.querySelectorAll("[data-member-checkbox]:checked")).map((item) => item.value)
                );
                Array.from(select.options).forEach((option) => {
                  option.selected = lookup.has(option.value);
                });
                syncMemberCombobox(box);
                const form = box.closest("form");
                if (form) {
                  syncAuthorFieldWithMembers(form);
                  clearStatus(form === editForm ? editStatus : createStatus);
                }
              });

              if (search) {
                search.addEventListener("input", () => {
                  const query = normalizeInlineText(search.value).toLowerCase();
                  box.querySelectorAll(".category-combobox__option").forEach((option) => {
                    const text = normalizeInlineText(option.textContent || "").toLowerCase();
                    option.classList.toggle("is-hidden", Boolean(query) && !text.includes(query));
                  });
                });
              }
            });

            document.addEventListener("click", (event) => {
              if (event.target.closest("[data-member-combobox]")) {
                return;
              }
              document.querySelectorAll("[data-member-combobox] .category-combobox__menu").forEach((menu) => {
                menu.hidden = true;
                const box = menu.closest("[data-member-combobox]");
                if (box) {
                  box.classList.remove("is-open");
                  box.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                }
              });
            });
          }

          function activateCategoryComboboxes() {
            document.querySelectorAll("[data-category-combobox]").forEach((box) => {
              const form = box.closest("form");
              const select = form ? form.querySelector('select[name="categories"]') : null;
              const toggle = box.querySelector(".category-combobox__toggle");
              const menu = box.querySelector(".category-combobox__menu");
              const search = box.querySelector("[data-category-search]");
              if (!form || !select || !toggle || !menu) {
                return;
              }

              syncCategoryCombobox(form);

              toggle.addEventListener("click", () => {
                const nextOpen = menu.hidden;
                document.querySelectorAll("[data-category-combobox] .category-combobox__menu").forEach((node) => {
                  node.hidden = true;
                  const owner = node.closest("[data-category-combobox]");
                  if (owner) {
                    owner.classList.remove("is-open");
                    owner.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                  }
                });
                menu.hidden = !nextOpen;
                box.classList.toggle("is-open", nextOpen);
                toggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
                if (nextOpen && search) {
                  search.focus();
                }
              });

              box.querySelectorAll("[data-category-checkbox]").forEach((input) => {
                input.addEventListener("change", () => {
                  const lookup = new Set(
                    Array.from(box.querySelectorAll("[data-category-checkbox]:checked")).map((item) => item.value)
                  );
                  Array.from(select.options).forEach((option) => {
                    option.selected = lookup.has(option.value);
                  });
                  syncCategoryCombobox(form);
                  clearStatus(form === editForm ? editStatus : createStatus);
                });
              });

              if (search) {
                search.addEventListener("input", () => {
                  const query = normalizeInlineText(search.value).toLowerCase();
                  box.querySelectorAll(".category-combobox__option").forEach((option) => {
                    const text = normalizeInlineText(option.textContent || "").toLowerCase();
                    option.classList.toggle("is-hidden", Boolean(query) && !text.includes(query));
                  });
                });
              }
            });

            document.addEventListener("click", (event) => {
              if (event.target.closest("[data-category-combobox]")) {
                return;
              }
              document.querySelectorAll("[data-category-combobox] .category-combobox__menu").forEach((menu) => {
                menu.hidden = true;
                const box = menu.closest("[data-category-combobox]");
                if (box) {
                  box.classList.remove("is-open");
                  box.querySelector(".category-combobox__toggle")?.setAttribute("aria-expanded", "false");
                }
              });
            });
          }

          function currentEditState() {
            const blocks = syncEditBodyFields();
            const titleField = formField(editForm, "title");
            const authorField = formField(editForm, "author");
            const authorMembersField = formField(editForm, "author_members");
            const summaryField = formField(editForm, "summary");
            const tagsField = formField(editForm, "tags");
            const hashtagsField = formField(editForm, "hashtags");
            return {
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
            };
          }

          function sameState(left, right) {
            return JSON.stringify(left) === JSON.stringify(right);
          }

          function setActiveTab(name) {
            memberTabs.forEach((button) => {
              const active = button.dataset.memberTab === name;
              button.classList.toggle("is-active", active);
            });
            memberTabPanels.forEach((panel) => {
              const active = panel.dataset.memberTabPanel === name;
              panel.classList.toggle("is-active", active);
              panel.hidden = false;
              panel.style.display = active ? "block" : "none";
              panel.setAttribute("aria-hidden", active ? "false" : "true");
            });
          }

          function restrictedTabNames() {
            return ["approvals", "logs", "members"];
          }

          function syncRestrictedTabs() {
            memberTabs.forEach((button) => {
              const restricted = restrictedTabNames().includes(String(button.dataset.memberTab || "")) && (!member || member.role !== "admin");
              button.classList.toggle("is-restricted", restricted);
              button.title = restricted ? "Disponivel apenas para o Conselho Editorial." : "";
            });
          }

          function downloadEditorFile(filename, content, mime) {
            const blob = new Blob([content], { type: mime });
            const href = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = href;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(href), 150);
          }

          function bindFontSizeControl(editor, select) {
            if (!editor || !select) {
              return;
            }
            const sync = (range) => {
              const editorHasFocus = typeof editor.hasFocus === "function" ? editor.hasFocus() : false;
              if (range === null || !editorHasFocus) {
                select.value = "17px";
                return;
              }
              const activeRange = range || (typeof editor.getSelection === "function" ? editor.getSelection() : null);
              const format = typeof editor.getFormat === "function" ? editor.getFormat(activeRange || undefined) : {};
              const current = String(format.size || "").trim();
              if (current && Array.from(select.options).some((option) => option.value === current)) {
                select.value = current;
              } else {
                select.value = "17px";
              }
            };
            select.addEventListener("change", () => {
              const value = String(select.value || "").trim() || "17px";
              editor.format("size", value, "user");
            });
            editor.on("selection-change", (range) => sync(range));
            editor.on("text-change", () => sync());
            sync();
          }

          function activateRichEditor() {
            if (!editBodyEditor || !window.Quill) {
              return Promise.resolve();
            }
            if (window.barraventoEditor) {
              editorReady = Promise.resolve(window.barraventoEditor);
              return editorReady;
            }
            if (editorReady) {
              return editorReady;
            }
            if (editorToolbar) {
              editorToolbar.remove();
            }
            registerRichEditorFormats();
            const toolbarOptions = [
              [{ header: [1, 2, 3, false] }],
              [{ font: [] }],
              ["bold", "italic", "underline", "strike"],
              [{ script: "sub" }, { script: "super" }],
              [{ color: [] }, { background: [] }],
              [{ align: [] }],
              [{ list: "ordered" }, { list: "bullet" }, { indent: "-1" }, { indent: "+1" }],
              ["blockquote", "code-block"],
              ["link", "image", "video"],
              ["clean"]
            ];
            const quill = new window.Quill(editBodyEditor, {
              theme: "snow",
              placeholder: "Escreva o texto aqui com a mesma liberdade de um editor completo.",
              formats: ["header", "font", "size", "bold", "italic", "underline", "strike", "script", "color", "background", "align", "list", "indent", "blockquote", "code-block", "link", "image", "video"],
              modules: {
                toolbar: toolbarOptions,
                history: {
                  delay: 350,
                  maxStack: 200,
                  userOnly: true
                }
              }
            });
            window.barraventoEditor = quill;
            editorReady = Promise.resolve(quill);
            if (pendingEditorHtml) {
              applyHtmlToQuill(quill, pendingEditorHtml);
            }
            bindFontSizeControl(quill, document.getElementById("edit-font-size"));
            quill.on("text-change", () => {
              syncEditBodyFields();
              clearStatus(editStatus);
            });
            quill.root.addEventListener("blur", () => syncEditBodyFields());

            if (editorSpellcheckToggle) {
              editorSpellcheckToggle.addEventListener("change", () => {
                const editor = getEditorInstance();
                if (!editor || !editor.root) {
                  return;
                }
                editor.root.setAttribute("spellcheck", editorSpellcheckToggle.checked ? "true" : "false");
              });
            }
            quill.root.setAttribute("spellcheck", editorSpellcheckToggle && editorSpellcheckToggle.checked ? "true" : "false");

            if (editorPreviewButton) {
              editorPreviewButton.addEventListener("click", () => {
                const html = getEditorHtml();
                const preview = window.open("", "_blank", "noopener,noreferrer,width=1100,height=760");
                if (!preview) {
                  return;
                }
                preview.document.write("<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><title>Visualizacao do texto</title><style>body{font-family:Georgia,serif;max-width:900px;margin:40px auto;padding:0 20px;color:#2a201d;line-height:1.8}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d9d3cb;padding:8px}blockquote{border-left:3px solid #8d2f23;padding-left:16px;color:#5a4741}pre{background:#f7f1ea;padding:12px;border-radius:12px;overflow:auto}</style></head><body><h1>" + escapeHtml(editForm.title.value.trim() || "Visualizacao") + "</h1>" + html + "</body></html>");
                preview.document.close();
              });
            }

            if (editorExportHtmlButton) {
              editorExportHtmlButton.addEventListener("click", () => {
                downloadEditorFile((editForm.title.value.trim() || "texto") + ".html", getEditorHtml(), "text/html;charset=utf-8");
              });
            }

            if (editorExportTxtButton) {
              editorExportTxtButton.addEventListener("click", () => {
                downloadEditorFile((editForm.title.value.trim() || "texto") + ".txt", htmlToText(getEditorHtml()), "text/plain;charset=utf-8");
              });
            }

            syncEditBodyFields();
            return editorReady;
          }

          function activateCreateRichEditor() {
            if (!createBodyEditor || !window.Quill) {
              return Promise.resolve();
            }
            if (window.barraventoCreateEditor) {
              createEditorReady = Promise.resolve(window.barraventoCreateEditor);
              return createEditorReady;
            }
            if (createEditorReady) {
              return createEditorReady;
            }
            registerRichEditorFormats();
            const toolbarOptions = [
              [{ header: [1, 2, 3, false] }],
              [{ font: [] }],
              ["bold", "italic", "underline", "strike"],
              [{ script: "sub" }, { script: "super" }],
              [{ color: [] }, { background: [] }],
              [{ align: [] }],
              [{ list: "ordered" }, { list: "bullet" }, { indent: "-1" }, { indent: "+1" }],
              ["blockquote", "code-block"],
              ["link", "image", "video"],
              ["clean"]
            ];
            const quill = new window.Quill(createBodyEditor, {
              theme: "snow",
              placeholder: "Importe o DOCX e revise o texto aqui antes de publicar.",
              formats: ["header", "font", "size", "bold", "italic", "underline", "strike", "script", "color", "background", "align", "list", "indent", "blockquote", "code-block", "link", "image", "video"],
              modules: {
                toolbar: toolbarOptions,
                history: {
                  delay: 350,
                  maxStack: 200,
                  userOnly: true
                }
              }
            });
            window.barraventoCreateEditor = quill;
            createEditorReady = Promise.resolve(quill);
            if (pendingCreateEditorHtml) {
              applyHtmlToQuill(quill, pendingCreateEditorHtml);
            }
            bindFontSizeControl(quill, document.getElementById("create-font-size"));
            quill.on("text-change", () => {
              syncCreateBodyFields();
              clearStatus(createStatus);
            });
            quill.root.setAttribute("spellcheck", "true");
            syncCreateBodyFields();
            return createEditorReady;
          }

          function requireMember(statusNode) {
            if (member) {
              return true;
            }
            setStatus(statusNode, "error", "Entre como membro para liberar esta operacao.");
            return false;
          }

          function formatDateTime(value) {
            const stamp = String(value || "").trim();
            if (!stamp) {
              return "";
            }
            const parsed = new Date(stamp);
            if (Number.isNaN(parsed.getTime())) {
              return escapeHtml(stamp);
            }
            return escapeHtml(new Intl.DateTimeFormat("pt-BR", {
              dateStyle: "long",
              timeStyle: "short"
            }).format(parsed));
          }

          function formatMessage(value) {
            return escapeHtml(value).replace(/\n/g, "<br>");
          }

          function submissionKindLabel(kind) {
            if (kind === "edit") {
              return "Edicao pendente";
            }
            if (kind === "delete") {
              return "Exclusao pendente";
            }
            return "Inclusao pendente";
          }

          function submissionApprovalVariant(kind) {
            if (kind === "edit") {
              return "edit";
            }
            if (kind === "delete") {
              return "delete";
            }
            return "create";
          }

          function submissionApproveLabel(kind) {
            if (kind === "edit") {
              return "Aprovar edicao";
            }
            if (kind === "delete") {
              return "Aprovar exclusao";
            }
            return "Aprovar inclusao";
          }

          function submissionRejectLabel(kind) {
            if (kind === "edit") {
              return "Recusar edicao";
            }
            if (kind === "delete") {
              return "Recusar exclusao";
            }
            return "Recusar inclusao";
          }

          function renderNotice(item) {
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
          }

          function renderDashboard(payload) {
            const items = payload && Array.isArray(payload.items) ? payload.items : [];
            const totals = payload && payload.totals ? payload.totals : { views: 0, pdf_downloads: 0 };
            const series = payload && Array.isArray(payload.series) ? payload.series : [];
            const locations = payload && Array.isArray(payload.locations) ? payload.locations : [];
            const periodLabel = payload && payload.period ? String(payload.period.label || "") : "Periodo atual";
            const metric = dashboardMetric ? String(dashboardMetric.value || "views") : "views";
            const chartKind = dashboardChartKind ? String(dashboardChartKind.value || "line") : "line";
            if (!items.length) {
              dashboardList.innerHTML = '<div class="empty-state"><h3>Sem estatisticas ainda</h3><p>Os acessos e downloads vao aparecer aqui conforme o site for usado pelo servidor local.</p></div>';
              return;
            }
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
                items.map((item) => {
                  return (
                    '<div class="dashboard-row">' +
                      '<span><a href="' + escapeHtml(item.article_url) + '">' + escapeHtml(item.title) + '</a></span>' +
                      '<span>' + escapeHtml(String(item.views || 0)) + '</span>' +
                      '<span>' + escapeHtml(String(item.pdf_downloads || 0)) + '</span>' +
                      '<span>' + escapeHtml(item.published_label || "") + '</span>' +
                    '</div>'
                  );
                }).join('') +
              '</div>'
            );
          }

          function renderDashboardLineChart(items, series, locations, metric) {
            if (metric === "locations") {
              if (!locations.length) {
                return '<div class="empty-state empty-state--compact"><h3>Sem localidade suficiente</h3><p>Quando houver acessos com localidade resolvida, os locais mais recorrentes aparecerao aqui.</p></div>';
              }
              const width = 420;
              const height = 170;
              const padding = 20;
              const maxValue = Math.max(1, ...locations.map((item) => Number(item.value || 0)));
              const usableWidth = width - padding * 2;
              const usableHeight = height - padding * 2;
              const step = locations.length > 1 ? usableWidth / (locations.length - 1) : 0;
              const pathFor = locations.map((item, index) => {
                const x = padding + (step * index);
                const y = height - padding - ((Number(item.value || 0) / maxValue) * usableHeight);
                return (index === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2);
              }).join(' ');
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
            }
            if (!series.length) {
              return '<div class="empty-state empty-state--compact"><h3>Sem historico suficiente</h3><p>Os pontos diarios vao aparecer aqui conforme o site for usado.</p></div>';
            }
            const width = 420;
            const height = 170;
            const padding = 24;
            const key = metric === "pdf_downloads" ? "pdf_downloads" : "views";
            const values = series.map((item) => Number(item[key] || 0));
            const maxValue = Math.max(1, ...values);
            const usableWidth = width - padding * 2;
            const usableHeight = height - padding * 2;
            const step = series.length > 1 ? usableWidth / (series.length - 1) : 0;
            const pathFor = series.map((item, index) => {
              const x = padding + (step * index);
              const y = height - padding - ((Number(item[key] || 0) / maxValue) * usableHeight);
              return (index === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2);
            }).join(' ');
            const labels = [series[0], series[Math.floor((series.length - 1) / 2)], series[series.length - 1]]
              .filter(Boolean)
              .map((item) => '<span>' + escapeHtml(formatDateTime(String(item.label || '') + 'T12:00:00')) + '</span>')
              .filter((value, index, list) => list.indexOf(value) === index)
              .join('');
            const detailLegend = metric === "pdf_downloads"
              ? (() => {
                  const topItems = items
                    .map((item) => ({
                      label: String(item.title || "").trim(),
                      value: Number(item.pdf_downloads || 0)
                    }))
                    .filter((item) => item.value > 0)
                    .sort((left, right) => right.value - left.value)
                    .slice(0, 5);
                  if (!topItems.length) {
                    return '';
                  }
                  return '<ul class="dashboard-pie-chart__legend dashboard-pie-chart__legend--chart">' + topItems.map((item) => '<li><i class="dashboard-swatch dashboard-swatch--pdfs"></i><span>' + escapeHtml(item.label) + '</span><strong>' + escapeHtml(String(item.value)) + '</strong></li>').join('') + '</ul>';
                })()
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
          }

          function renderDashboardPieChart(items, locations, metric) {
            if (metric === "locations") {
              if (!locations.length) {
                return '<div class="empty-state empty-state--compact"><h3>Sem localidade suficiente</h3><p>Quando houver acessos com localidade resolvida, a distribuicao por cidade aparecera aqui.</p></div>';
              }
              const colors = ['#8d2f23', '#c96a2f', '#d8a24e', '#6d8a77', '#3c5f79'];
              const total = locations.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
              let angle = -Math.PI / 2;
              const radius = 82;
              const center = 100;
              const slices = locations.map((item, index) => {
                const portion = Number(item.value || 0) / total;
                const nextAngle = angle + (Math.PI * 2 * portion);
                const x1 = center + radius * Math.cos(angle);
                const y1 = center + radius * Math.sin(angle);
                const x2 = center + radius * Math.cos(nextAngle);
                const y2 = center + radius * Math.sin(nextAngle);
                const largeArc = portion > 0.5 ? 1 : 0;
                const path = 'M ' + center + ' ' + center + ' L ' + x1.toFixed(2) + ' ' + y1.toFixed(2) + ' A ' + radius + ' ' + radius + ' 0 ' + largeArc + ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + ' Z';
                angle = nextAngle;
                return { path, color: colors[index % colors.length], label: item.label, value: item.value };
              });
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
            }
            if (!items.length) {
              return '<div class="empty-state empty-state--compact"><h3>Sem distribuicao ainda</h3><p>Quando houver acessos no periodo, o grafico aparecera aqui.</p></div>';
            }
            const colors = ['#8d2f23', '#c96a2f', '#d8a24e', '#6d8a77', '#3c5f79'];
            const key = metric === "pdf_downloads" ? "pdf_downloads" : "views";
            const topItems = items
              .map((item) => ({
                label: item.title,
                value: Number(item[key] || 0)
              }))
              .filter((item) => item.value > 0)
              .sort((left, right) => right.value - left.value)
              .slice(0, 5);
            if (!topItems.length) {
              return '<div class="empty-state empty-state--compact"><h3>Sem distribuicao ainda</h3><p>Quando houver dados nesta modalidade, o grafico aparecera aqui.</p></div>';
            }
            const total = topItems.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
            let angle = -Math.PI / 2;
            const radius = 82;
            const center = 100;
            const slices = topItems.map((item, index) => {
              const portion = Number(item.value || 0) / total;
              const nextAngle = angle + (Math.PI * 2 * portion);
              const x1 = center + radius * Math.cos(angle);
              const y1 = center + radius * Math.sin(angle);
              const x2 = center + radius * Math.cos(nextAngle);
              const y2 = center + radius * Math.sin(nextAngle);
              const largeArc = portion > 0.5 ? 1 : 0;
              const path = 'M ' + center + ' ' + center + ' L ' + x1.toFixed(2) + ' ' + y1.toFixed(2) + ' A ' + radius + ' ' + radius + ' 0 ' + largeArc + ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + ' Z';
              angle = nextAngle;
              return {
                path,
                color: colors[index % colors.length],
                label: item.label,
                value: item.value
              };
            });
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
          }

          function scrollToMemberPanel() {
            if (window.location.hash !== "#member-panel") {
              history.replaceState(null, "", "#member-panel");
            }
            memberPanel.scrollIntoView({ behavior: "smooth", block: "start" });
          }

          function openInitialMemberView() {
            if (!member) {
              return;
            }
            setActiveTab("profile");
            loadProfileData().catch((error) => {
              setStatus(profileStatus, "error", escapeHtml(error.message));
            });
          }

          function renderRegistrationApproval(item) {
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
          }

          function renderSubmissionApproval(item) {
            const author = item.requested_by || {};
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
          }

          function applyMemberState(nextMember) {
            const wasAuthenticated = Boolean(member);
            member = nextMember;
            storePanelMemberState(member);
            const authenticated = Boolean(member);
            const shouldInitializePanel = authenticated && !wasAuthenticated;
            memberPanel.hidden = !authenticated;
            memberSession.hidden = !authenticated;
            memberLock.hidden = authenticated;
            if (memberAuthEntry) {
              memberAuthEntry.hidden = authenticated;
            }
            if (authenticated) {
              memberSummary.innerHTML = "Conectado como <strong>" + escapeHtml(member.email || member.name || "Membro") + "</strong><br>" + escapeHtml(member.role_label || "");
              if (whoFormShell) {
                whoFormShell.hidden = member.role !== "admin";
              }
              if (shouldInitializePanel) {
                openInitialMemberView();
              }
              clearStatus(memberStatus);
              if (shouldInitializePanel) {
                window.setTimeout(scrollToMemberPanel, 80);
              }
            } else {
              memberSummary.textContent = "Assim que o login for confirmado, o painel editorial sera aberto abaixo.";
              noticeList.innerHTML = "";
              dashboardList.innerHTML = "";
              logsList.innerHTML = "";
              registrationApprovals.innerHTML = "";
              submissionApprovals.innerHTML = "";
              memberDirectory = [];
              renderMemberSelectOptions();
              renderProfilePreview({});
              if (whoFormShell) {
                whoFormShell.hidden = true;
              }
              clearStatus(memberStatus);
            }
            syncRestrictedTabs();
            updateCreateSubmitState();
          }

          async function readJson(response) {
            return response.json().catch(() => ({}));
          }

          async function fetchSession() {
            const response = await fetch("/api/members/session", {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            const effectiveMember = payload.authenticated ? payload.member : null;
            applyMemberState(effectiveMember || null);
            if (effectiveMember) {
              const jobs = [loadNotices(), loadDashboard(), loadProfileData(), refreshArticles()];
              if (effectiveMember && effectiveMember.role === "admin") {
                jobs.push(loadApprovals());
                jobs.push(loadLogs());
              }
              await Promise.allSettled(jobs);
            } else if (window.location.protocol !== "file:") {
              window.location.replace(loginPageHref);
            }
            return payload;
          }

          async function submitJson(endpoint, payload) {
            const response = await fetch(endpoint, {
              method: "POST",
              credentials: "same-origin",
              headers: {
                "Content-Type": "application/json"
              },
              body: JSON.stringify(payload)
            });
            const body = await readJson(response);
            if (!response.ok || !body.ok) {
              throw new Error(body.error || "Nao foi possivel concluir a operacao.");
            }
            return body;
          }

          function fillEditForm(slug) {
            const article = articleMap.get(slug);
            if (!article) {
              editForm.reset();
              if (editDocxImportInput) {
                editDocxImportInput.value = "";
              }
              setEditorHtml("");
              setCheckedValues(editForm, []);
              editSnapshot = null;
              return;
            }
            const titleField = formField(editForm, "title");
            const authorField = formField(editForm, "author");
            const authorMembersField = formField(editForm, "author_members");
            const summaryField = formField(editForm, "summary");
            const tagsField = formField(editForm, "tags");
            const hashtagsField = formField(editForm, "hashtags");
            if (editDocxImportInput) {
              editDocxImportInput.value = "";
            }
            if (editDocxInput) {
              editDocxInput.value = "";
            }
            if (titleField) titleField.value = article.title || "";
            if (authorField) authorField.value = article.author || "";
            setMultiSelectValues(authorMembersField, (article.author_members || []).map((item) => item.email || ""));
            if (summaryField) summaryField.value = article.summary || "";
            setEditorHtml(article.body_html || renderLegacyMarkup(article.body_editor || ""));
            if (tagsField) tagsField.value = csv(article.tags || []);
            if (hashtagsField) hashtagsField.value = csv(article.hashtags || []);
            setCheckedValues(editForm, article.categories || []);
            editSnapshot = currentEditState();
          }

          function validateCategories(form, statusNode) {
            if (getCheckedValues(form).length > 0) {
              return true;
            }
            setStatus(statusNode, "error", "Selecione pelo menos uma categoria.");
            return false;
          }

          function validateRequiredTitle(form, statusNode) {
            const titleField = formField(form, "title");
            const title = String(titleField ? titleField.value : "").trim();
            if (title) {
              if (titleField) {
                titleField.value = title;
              }
              return true;
            }
            setStatus(statusNode, "error", "Informe o titulo do texto.");
            if (titleField) {
              titleField.focus();
            }
            return false;
          }

          function validateEditBody() {
            const blocks = syncEditBodyFields();
            if (blocks.length > 0) {
              return true;
            }
            setStatus(editStatus, "error", "Escreva o corpo do texto antes de salvar a edicao.");
            return false;
          }

          function validateCreateBody() {
            const blocks = syncCreateBodyFields();
            if (blocks.length > 0) {
              return true;
            }
            setStatus(createStatus, "error", "Importe o DOCX e revise o corpo do texto antes de publicar.");
            return false;
          }

          function populateSelect() {
            const options = ['<option value="">Escolha um texto</option>'].concat(
              articles.map((article) => '<option value="' + escapeHtml(article.slug) + '">' + escapeHtml(article.title) + '</option>')
            );
            editSelect.innerHTML = options.join("");
          }

          function setArticles(nextArticles) {
            articles = Array.isArray(nextArticles) ? repairValue(nextArticles) : [];
            articleMap = new Map(articles.map((item) => [item.slug, item]));
            const previousValue = editSelect ? String(editSelect.value || "") : "";
            populateSelect();
            if (editSelect && previousValue && articleMap.has(previousValue)) {
              editSelect.value = previousValue;
              fillEditForm(previousValue);
            } else if (editSelect) {
              editSelect.value = "";
              fillEditForm("");
            }
          }

          async function refreshArticles() {
            if (!member) {
              return;
            }
            const response = await fetch("/api/members/articles", {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401) {
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel atualizar a lista de textos.");
            }
            setArticles(payload.items || []);
          }

          async function loadProfileData() {
            if (!member || !profileForm) {
              return;
            }
            const response = await fetch("/api/members/profile", {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401) {
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel carregar o perfil.");
            }
            memberDirectory = Array.isArray(payload.directory) ? payload.directory : [];
            renderMemberSelectOptions();
            if (payload.member) {
              const memberPayload = payload.member;
              const nameField = formField(profileForm, "name");
              const roleField = formField(profileForm, "editorial_role");
              const educationField = formField(profileForm, "education");
              if (nameField) nameField.value = memberPayload.name || "";
              if (roleField) roleField.value = memberPayload.editorial_role || "Opcao A";
              if (educationField) educationField.value = memberPayload.education || "";
              renderProfilePreview(memberPayload);
            }
            if (whoFormShell) {
              whoFormShell.hidden = !(member && member.role === "admin");
            }
            if (whoForm && payload.who) {
              const titleField = formField(whoForm, "title");
              const summaryField = formField(whoForm, "summary");
              const bodyField = formField(whoForm, "body");
              if (titleField) titleField.value = payload.who.title || "";
              if (summaryField) summaryField.value = payload.who.summary || "";
              if (bodyField) bodyField.value = payload.who.body || "";
            }
          }

          async function loadNotices() {
            if (!member) {
              noticeList.innerHTML = "";
              return;
            }
            const response = await fetch("/api/members/notices", {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401) {
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel carregar os recados.");
            }
            noticeList.innerHTML = (payload.items || []).length
              ? payload.items.map(renderNotice).join('')
              : '<div class="empty-state"><h3>Sem recados ainda</h3><p>Os avisos para os membros vao aparecer aqui.</p></div>';
          }

          async function loadDashboard() {
            if (!member) {
              dashboardList.innerHTML = "";
              return;
            }
            const period = dashboardPeriod ? encodeURIComponent(dashboardPeriod.value || "30") : "30";
            const response = await fetch("/api/members/dashboard?period=" + period, {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401) {
              await fetchSession();
              throw new Error(payload.error || "Sessao encerrada.");
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel carregar o dashboard.");
            }
            dashboardPayload = payload;
            renderDashboard(payload);
          }

          async function loadApprovals() {
            if (!member || member.role !== "admin") {
              registrationApprovals.innerHTML = "";
              submissionApprovals.innerHTML = "";
              return;
            }
            const response = await fetch("/api/members/approvals", {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401 || response.status === 403) {
              await fetchSession();
              throw new Error(payload.error || "Acesso restrito as aprovacoes.");
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel carregar as aprovacoes.");
            }
            registrationApprovals.innerHTML = (payload.registrations || []).length
              ? payload.registrations.map(renderRegistrationApproval).join('')
              : '<div class="empty-state"><h3>Sem cadastros pendentes</h3><p>Quando surgir um novo cadastro aguardando liberacao, ele aparecera aqui.</p></div>';
            submissionApprovals.innerHTML = (payload.submissions || []).length
              ? payload.submissions.map(renderSubmissionApproval).join('')
              : '<div class="empty-state"><h3>Sem publicacoes pendentes</h3><p>Quando um revisor enviar um texto, ele aparecera aqui para aprovacao.</p></div>';
          }

          function renderLogItem(item) {
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
          }

          async function loadLogs() {
            if (!member || member.role !== "admin") {
              logsList.innerHTML = "";
              return;
            }
            const response = await fetch("/api/members/logs?limit=200", {
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401 || response.status === 403) {
              await fetchSession();
              throw new Error(payload.error || "Acesso restrito aos logs.");
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel carregar os logs.");
            }
            logsList.innerHTML = (payload.items || []).length
              ? payload.items.map(renderLogItem).join('')
              : '<div class="empty-state"><h3>Sem logs ainda</h3><p>Os acessos e as acoes dos membros vao aparecer aqui.</p></div>';
          }

          async function submitForm(form, endpoint, statusNode) {
            const data = new FormData(form);
            const response = await fetch(endpoint, {
              method: "POST",
              body: data,
              credentials: "same-origin"
            });
            const payload = await readJson(response);
            if (response.status === 401) {
              await fetchSession();
            }
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || "Nao foi possivel concluir a operacao.");
            }
            if (payload.pending) {
              setStatus(
                statusNode,
                "success",
                escapeHtml(payload.message || "Solicitacao enviada para aprovacao.") + "<br><strong>" + escapeHtml(payload.title || "Texto pendente") + "</strong>"
              );
              form.reset();
              syncCategoryCombobox(form);
              setMultiSelectValues(formField(form, "author_members"), []);
              if (form === createForm) {
                if (createDocxImportInput) {
                  createDocxImportInput.value = "";
                }
                setCreateEditorHtml("");
                updateCreateSubmitState();
              }
              if (form === editForm) {
                if (editDocxImportInput) {
                  editDocxImportInput.value = "";
                }
                setEditorHtml("");
                setCheckedValues(editForm, []);
                editSnapshot = null;
                editSelect.value = "";
              }
              if (member && member.role === "admin") {
                loadApprovals().catch(() => {
                  setStatus(approvalsStatus, "error", "Nao foi possivel atualizar a fila de aprovacoes.");
                });
              }
              refreshArticles().catch(() => {
                setStatus(editStatus, "error", "Nao foi possivel atualizar a lista de textos.");
              });
              return;
            }
            setStatus(
              statusNode,
              "success",
              "Concluido com sucesso.<br><strong>" + escapeHtml(payload.title || "Texto atualizado") + "</strong><br><a href=\"" + escapeHtml(payload.article_url || "/") + "\">Abrir pagina</a>"
            );
            refreshArticles().catch(() => {
              setStatus(editStatus, "error", "Nao foi possivel atualizar a lista de textos.");
            });
            window.setTimeout(() => window.location.reload(), 1200);
          }

          if (window.location.protocol === "file:") {
            setStatus(loginStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O login nao funciona em <code>file://</code>.");
            setStatus(registerStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O cadastro nao funciona em <code>file://</code>.");
            setStatus(createStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O envio nao funciona em <code>file://</code>.");
            setStatus(editStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. A edicao nao funciona em <code>file://</code>.");
            setStatus(profileStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O perfil nao funciona em <code>file://</code>.");
            setStatus(whoStatus, "error", "Abra esta pagina com <code>abrir-site-completo.bat</code>. O Quem Somos nao funciona em <code>file://</code>.");
          }

          activateCategoryComboboxes();
          activateMemberComboboxes();
          if (createDocxInput) {
            createDocxInput.addEventListener("change", () => {
              if (createDocxImportInput) {
                createDocxImportInput.value = "";
              }
              updateCreateSubmitState();
            });
          }
          if (editDocxInput) {
            editDocxInput.addEventListener("change", () => {
              if (editDocxImportInput) {
                editDocxImportInput.value = "";
              }
            });
          }
          activateRichEditor();
          activateCreateRichEditor();
          populateSelect();
          renderMemberSelectOptions();
          setEditorHtml("");
          setCreateEditorHtml("");
          if (createForm) {
            createForm.addEventListener("input", updateCreateSubmitState);
            createForm.addEventListener("change", updateCreateSubmitState);
          }
          [createForm, editForm].forEach((form) => {
            const select = formField(form, "author_members");
            if (select) {
              select.addEventListener("change", () => syncAuthorFieldWithMembers(form));
            }
          });
          updateCreateSubmitState();
          syncRestrictedTabs();
          fetchSession().catch(() => {
            applyMemberState(null);
            setStatus(loginStatus, "error", "Nao foi possivel verificar a sessao de membro.");
          });

          memberTabs.forEach((button) => {
            button.addEventListener("click", async () => {
              if (!member) {
                return;
              }
              const target = button.dataset.memberTab;
              if (restrictedTabNames().includes(String(target || "")) && member.role !== "admin") {
                setStatus(memberStatus, "error", "Esta aba e restrita ao Conselho Editorial.");
                return;
              }
              setActiveTab(target);
              if (target === "notices") {
                try {
                  await loadNotices();
                } catch (error) {
                  setStatus(noticeStatus, "error", escapeHtml(error.message));
                }
              }
              if (target === "dashboard") {
                try {
                  await loadDashboard();
                } catch (error) {
                  setStatus(dashboardStatus, "error", escapeHtml(error.message));
                }
              }
              if (target === "edit") {
                try {
                  await refreshArticles();
                } catch (error) {
                  setStatus(editStatus, "error", escapeHtml(error.message));
                }
              }
              if (target === "profile") {
                try {
                  await loadProfileData();
                } catch (error) {
                  setStatus(profileStatus, "error", escapeHtml(error.message));
                }
              }
              if (target === "approvals") {
                try {
                  await loadApprovals();
                } catch (error) {
                  setStatus(approvalsStatus, "error", escapeHtml(error.message));
                }
              }
              if (target === "logs") {
                try {
                  await loadLogs();
                } catch (error) {
                  setStatus(logsStatus, "error", escapeHtml(error.message));
                }
              }
            });
          });

          if (openProfileTabButton) {
            openProfileTabButton.addEventListener("click", async () => {
              if (!member) {
                return;
              }
              setActiveTab("profile");
              try {
                await loadProfileData();
              } catch (error) {
                setStatus(profileStatus, "error", escapeHtml(error.message));
              }
            });
          }

          loginForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (window.location.protocol === "file:") {
              return;
            }
            setStatus(loginStatus, "pending", "Entrando...");
            try {
              const payload = await submitJson("/api/members/login", {
                email: formField(loginForm, "email").value.trim(),
                password: formField(loginForm, "password").value
              });
              storePanelMemberState(payload.member || null);
              loginForm.reset();
              setStatus(loginStatus, "success", "Acesso liberado para <strong>" + escapeHtml(payload.member.name || payload.member.email) + "</strong>.");
              window.location.assign(panelPageHref);
            } catch (error) {
              setStatus(loginStatus, "error", escapeHtml(error.message));
            }
          });

          registerForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (window.location.protocol === "file:") {
              return;
            }
            if (formField(registerForm, "password").value !== formField(registerForm, "password_confirm").value) {
              setStatus(registerStatus, "error", "A confirmacao da senha precisa ser igual a senha informada.");
              return;
            }
            setStatus(registerStatus, "pending", "Cadastrando membro...");
            try {
              const payload = await submitJson("/api/members/register", {
                name: formField(registerForm, "name").value.trim(),
                email: formField(registerForm, "email").value.trim(),
                role: formField(registerForm, "role").value,
                password: formField(registerForm, "password").value
              });
              registerForm.reset();
              setStatus(registerStatus, "success", "Cadastro enviado para aprovacao do Conselho Editorial.<br><strong>" + escapeHtml(payload.member.name || payload.member.email) + "</strong>");
            } catch (error) {
              setStatus(registerStatus, "error", escapeHtml(error.message));
            }
          });

          if (profileForm) {
            profileForm.addEventListener("submit", async (event) => {
              event.preventDefault();
              if (window.location.protocol === "file:" || !requireMember(profileStatus)) {
                return;
              }
              setStatus(profileStatus, "pending", "Salvando perfil...");
              try {
                const response = await fetch("/api/members/profile", {
                  method: "POST",
                  body: new FormData(profileForm),
                  credentials: "same-origin"
                });
                const payload = await readJson(response);
                if (!response.ok || !payload.ok) {
                  throw new Error(payload.error || "Nao foi possivel salvar o perfil.");
                }
                applyMemberState(payload.member || member);
                memberDirectory = Array.isArray(payload.directory) ? payload.directory : memberDirectory;
                renderMemberSelectOptions();
                renderProfilePreview(payload.member || {});
                setStatus(profileStatus, "success", "Perfil atualizado com sucesso.");
              } catch (error) {
                setStatus(profileStatus, "error", escapeHtml(error.message));
              }
            });
          }

          if (whoForm) {
            whoForm.addEventListener("submit", async (event) => {
              event.preventDefault();
              if (window.location.protocol === "file:" || !requireMember(whoStatus)) {
                return;
              }
              setStatus(whoStatus, "pending", "Salvando Quem Somos...");
              try {
                await submitJson("/api/members/who", {
                  title: formField(whoForm, "title").value.trim(),
                  summary: formField(whoForm, "summary").value.trim(),
                  body: formField(whoForm, "body").value.trim()
                });
                setStatus(whoStatus, "success", "Pagina Quem Somos atualizada.");
              } catch (error) {
                setStatus(whoStatus, "error", escapeHtml(error.message));
              }
            });
          }

          noticeForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (window.location.protocol === "file:" || !requireMember(noticeStatus)) {
              return;
            }
            setStatus(noticeStatus, "pending", "Publicando recado...");
            try {
              await submitJson("/api/members/notices", {
                message: formField(noticeForm, "message").value
              });
              noticeForm.reset();
              setStatus(noticeStatus, "success", "Recado publicado com sucesso.");
              await loadNotices();
              setActiveTab("notices");
            } catch (error) {
              setStatus(noticeStatus, "error", escapeHtml(error.message));
            }
          });

          editSelect.addEventListener("change", () => {
            fillEditForm(editSelect.value);
            clearStatus(editStatus);
          });

          dashboardRefresh.addEventListener("click", async () => {
            if (!requireMember(dashboardStatus)) {
              return;
            }
            setStatus(dashboardStatus, "pending", "Atualizando dashboard...");
            try {
              await loadDashboard();
              setStatus(dashboardStatus, "success", "Dashboard atualizado.");
            } catch (error) {
              setStatus(dashboardStatus, "error", escapeHtml(error.message));
            }
          });

          if (dashboardPeriod) {
            dashboardPeriod.addEventListener("change", async () => {
              if (!requireMember(dashboardStatus)) {
                return;
              }
              setStatus(dashboardStatus, "pending", "Atualizando filtro do dashboard...");
              try {
                await loadDashboard();
                setStatus(dashboardStatus, "success", "Dashboard filtrado.");
              } catch (error) {
                setStatus(dashboardStatus, "error", escapeHtml(error.message));
              }
            });
          }

          [dashboardChartKind, dashboardMetric].forEach((control) => {
            if (!control) {
              return;
            }
            control.addEventListener("change", () => {
              if (dashboardPayload) {
                renderDashboard(dashboardPayload);
              }
            });
          });

          approvalsRefresh.addEventListener("click", async () => {
            if (!requireMember(approvalsStatus)) {
              return;
            }
            setStatus(approvalsStatus, "pending", "Atualizando aprovacoes...");
            try {
              await loadApprovals();
              setStatus(approvalsStatus, "success", "Fila de aprovacoes atualizada.");
            } catch (error) {
              setStatus(approvalsStatus, "error", escapeHtml(error.message));
            }
          });

          if (logsRefresh) {
            logsRefresh.addEventListener("click", async () => {
              if (!requireMember(logsStatus)) {
                return;
              }
              setStatus(logsStatus, "pending", "Atualizando logs...");
              try {
                await loadLogs();
                setStatus(logsStatus, "success", "Logs atualizados.");
              } catch (error) {
                setStatus(logsStatus, "error", escapeHtml(error.message));
              }
            });
          }

          createForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const createRequirements = describeCreateRequirements();
            if (!createRequirements.valid) {
              setStatus(createStatus, "error", escapeHtml(createRequirements.message));
              updateCreateSubmitState();
              return;
            }
            if (window.location.protocol === "file:" || !requireMember(createStatus) || !validateRequiredTitle(createForm, createStatus) || !validateCategories(createForm, createStatus) || !validateCreateBody()) {
              return;
            }
            setStatus(createStatus, "pending", "Publicando texto...");
            try {
              await submitForm(createForm, "/api/upload", createStatus);
            } catch (error) {
              setStatus(createStatus, "error", escapeHtml(error.message));
            }
          });

          async function importDocxIntoEditor({ form, fileInput, importInput, statusNode, setEditor, successMessage, titleFallback = false, readyEditor = null }) {
            if (window.location.protocol === "file:" || !requireMember(statusNode)) {
              return;
            }
            const file = fileInput && fileInput.files ? fileInput.files[0] : null;
            if (!file) {
              setStatus(statusNode, "error", "Escolha um arquivo DOCX para importar.");
              return;
            }
            setStatus(statusNode, "pending", "Salvando e importando o DOCX para a caixa de edicao...");
            try {
              const data = new FormData();
              data.append("docx", file);
              const response = await fetch("/api/docx-import", {
                method: "POST",
                body: data,
                credentials: "same-origin"
              });
              const payload = await readJson(response);
              if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Nao foi possivel importar o DOCX.");
              }
              if (importInput) {
                importInput.value = payload.import_id || "";
              }
              const titleField = formField(form, "title");
              const authorField = formField(form, "author");
              if (titleField && (!titleField.value.trim() || titleFallback)) {
                titleField.value = payload.title || "";
              }
              if (authorField && (!authorField.value.trim() || titleFallback) && payload.author) {
                authorField.value = payload.author;
              }
              if (typeof readyEditor === "function") {
                await readyEditor();
              }
              setEditor(payload.body_html || "");
              if (form === createForm) {
                syncCreateBodyFields();
              } else {
                syncEditBodyFields();
              }
              setStatus(statusNode, "success", successMessage || "DOCX salvo e importado para a caixa de edicao.");
            } catch (error) {
              setStatus(statusNode, "error", escapeHtml(error.message));
            }
          }

          createImportDocxButton.addEventListener("click", async () => {
            await importDocxIntoEditor({
              form: createForm,
              fileInput: createDocxInput,
              importInput: createDocxImportInput,
              statusNode: createStatus,
              setEditor: setCreateEditorHtml,
              readyEditor: activateCreateRichEditor,
              successMessage: "DOCX salvo no site e importado para a caixa de edicao. Revise e publique o texto final."
            });
          });

          editForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (window.location.protocol === "file:") {
              return;
            }
            if (!requireMember(editStatus)) {
              return;
            }
            if (!editSelect.value) {
              setStatus(editStatus, "error", "Escolha um texto para editar.");
              return;
            }
            if (!validateRequiredTitle(editForm, editStatus)) {
              return;
            }
            if (!validateCategories(editForm, editStatus)) {
              return;
            }
            if (!validateEditBody()) {
              return;
            }
            const currentState = currentEditState();
            const docxChanged = Boolean((editDocxInput && editDocxInput.files && editDocxInput.files[0]) || (editDocxImportInput && editDocxImportInput.value));
            const imageChanged = Boolean(editForm.image.files[0]);
            if (!docxChanged && !imageChanged && sameState(currentState, editSnapshot)) {
              setStatus(editStatus, "error", "Nenhuma alteracao foi feita. A edicao nao sera executada.");
              return;
            }
            setStatus(editStatus, "pending", "Salvando edicao...");
            try {
              await submitForm(editForm, "/api/edit", editStatus);
            } catch (error) {
              setStatus(editStatus, "error", escapeHtml(error.message));
            }
          });

          editImportDocxButton.addEventListener("click", async () => {
            await importDocxIntoEditor({
              form: editForm,
              fileInput: editDocxInput,
              importInput: editDocxImportInput,
              statusNode: editStatus,
              setEditor: setEditorHtml,
              readyEditor: activateRichEditor,
              titleFallback: true,
              successMessage: "Novo DOCX salvo no site e carregado na caixa de edicao. Salve a edicao para enviar para aprovacao."
            });
          });

          deleteArticleButton.addEventListener("click", async () => {
            if (window.location.protocol === "file:") {
              return;
            }
            if (!requireMember(editStatus)) {
              return;
            }
            if (!editSelect.value) {
              setStatus(editStatus, "error", "Escolha um texto para excluir.");
              return;
            }
            if (!window.confirm("Deseja enviar a exclusao deste texto para aprovacao?")) {
              return;
            }
            setStatus(editStatus, "pending", "Enviando exclusao...");
            try {
              await submitJson("/api/delete", {
                slug: editSelect.value
              });
              editForm.reset();
              setEditorHtml("");
              setCheckedValues(editForm, []);
              setMultiSelectValues(formField(editForm, "author_members"), []);
              editSnapshot = null;
              editSelect.value = "";
              setStatus(editStatus, "success", "Exclusao enviada para aprovacao.");
              await refreshArticles();
              if (member && member.role === "admin") {
                await loadApprovals();
              }
            } catch (error) {
              setStatus(editStatus, "error", escapeHtml(error.message));
            }
          });

          logoutButton.addEventListener("click", async () => {
            if (window.location.protocol === "file:") {
              return;
            }
            setStatus(memberStatus, "pending", "Encerrando sessao...");
            try {
              await submitJson("/api/members/logout", {});
              applyMemberState(null);
              noticeForm.reset();
              editForm.reset();
              createForm.reset();
              if (profileForm) {
                profileForm.reset();
              }
              if (whoForm) {
                whoForm.reset();
              }
              setEditorHtml("");
              setCheckedValues(editForm, []);
              setCheckedValues(createForm, []);
              setMultiSelectValues(formField(editForm, "author_members"), []);
              setMultiSelectValues(formField(createForm, "author_members"), []);
              renderProfilePreview({});
              editSnapshot = null;
              editSelect.value = "";
              clearStatus(createStatus);
              clearStatus(editStatus);
              clearStatus(profileStatus);
              clearStatus(whoStatus);
              clearStatus(noticeStatus);
              clearStatus(dashboardStatus);
              window.location.assign(loginPageHref);
            } catch (error) {
              setStatus(memberStatus, "error", escapeHtml(error.message));
            }
          });

          document.addEventListener("click", async (event) => {
            const registrationButton = event.target.closest("[data-approve-registration]");
            if (registrationButton) {
              if (!requireMember(approvalsStatus)) {
                return;
              }
              setStatus(approvalsStatus, "pending", "Aprovando cadastro...");
              try {
                await submitJson("/api/members/approvals/registrations/approve", {
                  email: registrationButton.dataset.approveRegistration
                });
                await loadApprovals();
                setStatus(approvalsStatus, "success", "Cadastro aprovado com sucesso.");
              } catch (error) {
                setStatus(approvalsStatus, "error", escapeHtml(error.message));
              }
              return;
            }

            const submissionButton = event.target.closest("[data-approve-submission]");
            if (submissionButton) {
              if (!requireMember(approvalsStatus)) {
                return;
              }
              setStatus(approvalsStatus, "pending", "Aprovando publicacao...");
              try {
                await submitJson("/api/members/approvals/submissions/approve", {
                  id: submissionButton.dataset.approveSubmission
                });
                await loadApprovals();
                await loadDashboard();
                window.setTimeout(() => window.location.reload(), 600);
                setStatus(approvalsStatus, "success", "Publicacao aprovada com sucesso.");
              } catch (error) {
                setStatus(approvalsStatus, "error", escapeHtml(error.message));
              }
              return;
            }

            const rejectionButton = event.target.closest("[data-reject-submission]");
            if (rejectionButton) {
              if (!requireMember(approvalsStatus)) {
                return;
              }
              const approvalCard = rejectionButton.closest(".approval-card");
              const reasonField = approvalCard ? approvalCard.querySelector("[data-rejection-reason]") : null;
              const reason = reasonField ? String(reasonField.value || "").trim() : "";
              if (reason.length < 3) {
                setStatus(approvalsStatus, "error", "Informe um motivo curto para a recusa.");
                if (reasonField) {
                  reasonField.focus();
                }
                return;
              }
              setStatus(approvalsStatus, "pending", "Recusando publicacao...");
              try {
                await submitJson("/api/members/approvals/submissions/reject", {
                  id: rejectionButton.dataset.rejectSubmission,
                  reason
                });
                await loadApprovals();
                setStatus(approvalsStatus, "success", "Publicacao recusada com sucesso.");
              } catch (error) {
                setStatus(approvalsStatus, "error", escapeHtml(error.message));
              }
            }
          });
        })();
      