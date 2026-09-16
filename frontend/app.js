const STAGES = ["SERP", "Brief", "Draft", "SEO"];
const STAGES_WITH_SCRAPE = ["SERP", "Brief", "Scrape", "Draft", "SEO"];
const STAGES_REWRITE = ["Parse", "Rewrite", "SEO"];

const API_BASE = "";
const PAGE = document.body?.dataset?.page || "writer";

let _genTimer = null;

function authHeaders() {
  return window.BlogAgentAuth?.headers() || { "Content-Type": "application/json" };
}

function getStages() {
  if (PAGE === "rewriter") return STAGES_REWRITE;
  const website = document.getElementById("website")?.value?.trim() || "";
  return website ? STAGES_WITH_SCRAPE : STAGES;
}

function renderTracker(activeIndex, elapsed) {
  const tracker = document.getElementById("tracker");
  if (!tracker) return;
  const stages = getStages();
  tracker.innerHTML = "";
  if (activeIndex >= 0 && activeIndex < stages.length && elapsed !== undefined) {
    const pct = Math.min(Math.round((elapsed / 180) * 100), 99);
    tracker.innerHTML = `
      <div class="tracker-step active">
        <span class="tracker-dot"></span>
        <span class="tracker-label">${stages[activeIndex]}</span>
      </div>
      <span class="tracker-meta">${pct}% · ${elapsed}s</span>
    `;
  } else if (activeIndex >= stages.length) {
    tracker.innerHTML = `
      <div class="tracker-step done">
        <span class="tracker-dot"></span>
        <span class="tracker-label">Complete</span>
      </div>
    `;
  }
}

function startTimer() {
  let elapsed = 0;
  let stageIdx = 0;
  const stages = getStages();
  const stageAt = [0, 5, 10, 20, 35, 50].slice(0, stages.length);
  renderTracker(0, elapsed);
  _genTimer = setInterval(() => {
    elapsed++;
    for (let i = stageAt.length - 1; i >= 0; i--) {
      if (elapsed >= stageAt[i]) { stageIdx = i; break; }
    }
    renderTracker(stageIdx, elapsed);
  }, 1000);
}

function stopTimer() {
  if (_genTimer) { clearInterval(_genTimer); _genTimer = null; }
}

renderTracker(-1);

function wordCountOf(str) {
  return str ? str.split(/\s+/).filter(Boolean).length : 0;
}

function updateWordCountLabel(inputId, labelId, limit) {
  const el = document.getElementById(inputId);
  if (!el) return;
  const fn = () => {
    const label = document.getElementById(labelId);
    if (!label) return;
    const n = wordCountOf(el.value.trim());
    label.textContent = `${n}/${limit} words`;
    label.classList.toggle("over", n > limit);
  };
  el.addEventListener("input", fn);
  fn();
}

updateWordCountLabel("instructions", "instructions-count", 150);
updateWordCountLabel("hook-brief", "hook-brief-count", 30);
updateWordCountLabel("bv-style", "bv-style-count", 60);
updateWordCountLabel("audience", "audience-count", 40);

document.getElementById("keyword")?.addEventListener("input", function() {
  const count = document.getElementById("keyword-count");
  if (!count) return;
  const len = this.value.length;
  count.textContent = len;
  count.classList.toggle("over", len > 200);
});

// Toggle chips
document.querySelectorAll(".toggle-chip").forEach(chip => {
  const checkbox = chip.querySelector("input[type=checkbox]");
  if (checkbox.checked) chip.classList.add("active");
  chip.addEventListener("click", (e) => {
    e.preventDefault();
    checkbox.checked = !checkbox.checked;
    chip.classList.toggle("active", checkbox.checked);
  });
});

// Brand voice editor
document.getElementById("brand-voice-select")?.addEventListener("change", function() {
  const editor = document.getElementById("brand-voice-editor");
  if (!editor) return;
  if (this.value === "__create__") {
    editor.classList.remove("hidden");
  } else {
    editor.classList.add("hidden");
  }
});

function buildBrandVoice() {
  const select = document.getElementById("brand-voice-select")?.value;
  if (select !== "__create__") return null;
  if (select !== "__create__") return null;

  const parts = [];
  const tone = document.getElementById("bv-tone").value.trim();
  const vocab = document.getElementById("bv-vocabulary").value;
  const style = document.getElementById("bv-style").value.trim();
  const donts = document.getElementById("bv-donts").value.trim();

  if (tone) parts.push("Tone: " + tone);
  if (vocab) parts.push("Vocabulary: " + vocab);
  if (style) parts.push("Style: " + style);
  if (donts) parts.push("Avoid: " + donts);

  return parts.length > 0 ? parts.join(". ") + "." : null;
}

