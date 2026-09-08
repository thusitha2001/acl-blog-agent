const STAGES = ["SERP", "Brief", "Draft", "SEO", "Validate"];
const STAGES_WITH_SCRAPE = ["SERP", "Brief", "Scrape", "Draft", "SEO", "Validate"];

const API_BASE = "";

let _genTimer = null;

function authHeaders() {
  return { "Content-Type": "application/json" };
}

function getStages() {
  const website = document.getElementById("website")?.value?.trim() || "";
  return website ? STAGES_WITH_SCRAPE : STAGES;
}

function renderTracker(activeIndex, elapsed) {
  const tracker = document.getElementById("tracker");
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

document.getElementById("keyword").addEventListener("input", function() {
  const count = document.getElementById("keyword-count");
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
document.getElementById("brand-voice-select").addEventListener("change", function() {
  const editor = document.getElementById("brand-voice-editor");
  if (this.value === "__create__") {
    editor.classList.remove("hidden");
  } else {
    editor.classList.add("hidden");
  }
});

function buildBrandVoice() {
  const select = document.getElementById("brand-voice-select").value;
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

function markdownToHtml(md) {
  const lines = md.split("\n");
  let html = "";
  let inParagraph = false;
  let inTable = false;

  function closeParagraph() { if (inParagraph) { html += "</p>"; inParagraph = false; } }
  function closeTable() { if (inTable) { html += "</tbody></table>"; inTable = false; } }
  function parseRow(line) { return line.split("|").slice(1, -1).map(c => c.trim()); }
  function isSeparator(line) { return /^\|[\s:-]+\|$/.test(line.trim()); }
  function applyInline(text) { return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>"); }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { closeParagraph(); closeTable(); continue; }
    if (trimmed.startsWith("### ")) { closeParagraph(); closeTable(); html += "<h3>" + trimmed.slice(4) + "</h3>"; continue; }
    if (trimmed.startsWith("## ")) { closeParagraph(); closeTable(); html += "<h2>" + trimmed.slice(3) + "</h2>"; continue; }
    if (trimmed.startsWith("# ")) { closeParagraph(); closeTable(); html += "<h1>" + trimmed.slice(2) + "</h1>"; continue; }
    if (trimmed.startsWith("- ")) { closeParagraph(); closeTable(); html += "<p class='list-item'>- " + trimmed.slice(2) + "</p>"; continue; }
    if (trimmed.startsWith("> ")) { closeParagraph(); closeTable(); html += "<blockquote>" + applyInline(trimmed.slice(2)) + "</blockquote>"; continue; }
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      if (!inTable) {
        closeParagraph();
        const cells = parseRow(trimmed);
        html += '<table><thead><tr>';
        cells.forEach(c => { html += "<th>" + applyInline(c) + "</th>"; });
        html += "</tr></thead><tbody>";
        inTable = true;
        continue;
      }
      if (isSeparator(trimmed)) continue;
      const cells = parseRow(trimmed);
      html += "<tr>";
      cells.forEach(c => { html += "<td>" + applyInline(c) + "</td>"; });
      html += "</tr>";
      continue;
    }
    closeTable();
    let processed = applyInline(trimmed);
    if (!inParagraph) { html += "<p>"; inParagraph = true; } else { html += " "; }
    html += processed;
  }
  closeParagraph();
  closeTable();
  return html;
}

function renderOutput(result) {
  const validation = result.validation || {};
  const seo = result.seo || {};
  const serp = result.serp || {};
  const errors = validation.errors || [];
  const warnings = validation.warnings || [];

  const badgeHtml = validation.passed
    ? '<span class="badge badge-pass">Validation passed</span>'
    : '<span class="badge badge-error">Validation failed</span>';

  let issuesHtml = "";
  if (errors.length || warnings.length) {
    issuesHtml = '<ul class="issue-list">';
    errors.forEach(e => { issuesHtml += '<li><span class="issue-marker error">ERR</span><span>' + e + '</span></li>'; });
    warnings.forEach(w => { issuesHtml += '<li><span class="issue-marker warn">WARN</span><span>' + w + '</span></li>'; });
    issuesHtml += '</ul>';
  } else {
    issuesHtml = '<p class="no-issues">No errors or warnings.</p>';
  }

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

  document.getElementById("output-body").innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${validation.word_count ?? "—"}</div><div class="stat-label">Words</div></div>
      <div class="stat-card"><div class="stat-value">${validation.h1_count ?? "—"}</div><div class="stat-label">H1 Count</div></div>
      <div class="stat-card"><div class="stat-value">${validation.keyword_count ?? "—"}</div><div class="stat-label">Keyword Hits</div></div>
      <div class="stat-card"><div class="stat-value">${errors.length}</div><div class="stat-label">Errors</div></div>
    </div>
    <div class="badge-row">${badgeHtml}</div>
    <div class="tabs" role="tablist">
      <button class="tab-btn active" role="tab" data-tab="article" aria-selected="true">Article</button>
      <button class="tab-btn" role="tab" data-tab="seo" aria-selected="false">SEO</button>
      <button class="tab-btn" role="tab" data-tab="serp" aria-selected="false">SERP</button>
      <button class="tab-btn" role="tab" data-tab="validation" aria-selected="false">Validation</button>
    </div>
    <div class="tab-panel active" id="tab-article" role="tabpanel">
      <div class="article-body">${markdownToHtml(result.article || "")}</div>
    </div>
    <div class="tab-panel" id="tab-seo" role="tabpanel">
      <div class="meta-card"><div class="meta-label">Meta Title</div><div class="meta-value">${seo.meta_title || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Meta Description</div><div class="meta-value">${seo.meta_description || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Secondary Keywords</div><div class="meta-value mono">${(seo.secondary_keywords || []).join(", ") || "—"}</div></div>
      ${faqsHtml}
      ${issueRowsHtml ? '<div class="meta-card"><div class="meta-label">SEO Recommendations</div><ul class="issue-list">' + issueRowsHtml + '</ul></div>' : ""}
    </div>
    <div class="tab-panel" id="tab-serp" role="tabpanel">
      <div class="meta-card"><div class="meta-label">Keyword Analyzed</div><div class="meta-value">${serp.keyword || "—"}</div></div>
      <div class="meta-card"><div class="meta-label">Competitor Results</div><div class="meta-value">${serp.results_count || 0} pages analyzed</div></div>
      ${nlpKeywordsHtml}
      <div class="meta-card"><div class="meta-label">Related Queries</div><div class="meta-value">${(serp.related_queries || []).join("<br>") || "—"}</div></div>
    </div>
    <div class="tab-panel" id="tab-validation" role="tabpanel">
      ${issuesHtml}
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
}

function updateStreamTracker(activeIndex, status, message) {
  const tracker = document.getElementById("tracker");
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
function openGuide() { guideOverlay.classList.remove("hidden"); }
function closeGuide() { guideOverlay.classList.add("hidden"); }
document.getElementById("guide-trigger")?.addEventListener("click", openGuide);
document.querySelector(".guide-close")?.addEventListener("click", closeGuide);
guideOverlay?.addEventListener("click", (e) => { if (e.target === guideOverlay) closeGuide(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !guideOverlay?.classList.contains("hidden")) closeGuide(); });

// Form submit
document.getElementById("brief-form").addEventListener("submit", async (e) => {
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

    stopTimer();

    if (!result) throw new Error("No result received from server");

    renderTracker(getStages().length);
    renderOutput(result);

  } catch (err) {
    stopTimer();
    renderTracker(-1);
    document.getElementById("output-body").innerHTML =
      '<div class="error-banner"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg><span>Generation failed: ' + err.message + '</span></div>';
  } finally {
    btn.disabled = false;
    btnContent.classList.remove("hidden");
    btnLoader.classList.add("hidden");
  }
});