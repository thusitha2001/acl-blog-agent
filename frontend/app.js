const STAGES = ["SERP", "Brief", "Draft", "SEO", "Validate"];

const API_BASE = "";

let _genTimer = null;

function renderTracker(activeIndex, elapsed) {
  const tracker = document.getElementById("tracker");
  tracker.innerHTML = "";
  if (activeIndex >= 0 && activeIndex < STAGES.length && elapsed !== undefined) {
    const pct = Math.min(Math.round((elapsed / 180) * 100), 99);
    tracker.innerHTML = '<div class="step active"><span class="dot"></span><span>' + STAGES[activeIndex] + '</span></div><span style="margin-left:10px;color:var(--teal);font-size:12px;">' + pct + '% - ' + elapsed + 's</span>';
  } else if (activeIndex >= STAGES.length) {
    tracker.innerHTML = '<div class="step done"><span class="dot"></span><span>Done!</span></div>';
  } else {
    tracker.innerHTML = "";
  }
}

function startTimer() {
  let elapsed = 0;
  let stageIdx = 0;
  const stageAt = [0, 5, 10, 25, 40];
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

document.getElementById("keyword").addEventListener("input", function() {
  const count = document.getElementById("keyword-count");
  const len = this.value.length;
  count.textContent = len;
  count.className = len > 200 ? "char-count over" : "char-count";
});

document.querySelectorAll(".pill-toggle").forEach(pill => {
  const checkbox = pill.querySelector("input[type=checkbox]");
  if (checkbox.checked) pill.classList.add("active");
  pill.addEventListener("click", (e) => {
    e.preventDefault();
    checkbox.checked = !checkbox.checked;
    pill.classList.toggle("active", checkbox.checked);
  });
});

document.getElementById("brand-voice-select").addEventListener("change", function() {
  const editor = document.getElementById("brand-voice-editor");
  if (this.value === "__create__") {
    editor.classList.remove("collapsed");
  } else {
    editor.classList.add("collapsed");
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

  function closeParagraph() {
    if (inParagraph) { html += "</p>"; inParagraph = false; }
  }

  function closeTable() {
    if (inTable) { html += "</tbody></table>"; inTable = false; }
  }

  function parseRow(line) {
    return line.split("|").slice(1, -1).map(c => c.trim());
  }

  function isSeparator(line) {
    return /^\|[\s:-]+\|$/.test(line.trim());
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { closeParagraph(); closeTable(); continue; }
    if (trimmed.startsWith("### ")) { closeParagraph(); closeTable(); html += "<h3>" + trimmed.slice(4) + "</h3>"; continue; }
    if (trimmed.startsWith("## ")) { closeParagraph(); closeTable(); html += "<h2>" + trimmed.slice(3) + "</h2>"; continue; }
    if (trimmed.startsWith("# ")) { closeParagraph(); closeTable(); html += "<h1>" + trimmed.slice(2) + "</h1>"; continue; }
    if (trimmed.startsWith("- ")) {
      closeParagraph(); closeTable();
      html += "<p style='margin-left:16px'>- " + trimmed.slice(2) + "</p>";
      continue;
    }

    if (trimmed.startsWith("> ")) {
      closeParagraph(); closeTable();
      html += "<blockquote>" + applyInline(trimmed.slice(2)) + "</blockquote>";
      continue;
    }
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      if (!inTable) {
        closeParagraph();
        const cells = parseRow(trimmed);
        html += '<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:13px"><thead><tr>';
        cells.forEach(c => { html += '<th style="border:1px solid #d2dbe4;padding:6px 10px;background:#f4f6f9;text-align:left">' + applyInline(c) + '</th>'; });
        html += '</tr></thead><tbody>';
        inTable = true;
        continue;
      }
      if (isSeparator(trimmed)) continue;
      const cells = parseRow(trimmed);
      html += '<tr>';
      cells.forEach(c => { html += '<td style="border:1px solid #d2dbe4;padding:6px 10px">' + applyInline(c) + '</td>'; });
      html += '</tr>';
      continue;
    }

    closeTable();
    let processed = trimmed.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    processed = processed.replace(/\*(.+?)\*/g, "<em>$1</em>");

    if (!inParagraph) { html += "<p>"; inParagraph = true; } else { html += " "; }
    html += processed;
  }
  closeParagraph();
  closeTable();
  return html;
}

function applyInline(text) {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>");
}

function renderOutput(result) {
  const validation = result.validation || {};
  const seo = result.seo || {};
  const serp = result.serp || {};
  const errors = validation.errors || [];
  const warnings = validation.warnings || [];

  let badgeHtml = validation.passed
    ? '<span class="badge pass">Validation passed</span>'
    : '<span class="badge error">Validation failed</span>';

  let issuesHtml = "";
  if (errors.length || warnings.length) {
    issuesHtml = '<ul class="issue-list">';
    errors.forEach(e => { issuesHtml += '<li><span class="marker error">ERR</span><span>' + e + '</span></li>'; });
    warnings.forEach(w => { issuesHtml += '<li><span class="marker warn">WARN</span><span>' + w + '</span></li>'; });
    issuesHtml += '</ul>';
  } else {
    issuesHtml = '<p style="font-size:13px; color: var(--ink-soft);">No errors or warnings.</p>';
  }

  const faqsHtml = (seo.faqs || []).map(f =>
    '<div class="meta-card"><div class="label">FAQ</div><div class="value"><strong>' +
    (f.question || "") + '</strong><br>' + (f.answer || "") + '</div></div>'
  ).join("");

  const issueRowsHtml = (seo.issues || []).map(i =>
    '<li><span class="marker warn">' + (i.severity || "note").toUpperCase() + '</span><span><strong>' +
    (i.issue_type || "") + '</strong> -- ' + (i.recommendation || "") + '</span></li>'
  ).join("");

  const nlpKeywordsHtml = serp.nlp_keywords
    ? '<div class="meta-card"><div class="label">NLP Keywords (from SERP)</div><div class="value mono">' +
      serp.nlp_keywords.join(", ") + '</div></div>'
    : "";

  document.getElementById("output-body").innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="num">${validation.word_count ?? "--"}</div><div class="lbl">Words</div></div>
      <div class="stat-box"><div class="num">${validation.h1_count ?? "--"}</div><div class="lbl">H1 count</div></div>
      <div class="stat-box"><div class="num">${validation.keyword_count ?? "--"}</div><div class="lbl">Keyword hits</div></div>
      <div class="stat-box"><div class="num">${errors.length}</div><div class="lbl">Errors</div></div>
    </div>
    <div style="margin-bottom: 16px;">${badgeHtml}</div>
    <div class="tabs">
      <button class="tab-btn active" data-tab="article">Article</button>
      <button class="tab-btn" data-tab="seo">SEO</button>
      <button class="tab-btn" data-tab="serp">SERP</button>
      <button class="tab-btn" data-tab="validation">Validation</button>
    </div>
    <div class="tab-content active" id="tab-article">
      <div class="article-body">${markdownToHtml(result.article || "")}</div>
    </div>
    <div class="tab-content" id="tab-seo">
      <div class="meta-card"><div class="label">Meta title</div><div class="value">${seo.meta_title || "--"}</div></div>
      <div class="meta-card"><div class="label">Meta description</div><div class="value">${seo.meta_description || "--"}</div></div>
      <div class="meta-card"><div class="label">Secondary keywords</div><div class="value mono">${(seo.secondary_keywords || []).join(", ") || "--"}</div></div>
      ${faqsHtml}
      ${issueRowsHtml ? '<div class="meta-card"><div class="label">SEO recommendations</div><ul class="issue-list">' + issueRowsHtml + '</ul></div>' : ""}
    </div>
    <div class="tab-content" id="tab-serp">
      <div class="meta-card"><div class="label">Keyword analyzed</div><div class="value">${serp.keyword || "--"}</div></div>
      <div class="meta-card"><div class="label">Competitor results</div><div class="value">${serp.results_count || 0} pages analyzed</div></div>
      ${nlpKeywordsHtml}
      <div class="meta-card"><div class="label">Related queries</div><div class="value">${(serp.related_queries || []).join("<br>") || "--"}</div></div>
    </div>
    <div class="tab-content" id="tab-validation">
      ${issuesHtml}
    </div>
  `;

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });
}

// Panel Resize Divider
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
    const min = 300;
    const max = Math.floor(rect.width * 0.5);
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
})();

document.getElementById("brief-form").addEventListener("submit", async (e) => {
  e.preventDefault();

  const btn = document.getElementById("generate-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Analyzing SERP & generating...';

  startTimer();
  document.getElementById("output-body").innerHTML =
    '<div class="empty-state">Analyzing competitors, generating brief, and writing article. This takes 1-3 minutes.</div>';

  const payload = {
    keyword: document.getElementById("keyword").value.trim(),
    title: document.getElementById("title").value.trim() || null,
    size: document.getElementById("size").value,
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
    hook_type: document.getElementById("hook").value,
    hook_brief: document.getElementById("hook-brief").value.trim() || null,
    additional_instructions: document.getElementById("instructions").value.trim(),
  };

  try {
    const response = await fetch(`${API_BASE}/generate-1click-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok || !response.body) {
      stopTimer();
      renderTracker(-1);
      const errBody = await response.json().catch(() => ({}));
      throw new Error(errBody.detail?.message || ("Request failed with status " + response.status));
    }

    // Read the SSE stream and update progress live
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result = null;

    const stageIndex = { serp: 0, brief: 1, draft: 2, seo: 3, validate: 4 };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line
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
          if (idx !== undefined) {
            updateStreamTracker(idx, data.status, data.message);
          }
        } else if (eventName === "result") {
          result = data;
        } else if (eventName === "error") {
          throw new Error(data.message || "Generation failed");
        }
      }
    }

    stopTimer();

    if (!result) {
      throw new Error("No result received from server");
    }

    renderTracker(STAGES.length);
    renderOutput(result);

  } catch (err) {
    stopTimer();
    renderTracker(-1);
    document.getElementById("output-body").innerHTML =
      '<div class="error-banner">Generation failed: ' + err.message + '</div>';
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate Article";
  }
});

function updateStreamTracker(activeIndex, status, message) {
  const tracker = document.getElementById("tracker");
  tracker.innerHTML = "";
  const stageName = STAGES[activeIndex];
  const isDone = status === "done";
  tracker.innerHTML =
    '<div class="step ' + (isDone ? "done" : "active") + '"><span class="dot"></span><span>' + stageName + '</span></div>' +
    (message ? '<div class="stream-msg">' + (isDone ? "✓ " : "⏳ ") + message + '</div>' : "");
}