function countArticleWords(md) {
  const visible = (md || "").replace(/<[^>]+>/g, " ");
  return visible.split(/\s+/).filter(Boolean).length;
}

function countArticleH1(md) {
  const source = md || "";
  const markdown = (source.match(/^#\s+.+$/gm) || []).length;
  const html = (source.match(/<h1\b[^>]*>/gi) || []).length;
  return markdown + html;
}

function countKeywordHits(md, keyword) {
  if (!md || !keyword) return 0;
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matches = md.match(new RegExp(escaped, "gi"));
  return matches ? matches.length : 0;
}

function articleStats(result) {
  const article = result.article || "";
  const backend = result.stats || {};
  const keyword = (
    result.brief?.primary_keyword
    || result.serp?.keyword
    || ""
  ).trim();
  return {
    word_count: backend.word_count ?? countArticleWords(article),
    h1_count: backend.h1_count ?? countArticleH1(article),
    keyword_count: backend.keyword_count ?? countKeywordHits(article, keyword),
  };
}

function stripEmphasisMarkup(text) {
  return String(text || "")
    .replace(/<\/?(strong|b|em|i|u|mark)\b[^>]*>/gi, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/~~([^~]+)~~/g, "$1")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, "$1$2")
    .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?:;]|$)/g, "$1$2")
    .replace(/`([^`]+)`/g, "$1");
}

function inlinePublish(text) {
  return stripEmphasisMarkup(text)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>');
}

function isHtmlArticle(src) {
  return /<(h[1-3]|p|ul|ol|table)\b/i.test(src || "");
}

function splitInlineList(text) {
  const numbered = text.split(/(?=\s\d+[.)]\s+)/);
  if (numbered.length > 1 && /^\d+[.)]\s+/.test(text.trim())) {
    return numbered.map((part) => part.trim()).filter(Boolean);
  }
  return [text];
}

function markdownToHtml(md) {
  const source = (md || "").trim();
  if (!source) return "";
  if (isHtmlArticle(source)) {
    return stripEmphasisMarkup(source);
  }

  const lines = source.split("\n");
  let html = "";
  let inParagraph = false;
  let inTable = false;
  let listType = null;

  function closeParagraph() {
    if (inParagraph) {
      html += "</p>";
      inParagraph = false;
    }
  }
  function closeTable() {
    if (inTable) {
      html += "</tbody></table>";
      inTable = false;
    }
  }
  function closeList() {
    if (listType) {
      html += "</" + listType + ">";
      listType = null;
    }
  }
  function openList(type) {
    if (listType === type) return;
    closeParagraph();
    closeTable();
    closeList();
    html += "<" + type + ">";
    listType = type;
  }
  function parseRow(line) {
    return line.split("|").slice(1, -1).map((c) => c.trim());
  }
  function isSeparator(line) {
    return /^\|(?:[\s:-]+\|)+$/.test(line.trim());
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      closeParagraph();
      closeTable();
      closeList();
      continue;
    }

    if (/^#{1,3}\s+/.test(trimmed)) {
      closeParagraph();
      closeTable();
      closeList();
      if (trimmed.startsWith("### ")) {
        html += "<h3>" + inlinePublish(trimmed.slice(4)) + "</h3>";
      } else if (trimmed.startsWith("## ")) {
        html += "<h2>" + inlinePublish(trimmed.slice(3)) + "</h2>";
      } else {
        html += "<h1>" + inlinePublish(trimmed.slice(2)) + "</h1>";
      }
      continue;
    }

    const numbered = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
    const bullet = trimmed.match(/^[-•]\s+(.+)$/) || trimmed.match(/^\*\s+(.+)$/);
    if (numbered) {
      openList("ol");
      html += "<li>" + inlinePublish(numbered[2]) + "</li>";
      continue;
    }
    if (bullet) {
      openList("ul");
      html += "<li>" + inlinePublish(bullet[1]) + "</li>";
      continue;
    }

    if (trimmed.startsWith("> ")) {
      closeParagraph();
      closeTable();
      closeList();
      html += "<blockquote>" + inlinePublish(trimmed.slice(2)) + "</blockquote>";
      continue;
    }

    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      closeParagraph();
      closeList();
      if (!inTable) {
        const cells = parseRow(trimmed);
        html += "<table><thead><tr>";
        cells.forEach((c) => { html += "<th>" + inlinePublish(c) + "</th>"; });
        html += "</tr></thead><tbody>";
        inTable = true;
        continue;
      }
      if (isSeparator(trimmed)) continue;
      const cells = parseRow(trimmed);
      html += "<tr>";
      cells.forEach((c) => { html += "<td>" + inlinePublish(c) + "</td>"; });
      html += "</tr>";
      continue;
    }

    closeTable();
    closeList();
    const chunks = splitInlineList(trimmed);
    if (chunks.length > 1 && /^\d+[.)]\s+/.test(chunks[0])) {
      openList("ol");
      chunks.forEach((chunk) => {
        const item = chunk.replace(/^\d+[.)]\s+/, "");
        html += "<li>" + inlinePublish(item) + "</li>";
      });
      closeList();
      continue;
    }

    const processed = inlinePublish(trimmed);
    if (!inParagraph) {
      html += "<p>";
      inParagraph = true;
    } else {
      html += " ";
    }
    html += processed;
  }
  closeParagraph();
  closeTable();
  closeList();
  return html;
}

function parseInternalLinks() {
  const raw = document.getElementById("internal-links")?.value?.trim() || "";
  if (!raw) return [];
  const links = [];
  const seen = new Set();
  raw.split("\n").forEach((line) => {
    const parts = line.split("|").map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return;
    let url = parts.find((p) => /^https?:\/\//i.test(p)) || "";
    if (!url) {
      const maybe = parts.find((p) => /\./.test(p) && !p.includes(" "));
      if (maybe) url = maybe.startsWith("http") ? maybe : "https://" + maybe;
    }
    if (!url) return;
    const key = url.replace(/\/$/, "").toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    const others = parts.filter((p) => p !== url);
    const slug = url.replace(/^https?:\/\//i, "").split("/").filter(Boolean).pop() || "";
    links.push({
      url,
      anchor_text: others[0] || slug.replace(/[-_]/g, " ") || url,
      reason: others[1] || "User-provided internal link",
    });
  });
  return links;
}

function scoreTone(score) {
  if (score >= 80) return "high";
  if (score >= 60) return "mid";
  return "low";
}

function renderScoreCard(key, report) {
  const score = report?.score ?? 0;
  const grade = report?.grade || "";
  const summary = report?.summary || "";
  const label = report?.label || key.toUpperCase();
  return `
    <div class="score-card score-${scoreTone(score)}" data-score-tab="${key}">
      <div class="score-ring" style="--pct: ${score}">
        <span class="score-ring-value">${score}</span>
      </div>
      <div class="score-card-copy">
        <div class="score-name">${label}</div>
        <div class="score-grade">${grade}</div>
        <p class="score-summary">${summary}</p>
      </div>
    </div>
  `;
}

function renderScoreFactors(report) {
  const factors = report?.factors || [];
  const tips = report?.tips || [];
  const rows = factors.map((f) => {
    const pct = f.max ? Math.round((f.score / f.max) * 100) : 0;
    return `
      <div class="score-factor">
        <div class="score-factor-top">
          <span>${f.name}</span>
          <span class="mono">${f.score}/${f.max}</span>
        </div>
        <div class="score-bar"><span style="width:${pct}%"></span></div>
        <p class="score-factor-note">${f.note || ""}</p>
      </div>
    `;
  }).join("");
  const tipsHtml = tips.length
    ? `<ul class="score-tips">${tips.map((t) => `<li>${t}</li>`).join("")}</ul>`
    : `<p class="no-issues">No optimization tips — this score looks strong.</p>`;
  return `
    <div class="score-breakdown">
      <div class="score-factors">${rows}</div>
      <div class="meta-card">
        <div class="meta-label">How to improve ${report?.label || ""}</div>
        ${tipsHtml}
      </div>
    </div>
  `;
}

function renderOutput(result) {
  const stats = articleStats(result);
  const seo = result.seo || {};
  const serp = result.serp || {};
  const scores = result.scores || {};
  const handoff = readCompetitorHandoff();
  const competitorCount = serp.results_count || (handoff?.competitors || []).length || 0;

  const faqsHtml = (seo.faqs || []).map(f =>
    '<div class="meta-card"><div class="meta-label">FAQ</div><div class="meta-value"><strong>' +
    (f.question || "") + '</strong><br>' + (f.answer || "") + '</div></div>'
  ).join("");

  const issueRowsHtml = (seo.issues || []).map(i =>
    '<li><span class="issue-marker warn">' + (i.severity || "note").toUpperCase() + '</span><span><strong>' +
    (i.issue_type || "") + '</strong> — ' + (i.recommendation || "") + '</span></li>'
  ).join("");

  const nlpKeywordsHtml = serp.nlp_keywords
    ? '<div class="meta-card"><div class="meta-label">NLP Keywords (SERP)</div><div class="meta-value mono">' +
      serp.nlp_keywords.join(", ") + '</div></div>'
    : "";

  const linksHtml = (seo.internal_links || []).length
    ? '<div class="meta-card"><div class="meta-label">Internal Links</div><div class="meta-value">' +
      seo.internal_links.map((l) => {
        const label = l.anchor_text || l.url;
        return '<a href="' + (l.url || "#") + '" target="_blank" rel="noopener noreferrer">' +
          label + '</a>';
      }).join("<br>") +
      '</div></div>'
    : "";

  const seoReport = scores.seo || {};
  const geoReport = scores.geo || {};
  const aeoReport = scores.aeo || {};
  const scoresHtml = (scores.seo || scores.geo || scores.aeo)
    ? `<div class="scores-panel">
        <div class="scores-grid">
          ${renderScoreCard("seo", seoReport)}
          ${renderScoreCard("geo", geoReport)}
          ${renderScoreCard("aeo", aeoReport)}
        </div>
      </div>`
    : "";

  document.getElementById("output-body").innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${stats.word_count ?? 0}</div><div class="stat-label">Word Count</div></div>
      <div class="stat-card"><div class="stat-value">${stats.h1_count ?? 0}</div><div class="stat-label">H1 Count</div></div>
      <div class="stat-card"><div class="stat-value">${stats.keyword_count ?? 0}</div><div class="stat-label">Keyword Hits</div></div>
    </div>
    ${scoresHtml}
    <div class="tabs" role="tablist">
      <button class="tab-btn active" role="tab" data-tab="article" aria-selected="true">Article</button>
      <button class="tab-btn" role="tab" data-tab="scores" aria-selected="false">Scores</button>
      <button class="tab-btn" role="tab" data-tab="seo" aria-selected="false">SEO</button>
      <button class="tab-btn" role="tab" data-tab="serp" aria-selected="false">SERP</button>
    </div>
    <div class="tab-panel active" id="tab-article" role="tabpanel">
      <div class="article-toolbar">
        <button type="button" class="btn-copy-article" id="copy-article-btn">Copy article</button>
        <button type="button" class="btn-new-article" id="open-editor-btn">Open in Editor →</button>
      </div>
      <div class="article-body" id="article-publish">${markdownToHtml(result.article || "")}</div>
    </div>
    <div class="tab-panel" id="tab-scores" role="tabpanel">
      <div class="score-detail">
        <section>
          <h3>SEO — Search</h3>
          <p class="score-detail-lead">${seoReport.summary || ""} Score ${seoReport.score ?? "—"} (${seoReport.grade || ""}).</p>
          ${renderScoreFactors(seoReport)}
        </section>
        <section>
          <h3>GEO — Generative engines</h3>
          <p class="score-detail-lead">${geoReport.summary || ""} Score ${geoReport.score ?? "—"} (${geoReport.grade || ""}).</p>
          ${renderScoreFactors(geoReport)}
        </section>
        <section>
          <h3>AEO — Answer engines</h3>
          <p class="score-detail-lead">${aeoReport.summary || ""} Score ${aeoReport.score ?? "—"} (${aeoReport.grade || ""}).</p>
          ${renderScoreFactors(aeoReport)}
        </section>
      </div>
    </div>
    <div class="tab-panel" id="tab-seo" role="tabpanel">
      <div class="meta-card"><div class="meta-label">Meta Title</div><div class="meta-value">${seo.meta_title || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Meta Description</div><div class="meta-value">${seo.meta_description || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Search Intent</div><div class="meta-value">${result.brief?.search_intent || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Secondary Keywords</div><div class="meta-value mono">${(seo.secondary_keywords || []).join(", ") || "—"}</div></div>
      ${linksHtml}
      ${faqsHtml}
      ${issueRowsHtml ? '<div class="meta-card"><div class="meta-label">SEO Recommendations</div><ul class="issue-list">' + issueRowsHtml + '</ul></div>' : ""}
    </div>
    <div class="tab-panel" id="tab-serp" role="tabpanel">
      <div class="meta-card"><div class="meta-label">Keyword Analyzed</div><div class="meta-value">${serp.keyword || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Competitor Results</div><div class="meta-value">${competitorCount} pages analyzed</div></div>
      ${nlpKeywordsHtml}
      <div class="meta-card"><div class="meta-label">Related Queries</div><div class="meta-value">${(serp.related_queries || []).join("<br>") || "—"}</div></div>
    </div>
  `;

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });

  document.querySelectorAll(".score-card[data-score-tab]").forEach((card) => {
    card.addEventListener("click", () => {
      const tabBtn = document.querySelector('.tab-btn[data-tab="scores"]');
      tabBtn?.click();
    });
  });

  const copyBtn = document.getElementById("copy-article-btn");
  copyBtn?.addEventListener("click", async () => {
    const body = document.getElementById("article-publish");
    if (!body) return;
    const html = body.innerHTML.trim();
    try {
      if (navigator.clipboard && window.ClipboardItem) {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([body.innerText], { type: "text/plain" }),
          }),
        ]);
      } else {
        await navigator.clipboard.writeText(html);
      }
      copyBtn.textContent = "Copied";
      setTimeout(() => { copyBtn.textContent = "Copy article"; }, 1600);
    } catch (err) {
      copyBtn.textContent = "Copy failed";
      setTimeout(() => { copyBtn.textContent = "Copy article"; }, 1600);
    }
  });

  document.getElementById("open-editor-btn")?.addEventListener("click", () => {
    const body = document.getElementById("article-publish");
    const html = body?.innerHTML?.trim() || result.article || "";
    let competitorAvgWords = null;
    try {
      const snaps = JSON.parse(localStorage.getItem("ba-competitor-snapshots") || "[]");
      const words = (snaps[0]?.result?.competitors || []).map((c) => c.word_count).filter(Boolean);
      if (words.length) {
        competitorAvgWords = Math.round(words.reduce((a, b) => a + b, 0) / words.length);
      }
    } catch (err) { competitorAvgWords = null; }
    const payload = {
      source: PAGE === "rewriter" ? "rewriter" : "writer",
      title: result.brief?.title || result.seo?.meta_title || "",
      article: html,
      keyword: result.brief?.primary_keyword || result.serp?.keyword || "",
      secondaryKeywords: (result.brief?.secondary_keywords || []).map((k) => k.phrase || k).filter(Boolean),
      metaTitle: result.seo?.meta_title || "",
      metaDescription: result.seo?.meta_description || "",
      scores: result.scores || {},
      competitorAvgWords,
    };
    sessionStorage.setItem("ba-editor-handoff", JSON.stringify(payload));
    sessionStorage.setItem("ba-editor-handoff-pending", "1");
    window.location.href = "/editor";
  });
}

