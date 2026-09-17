(function () {
  const SNAPSHOT_KEY = "ba-competitor-snapshots";
  const HANDOFF_KEY = "ba-competitor-handoff";
  const STAGES = ["fetch_page", "serp", "competitors", "scoring"];

  const blogUrlInput = document.getElementById("ca-blog-url");
  const keywordInput = document.getElementById("ca-keyword");
  const analyzeBtn = document.getElementById("ca-analyze");
  const rewriteBtn = document.getElementById("ca-rewrite");
  const errorEl = document.getElementById("ca-error");
  const liveMeta = document.getElementById("ca-live-meta");
  const progress = document.getElementById("ca-progress");
  const tableEl = document.getElementById("ca-table");
  const intentBody = document.getElementById("ca-intent-body");
  const compareBody = document.getElementById("ca-compare-body");
  const gapsBody = document.getElementById("ca-gaps-body");
  const paaBody = document.getElementById("ca-paa-body");
  const structureBody = document.getElementById("ca-structure-body");
  const snapshotSelect = document.getElementById("ca-snapshot");
  const fullCompareBtn = document.getElementById("ca-full-compare");
  const intentHeading = document.getElementById("ca-intent-heading");
  const compSub = document.getElementById("ca-comp-sub");

  let currentResult = null;
  let compareExpanded = false;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatWords(value) {
    const n = Number(value) || 0;
    return n.toLocaleString() + " words";
  }

  function formatWhen(iso) {
    if (!iso) return "--";
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return "--";
    return dt.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function showError(message) {
    errorEl.hidden = !message;
    errorEl.textContent = message || "";
  }

  function setRewriteEnabled(on) {
    rewriteBtn.disabled = !on;
  }

  function setAnalyzing(on) {
    analyzeBtn.disabled = on;
    analyzeBtn.textContent = on ? "Analyzing…" : "Analyze →";
    progress.hidden = !on;
  }

  function markStage(stage) {
    document.querySelectorAll("#ca-progress-track [data-stage]").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.stage === stage);
      const idx = STAGES.indexOf(el.dataset.stage);
      const current = STAGES.indexOf(stage);
      el.classList.toggle("is-done", idx >= 0 && idx < current);
    });
  }

  function skeletonRows() {
    return Array.from({ length: 5 }, () => `
      <div class="ca-row ca-skel">
        <div class="ca-skel-line wide"></div>
        <div class="ca-skel-line"></div>
        <div class="ca-skel-line short"></div>
      </div>
    `).join("");
  }

  function scorePills(scores) {
    const items = [
      ["SEO", scores?.seo],
      ["GEO", scores?.geo],
      ["AEO", scores?.aeo],
    ];
    return `<div class="ca-scores">${items.map(([label, value]) => `
      <span class="ca-pill ca-pill-${label.toLowerCase()}">
        <strong>${escapeHtml(value ?? "—")}</strong>
        <span>${label}</span>
      </span>
    `).join("")}</div>`;
  }

  function signalTags(signals) {
    return `<div class="ca-signals">${(signals || []).map((s) => `
      <span class="ca-tag ca-tag-${s.kind === "positive" ? "good" : "warn"}">
        ${s.kind === "positive" ? "✓" : "!"} ${escapeHtml(s.label)}
      </span>
    `).join("")}</div>`;
  }

  function renderCompetitors(result) {
    const rows = result?.competitors || [];
    const keyword = result?.target_keyword || "your target keyword";
    compSub.textContent = `Top pages for ${keyword}`;
    if (!rows.length) {
      tableEl.innerHTML = `<div class="ca-empty">Run an analysis to see ranking competitors here</div>`;
      return;
    }
    tableEl.innerHTML = `
      <div class="ca-cols">
        <span>Page and content signals</span>
        <span>Scores</span>
        <span>Opportunity signals</span>
      </div>
      ${rows.map((row) => `
        <article class="ca-row">
          <div class="ca-page">
            <div class="ca-page-top">
              <img class="ca-fav" src="${escapeHtml(row.favicon)}" alt="" width="16" height="16">
              <span class="ca-domain">${escapeHtml(row.domain)}</span>
              <span class="ca-type">${escapeHtml(row.content_type)}</span>
            </div>
            <a class="ca-title" href="${escapeHtml(row.url)}" target="_blank" rel="noopener">${escapeHtml(row.title)}</a>
            <p class="ca-meta">${escapeHtml(row.authority)} · ${escapeHtml(formatWords(row.word_count))} · ${escapeHtml(row.updated)}</p>
          </div>
          ${scorePills(row.scores)}
          ${signalTags(row.signals)}
        </article>
      `).join("")}
    `;
  }

  function intentBar(label, color, yours, theirs) {
    const y = Number(yours) || 0;
    const t = Number(theirs) || 0;
    return `
      <div class="ca-intent-row">
        <span class="ca-intent-dot" style="background:${color}"></span>
        <span class="ca-intent-name">${escapeHtml(label)}</span>
        <span class="ca-intent-pcts"><strong>${y}%</strong><span>${t}%</span></span>
        <div class="ca-intent-bars" aria-hidden="true">
          <i style="width:${y}%;background:${color}"></i>
          <i style="width:${t}%;background:${color};opacity:.35"></i>
        </div>
      </div>
    `;
  }

  function renderIntent(result) {
    const intent = result?.intent;
    if (!intent) {
      intentHeading.textContent = "Readers are comparing";
      intentBody.innerHTML = `<div class="ca-empty">Search intent will appear here after analysis</div>`;
      return;
    }
    intentHeading.textContent = intent.heading || "Readers are comparing";
    const yours = intent.your || {};
    const avg = intent.competitor_avg || {};
    intentBody.innerHTML = `
      ${intentBar("Commercial investigation", "#6d4dff", yours.commercial, avg.commercial)}
      ${intentBar("Informational", "#22c55e", yours.informational, avg.informational)}
      ${intentBar("Navigational", "#f59e0b", yours.navigational, avg.navigational)}
      <div class="ca-cue">
        <strong>Writing cue</strong>
        <p>${escapeHtml(intent.cue || "")}</p>
      </div>
    `;
  }

  function dash(value) {
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  function comparisonRows(result, expanded) {
    const yours = result?.comparison?.your_blog || {};
    const best = result?.comparison?.best_competitor || {};
    const rows = [
      ["SEO Score", yours.seo, best.seo],
      ["GEO Score", yours.geo, best.geo],
      ["AEO Score", yours.aeo, best.aeo],
      ["Primary Keyword", yours.primary_keyword, best.primary_keyword],
      ["H1 Count", yours.h1_count, best.h1_count],
      ["H2 Count", yours.h2_count, best.h2_count],
      ["Word Count", yours.word_count, best.word_count],
    ];
    if (expanded) {
      rows.push(
        ["Pages analyzed", result?.your_page ? 1 : 0, (result?.competitors || []).length],
        ["Related queries", (result?.serp?.related_queries || []).length, (result?.serp?.related_queries || []).length],
      );
    }
    return rows.map(([label, a, b]) => `
      <div class="ca-compare-row">
        <span>${escapeHtml(label)}</span>
        <span><small>Your Blog</small><strong>${escapeHtml(dash(a))}</strong></span>
        <span><small>Best Competitor</small><strong>${escapeHtml(dash(b))}</strong></span>
      </div>
    `).join("");
  }

  function renderComparison(result) {
    if (!result) {
      compareBody.innerHTML = `<div class="ca-empty">Enter your blog URL above to see how it compares</div>`;
      fullCompareBtn.hidden = true;
      return;
    }
    if (!result.your_page) {
      compareBody.innerHTML = `<div class="ca-empty">Enter your blog URL above to see how it compares</div>`;
      fullCompareBtn.hidden = true;
      return;
    }
    compareBody.innerHTML = comparisonRows(result, compareExpanded);
    fullCompareBtn.hidden = false;
    fullCompareBtn.textContent = compareExpanded ? "Hide extra metrics ↑" : "View full comparison →";
  }

  function renderGapGroup(title, gaps) {
    if (!gaps.length) return "";
    return `
      <div class="ca-gap-group">
        <p class="ca-mini-label">${escapeHtml(title)}</p>
        ${gaps.map((gap) => `
          <div class="ca-gap">
            <span class="ca-gap-dot ${escapeHtml(gap.severity || "low")}" aria-hidden="true"></span>
            <div>
              <strong>${escapeHtml(gap.title)}</strong>
              <p>${escapeHtml(gap.description)}</p>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderGaps(result) {
    const keywordGaps = result?.keyword_gaps || [];
    const topicalGaps = result?.topical_gaps || [];
    const entityGaps = result?.entity_gaps || [];
    const flat = result?.gaps || [];
    const html = [
      renderGapGroup("Keyword gaps", keywordGaps),
      renderGapGroup("Topical gaps", topicalGaps),
      renderGapGroup("Entity gaps", entityGaps),
    ].join("");
    if (html.trim()) {
      gapsBody.innerHTML = html;
      return;
    }
    if (!flat.length) {
      gapsBody.innerHTML = `<div class="ca-empty">Gaps will appear here after analysis</div>`;
      return;
    }
    gapsBody.innerHTML = renderGapGroup("Content gaps", flat);
  }

  function renderPaa(result) {
    const items = result?.paa_opportunities || [];
    if (!items.length) {
      paaBody.innerHTML = `<div class="ca-empty">No question-style related queries in this SERP</div>`;
      return;
    }
    paaBody.innerHTML = items.map((item) => `
      <div class="ca-paa">
        <span>${escapeHtml(item.query)}</span>
        <span class="ca-badge ${item.answered ? "ca-badge-keep" : "ca-badge-add"}">
          ${item.answered ? "Answered" : "Unanswered"}
        </span>
      </div>
    `).join("");
  }

  function renderStructure(result) {
    const items = result?.recommended_structure || [];
    if (!items.length) {
      structureBody.innerHTML = `<div class="ca-empty">A suggested outline will appear here after analysis</div>`;
      return;
    }
    structureBody.innerHTML = items.map((item) => `
      <div class="ca-structure">
        <span>${escapeHtml(item.heading)}</span>
        <span class="ca-badge ${item.status === "keep" ? "ca-badge-keep" : "ca-badge-add"}">
          ${escapeHtml((item.status || "add").toUpperCase())}
        </span>
      </div>
    `).join("");
  }

  function applyResult(result) {
    currentResult = result;
    liveMeta.textContent = "· Last analyzed " + formatWhen(result.analyzed_at);
    if (result.target_keyword && !keywordInput.value.trim()) {
      keywordInput.value = result.target_keyword;
    }
    renderCompetitors(result);
    renderIntent(result);
    renderComparison(result);
    renderGaps(result);
    renderPaa(result);
    renderStructure(result);
    setRewriteEnabled(true);
    const yours = result.your_page || {};
    console.log("[Competitor Analysis] Your H1s", yours.h1_count, yours.h1_headings || []);
    console.log("[Competitor Analysis] Your H2s", yours.h2_count, yours.h2_headings || []);
    (result.competitors || []).forEach((row) => {
      console.log(
        "[Competitor Analysis] Competitor headings",
        row.domain,
        { h1: row.h1_count, h1s: row.h1_headings || [], h2: row.h2_count, h2s: row.h2_headings || [] }
      );
    });
    console.log("[Competitor Analysis] Gaps", result.gaps || []);
  }

  function loadSnapshots() {
    try {
      return JSON.parse(localStorage.getItem(SNAPSHOT_KEY) || "[]");
    } catch (err) {
      return [];
    }
  }

  function saveSnapshot(result) {
    const slim = { ...result, source_article: "" };
    const snapshots = loadSnapshots().filter((item) => item.id !== result.analyzed_at);
    snapshots.unshift({
      id: result.analyzed_at,
      label: `${String(result.target_keyword || "Snapshot").slice(0, 32)} · ${formatWhen(result.analyzed_at)}`,
      result: slim,
    });
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snapshots.slice(0, 6)));
    renderSnapshotOptions(result.analyzed_at);
  }

  function renderSnapshotOptions(selectedId) {
    const snapshots = loadSnapshots();
    const options = [`<option value="current">Recent snapshot</option>`];
    snapshots.forEach((item) => {
      options.push(`<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`);
    });
    snapshotSelect.innerHTML = options.join("");
    snapshotSelect.value = selectedId && snapshots.some((s) => s.id === selectedId)
      ? selectedId
      : "current";
  }

  async function consumeSse(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result = null;
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
        try { data = JSON.parse(dataStr); } catch (err) { continue; }
        if (eventName === "stage") markStage(data.stage);
        else if (eventName === "result") result = data;
        else if (eventName === "error") throw new Error(data.message || "Analysis failed");
      }
    }
    return result;
  }

  async function runAnalysis() {
    const blogUrl = blogUrlInput.value.trim();
    const keyword = keywordInput.value.trim();
    if (!blogUrl && !keyword) {
      showError("Enter a blog URL or a target keyword.");
      return;
    }
    showError("");
    setRewriteEnabled(false);
    setAnalyzing(true);
    markStage("fetch_page");
    tableEl.innerHTML = skeletonRows();
    intentBody.innerHTML = `<div class="ca-empty">Search intent will appear here after analysis</div>`;
    compareBody.innerHTML = `<div class="ca-empty">Enter your blog URL above to see how it compares</div>`;
    gapsBody.innerHTML = `<div class="ca-empty">Gaps will appear here after analysis</div>`;
    if (paaBody) paaBody.innerHTML = `<div class="ca-empty">Question queries will appear here after analysis</div>`;
    if (structureBody) structureBody.innerHTML = `<div class="ca-empty">A suggested outline will appear here after analysis</div>`;
    fullCompareBtn.hidden = true;
    compareExpanded = false;

    try {
      const response = await fetch("/analyze-competitors-stream", {
        method: "POST",
        headers: window.BlogAgentAuth?.headers() || { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_url: blogUrl || null,
          keyword: keyword || null,
        }),
      });
      if (!response.ok || !response.body) {
        const errBody = await response.json().catch(() => ({}));
        const detail = errBody.detail;
        const message = (typeof detail === "string" && detail)
          || detail?.message
          || (Array.isArray(detail) && detail[0]?.msg)
          || ("Request failed with status " + response.status);
        throw new Error(message);
      }
      const result = await consumeSse(response);
      if (!result) throw new Error("No analysis result received.");
      applyResult(result);
      saveSnapshot(result);
    } catch (err) {
      tableEl.innerHTML = `<div class="ca-empty">Run an analysis to see ranking competitors here</div>`;
      showError(err.message || "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  analyzeBtn?.addEventListener("click", runAnalysis);
  [blogUrlInput, keywordInput].forEach((input) => {
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        runAnalysis();
      }
    });
  });

  rewriteBtn?.addEventListener("click", () => {
    if (!currentResult || rewriteBtn.disabled) return;
    const payload = {
      blogUrl: currentResult.blog_url || blogUrlInput.value.trim(),
      targetKeyword: currentResult.target_keyword || keywordInput.value.trim(),
      competitors: (currentResult.competitors || []).map((row) => ({
        url: row.url,
        domain: row.domain,
        title: row.title,
        content_type: row.content_type,
        scores: row.scores,
      })),
      gaps: (currentResult.gaps || []).map((gap) => ({
        title: gap.title,
        description: gap.description,
        severity: gap.severity,
      })),
      keywordGaps: currentResult.keyword_gaps || [],
      topicalGaps: currentResult.topical_gaps || [],
      entityGaps: currentResult.entity_gaps || [],
      paaOpportunities: currentResult.paa_opportunities || [],
      oldScores: currentResult.old_scores || { seo: 0, geo: 0, aeo: 0 },
      sourceArticle: currentResult.source_article || "",
      sourceTitle: currentResult.source_title || "",
      sourceExtractError: !!currentResult.source_extract_error,
    };
    console.log("[Competitor Analysis] handoff competitors", payload.competitors.length, payload.gaps);
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify(payload));
    sessionStorage.setItem("ba-competitor-handoff-pending", "1");
    window.location.href = "/rewriter";
  });

  snapshotSelect?.addEventListener("change", () => {
    const id = snapshotSelect.value;
    if (id === "current") {
      if (currentResult) applyResult(currentResult);
      return;
    }
    const match = loadSnapshots().find((item) => item.id === id);
    if (match?.result) applyResult(match.result);
  });

  fullCompareBtn?.addEventListener("click", () => {
    compareExpanded = !compareExpanded;
    if (currentResult) renderComparison(currentResult);
  });

  renderSnapshotOptions();
  setRewriteEnabled(false);
})();