function updateStreamTracker(activeIndex, status, message) {
  const tracker = document.getElementById("tracker");
  if (!tracker) return;
  const stages = getStages();
  const stageName = stages[activeIndex] || "";
  const isDone = status === "done";
  tracker.innerHTML = `
    <div class="tracker-step ${isDone ? "done" : "active"}">
      <span class="tracker-dot"></span>
      <span class="tracker-label">${stageName}</span>
    </div>
    ${message ? '<div class="tracker-msg ' + (isDone ? "done" : "") + '">' + (isDone ? "✓ " : "⏳ ") + message + '</div>' : ""}
  `;
}

// Panel resize
(function() {
  const divider = document.getElementById("panel-divider");
  if (!divider) return;
  const panel = divider.previousElementSibling;
  let isDragging = false;

  divider.addEventListener("mousedown", (e) => {
    e.preventDefault();
    isDragging = true;
    divider.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const layout = divider.parentElement;
    const rect = layout.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const min = 320;
    const max = Math.floor(rect.width * 0.6);
    const clamped = Math.max(min, Math.min(max, x));
    panel.style.width = clamped + "px";
  });

  document.addEventListener("mouseup", () => {
    if (!isDragging) return;
    isDragging = false;
    divider.classList.remove("dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });

  divider.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      divider.click();
    }
  });
})();

// Guide modal
const guideOverlay = document.getElementById("guide-overlay");
function openGuide(e) {
  e?.preventDefault();
  if (!guideOverlay) return;
  guideOverlay.classList.remove("hidden");
}
function closeGuide() {
  if (!guideOverlay) return;
  guideOverlay.classList.add("hidden");
}
document.querySelectorAll(".guide-trigger").forEach((btn) => {
  btn.addEventListener("click", openGuide);
});
document.querySelector(".guide-close")?.addEventListener("click", closeGuide);
guideOverlay?.addEventListener("click", (e) => {
  if (e.target === guideOverlay) closeGuide();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && guideOverlay && !guideOverlay.classList.contains("hidden")) {
    closeGuide();
  }
});

async function consumeSseStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  const stages = getStages();
  const stageIndex = {};
  stages.forEach((stage, i) => { stageIndex[stage.toLowerCase()] = i; });

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop();

    for (const evt of events) {
      let eventName = "message";
      let dataStr = "";
      for (const line of evt.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
      }
      if (!dataStr) continue;

      let data;
      try { data = JSON.parse(dataStr); } catch (e) { continue; }

      if (eventName === "stage") {
        const st = data.stage || "";
        const idx = stageIndex[st];
        if (idx !== undefined) updateStreamTracker(idx, data.status, data.message);
      } else if (eventName === "result") {
        result = data;
      } else if (eventName === "error") {
        throw new Error(data.message || "Generation failed");
      }
    }
  }

  return result;
}

function showWorkError(message) {
  document.getElementById("output-body").innerHTML =
    '<div class="error-banner"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg><span>' + message + '</span></div>';
}

// Form submit
document.getElementById("brief-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();

  const btn = document.getElementById("generate-btn");
  const btnContent = btn.querySelector(".btn-content");
  const btnLoader = btn.querySelector(".btn-loader");

  // Client-side validation
  const instructionsVal = document.getElementById("instructions").value.trim();
  const hookBriefVal = document.getElementById("hook-brief").value.trim();
  const brandVoiceVal = buildBrandVoice() || "";
  const targetWordsVal = document.getElementById("target-words").value.trim();

  const wordCount = (s) => s ? s.split(/\s+/).filter(Boolean).length : 0;

  if (wordCount(instructionsVal) > 150) { alert("Additional Instructions limited to 150 words."); return; }
  if (wordCount(hookBriefVal) > 30) { alert("Hook Brief limited to 30 words."); return; }
  if (wordCount(brandVoiceVal) > 100) { alert("Brand Voice limited to 100 words."); return; }
  const audienceVal = document.getElementById("audience").value.trim();
  if (wordCount(audienceVal) > 40) { alert("Target Audience limited to 40 words."); return; }
  const parsedLinks = parseInternalLinks();
  if (parsedLinks.length > 12) { alert("Internal Links limited to 12 URLs."); return; }
  if (targetWordsVal !== "") {
    const n = parseInt(targetWordsVal, 10);
    if (isNaN(n) || n < 300 || n > 8000) { alert("Target Words must be 300–8000."); return; }
  }

  btn.disabled = true;
  btnContent.classList.add("hidden");
  btnLoader.classList.remove("hidden");

  startTimer();
  document.getElementById("output-body").innerHTML = `
    <div class="empty-state generating">
      <div class="spinner-ring"></div>
      <h3>Generating article…</h3>
      <p>Analyzing competitors, creating brief, and writing. This takes 1–3 minutes.</p>
    </div>
  `;

  const payload = {
    keyword: document.getElementById("keyword").value.trim(),
    title: document.getElementById("title").value.trim() || null,
    search_intent: document.getElementById("search-intent").value || "informational",
    size: document.getElementById("size").value,
    target_word_count: parseInt(document.getElementById("target-words").value, 10) || null,
    article_type: document.getElementById("article-type").value || null,
    tone: document.getElementById("tone").value,
    point_of_view: document.getElementById("pov").value || null,
    readability: document.getElementById("readability").value || null,
    brand_voice: buildBrandVoice(),
    language: document.getElementById("language").value,
    brand_name: document.getElementById("brand-name").value.trim() || null,
    website: document.getElementById("website").value.trim() || null,
    include_faq: document.getElementById("include-faq").checked,
    include_takeaways: document.getElementById("include-takeaways").checked,
    include_conclusion: document.getElementById("include-conclusion").checked,
    include_tables: document.getElementById("include-tables").checked,
    include_h3: document.getElementById("include-h3").checked,
    include_lists: document.getElementById("include-lists").checked,
    include_quotes: document.getElementById("include-quotes").checked,
    include_italics: document.getElementById("include-italics").checked,
    include_bold: document.getElementById("include-bold").checked,
    hook_type: document.getElementById("hook").value,
    hook_brief: document.getElementById("hook-brief").value.trim() || null,
    additional_instructions: document.getElementById("instructions").value.trim(),
    audience: audienceVal || null,
    internal_links: parsedLinks,
  };

  try {
    const response = await fetch(`${API_BASE}/generate-1click-stream`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload)
    });

    if (!response.ok || !response.body) {
      stopTimer();
      renderTracker(-1);
      const errBody = await response.json().catch(() => ({}));
      throw new Error(errBody.detail?.message || ("Request failed with status " + response.status));
    }

    const result = await consumeSseStream(response);
    stopTimer();
    if (!result) throw new Error("No result received from server");
    renderTracker(getStages().length);
    renderOutput(result);

  } catch (err) {
    stopTimer();
    renderTracker(-1);
    showWorkError("Generation failed: " + err.message);
  } finally {
    btn.disabled = false;
    btnContent.classList.remove("hidden");
    btnLoader.classList.add("hidden");
  }
});

document.getElementById("rewrite-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();

  const btn = document.getElementById("generate-btn");
  const btnContent = btn.querySelector(".btn-content");
  const btnLoader = btn.querySelector(".btn-loader");
  const source = document.getElementById("source-article")?.value.trim() || "";
  const instructionsVal = document.getElementById("instructions")?.value.trim() || "";
  const audienceVal = document.getElementById("audience")?.value.trim() || "";
  const targetWordsVal = document.getElementById("target-words")?.value.trim() || "";

  if (source.length < 200) {
    alert("Paste at least 200 characters of the original article.");
    return;
  }
  if (wordCountOf(instructionsVal) > 150) {
    alert("Additional Instructions limited to 150 words.");
    return;
  }
  if (wordCountOf(audienceVal) > 40) {
    alert("Target Audience limited to 40 words.");
    return;
  }
  if (targetWordsVal !== "") {
    const n = parseInt(targetWordsVal, 10);
    if (isNaN(n) || n < 300 || n > 8000) {
      alert("Target Words must be 300–8000.");
      return;
    }
  }

  btn.disabled = true;
  btnContent.classList.add("hidden");
  btnLoader.classList.remove("hidden");
  startTimer();
  document.getElementById("output-body").innerHTML = `
    <div class="empty-state generating">
      <div class="spinner-ring"></div>
      <h3>Rewriting article…</h3>
      <p>Keeping the original facts while producing a new publish-ready draft. This takes 1–3 minutes.</p>
    </div>
  `;

  const payload = {
    source_article: source,
    keyword: document.getElementById("keyword")?.value.trim() || null,
    title: document.getElementById("title")?.value.trim() || null,
    tone: document.getElementById("tone")?.value || "friendly",
    target_word_count: parseInt(document.getElementById("target-words")?.value, 10) || null,
    point_of_view: document.getElementById("pov")?.value || null,
    audience: audienceVal || null,
    additional_instructions: instructionsVal,
    brand_name: document.getElementById("brand-name")?.value.trim() || null,
    include_faq: document.getElementById("include-faq")?.checked ?? true,
    include_takeaways: document.getElementById("include-takeaways")?.checked ?? true,
    include_conclusion: document.getElementById("include-conclusion")?.checked ?? true,
    include_h3: true,
    include_lists: true,
    include_tables: false,
    include_quotes: false,
  };

  try {
    const response = await fetch(`${API_BASE}/rewrite-stream`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body) {
      stopTimer();
      renderTracker(-1);
      const errBody = await response.json().catch(() => ({}));
      const detail = errBody.detail;
      const message = (typeof detail === "string" && detail)
        || detail?.message
        || ("Request failed with status " + response.status);
      throw new Error(message);
    }

    const result = await consumeSseStream(response);
    stopTimer();
    if (!result) throw new Error("No result received from server");
    renderTracker(getStages().length);
    renderOutput(result);
  } catch (err) {
    stopTimer();
    renderTracker(-1);
    showWorkError("Rewrite failed: " + err.message);
  } finally {
    btn.disabled = false;
    btnContent.classList.remove("hidden");
    btnLoader.classList.add("hidden");
  }
});

function restoreCompetitorHandoff() {
  if (PAGE !== "rewriter") return;
  const pending = sessionStorage.getItem("ba-competitor-handoff-pending") === "1";
  if (!pending) {
    sessionStorage.removeItem("ba-competitor-handoff");
    sessionStorage.removeItem("ba-competitor-handoff-pending");
    window.__competitorHandoff = null;
    return;
  }

  const data = readCompetitorHandoffFromStorage();
  sessionStorage.removeItem("ba-competitor-handoff-pending");
  sessionStorage.removeItem("ba-competitor-handoff");
  if (!data) return;

  window.__competitorHandoff = data;
  console.log(
    "[Blog Rewriter] handoff competitors",
    (data.competitors || []).length,
    data.gaps
  );

  const source = document.getElementById("source-article");
  const extractError = document.getElementById("source-extract-error");
  const extractOk = document.getElementById("source-extract-ok");
  const sourceText = String(data.sourceArticle || "").trim();
  const looksLikeChrome = /<(?:html|head|nav|svg|script|header)\b/i.test(sourceText);
  const tooShort = wordCountOf(sourceText) < 100;
  if (source) {
    if (data.sourceExtractError || looksLikeChrome || tooShort) {
      source.value = "";
      if (extractError) extractError.hidden = false;
      if (extractOk) extractOk.hidden = true;
    } else if (!source.value.trim()) {
      source.value = sourceText;
      if (extractError) extractError.hidden = true;
      if (extractOk) extractOk.hidden = false;
    }
  }
  const keyword = document.getElementById("keyword");
  if (keyword && data.targetKeyword && !keyword.value.trim()) {
    keyword.value = data.targetKeyword;
    const count = document.getElementById("keyword-count");
    if (count) count.textContent = String(keyword.value.length);
  }
  const title = document.getElementById("title");
  if (title && data.sourceTitle && !title.value.trim()) {
    title.value = data.sourceTitle;
  }
  const instructions = document.getElementById("instructions");
  if (instructions && !instructions.value.trim()) {
    instructions.value = buildGapInstructions(data.gaps || [], data.oldScores || {});
    const badge = document.getElementById("instructions-count");
    if (badge) {
      const words = wordCountOf(instructions.value.trim());
      badge.textContent = words + "/150 words";
      badge.classList.toggle("over", words > 150);
    }
  }
  renderHandoffSummary(data);
}

function readCompetitorHandoff() {
  return window.__competitorHandoff || null;
}

function readCompetitorHandoffFromStorage() {
  try {
    const raw = sessionStorage.getItem("ba-competitor-handoff");
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (err) {
    return null;
  }
}

function isCleanGapTitle(title) {
  const text = String(title || "").trim();
  if (!text || /<[^>]+>/.test(text)) return false;
  if (text.includes("·") || /^\d+[\.)]/.test(text)) return false;
  if (/\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b.*\d{4}/i.test(text)) {
    return false;
  }
  return true;
}

function buildGapInstructions(gaps, scores) {
  const clean = (gaps || []).filter((gap) => isCleanGapTitle(gap.title));
  const lines = ["Close these content gaps from competitor analysis:"];
  clean.forEach((gap) => {
    const title = String(gap.title || "").trim();
    const desc = String(gap.description || "").trim();
    lines.push(`- ${title}${desc ? ": " + desc : ""}`);
  });
  if (scores.seo) {
    lines.push(`Previous scores: SEO ${scores.seo}, GEO ${scores.geo}, AEO ${scores.aeo}.`);
  }
  let text = lines.join("\n");
  const words = text.trim().split(/\s+/);
  if (words.length > 150) text = words.slice(0, 150).join(" ");
  return text.slice(0, 1000);
}

function renderHandoffSummary(data) {
  const output = document.getElementById("output-body");
  if (!output) return;
  const count = (data.competitors || []).length;
  const gaps = (data.gaps || []).filter((gap) => isCleanGapTitle(gap.title));
  const gapHtml = gaps.length
    ? gaps.map((gap) => `<li><strong>${escapeHtml(gap.title)}</strong> — ${escapeHtml(gap.description || "")}</li>`).join("")
    : "<li>No gap summaries were attached.</li>";
  output.innerHTML = `
    <div class="empty-state" style="align-items:stretch;text-align:left">
      <h3>Ready to rewrite</h3>
      <p>Source, keyword, and gap notes were loaded from Competitor Analysis.</p>
      <div class="meta-card">
        <div class="meta-label">Competitor Results</div>
        <div class="meta-value">${count} pages analyzed</div>
      </div>
      <div class="meta-card">
        <div class="meta-label">Content Gaps</div>
        <ul class="issue-list">${gapHtml}</ul>
      </div>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
restoreCompetitorHandoff();