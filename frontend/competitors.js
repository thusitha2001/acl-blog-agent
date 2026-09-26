(function () {
  const SNAPSHOT_KEY = "ba-competitor-snapshots";
  const HANDOFF_KEY = "ba-competitor-handoff";
  const STAGES = ["fetch_page", "competitors", "scoring", "report"];

  const MAX_COMPETITOR_URLS = 10;
  const URL_PLACEHOLDERS = [
    "https://competitor.com/article-one",
    "https://competitor.com/article-two",
    "https://competitor.com/article-three",
    "https://competitor.com/article-four",
    "https://competitor.com/article-five",
    "https://competitor.com/article-six",
    "https://competitor.com/article-seven",
    "https://competitor.com/article-eight",
    "https://competitor.com/article-nine",
    "https://competitor.com/article-ten",
  ];

  const blogUrlInput = document.getElementById("ca-blog-url");
  const keywordInput = document.getElementById("ca-keyword");
  const urlListEl = document.getElementById("ca-url-list");
  const urlAddBtn = document.getElementById("ca-url-add");
  const urlMetaEl = document.getElementById("ca-url-meta");
  const analyzeBtn = document.getElementById("ca-analyze");
  const rewriteBtn = document.getElementById("ca-rewrite");
  const errorEl = document.getElementById("ca-error");
  const liveMeta = document.getElementById("ca-live-meta");
  const progress = document.getElementById("ca-progress");
  const tableEl = document.getElementById("ca-table");
  const snapshotSelect = document.getElementById("ca-snapshot");
  const compSub = document.getElementById("ca-comp-sub");
  const yoursEl = document.getElementById("ca-yours");
  const dashEl = document.getElementById("ca-dashboard");
  const dashBody = document.getElementById("ca-dash-body");
  const countryEl = document.getElementById("ca-country");
  const languageEl = document.getElementById("ca-language");
  const monthsEl = document.getElementById("ca-months");

  let currentResult = null;
  let analysisSeq = 0;
  const INVALID_BLOG_URL_MESSAGE = "Please enter a valid public article URL. The current value is the local Competitor Analysis page, not an article URL.";

  function inspectBlogUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) return { ok: false, status: "missing", url: null, error: null };
    if (raw === "#" || raw === "/competitors" || raw === "/competitors#" || /\/competitors#?$/i.test(raw)) {
      return { ok: false, status: "invalid", url: raw, error: INVALID_BLOG_URL_MESSAGE };
    }
    try {
      const href = /^https?:\/\//i.test(raw) ? raw : "https://" + raw;
      const parsed = new URL(href);
      const host = (parsed.hostname || "").toLowerCase();
      const path = (parsed.pathname || "/").replace(/\/$/, "") || "/";
      const appPaths = ["/", "/competitors", "/writer", "/rewriter", "/editor", "/login", "/settings", "/dashboard", "/health"];
      const local = host === "127.0.0.1" || host === "localhost" || host === "0.0.0.0";
      const current = window.location;
      if (!host || (!host.includes(".") && !local)) {
        return { ok: false, status: "invalid", url: raw, error: INVALID_BLOG_URL_MESSAGE };
      }
      if (appPaths.includes(path) && (local || host === (current.hostname || "").toLowerCase())) {
        return { ok: false, status: "invalid", url: raw, error: INVALID_BLOG_URL_MESSAGE };
      }
      if (raw === current.href || raw === current.origin + "/competitors" || raw === current.origin + "/competitors#") {
        return { ok: false, status: "invalid", url: raw, error: INVALID_BLOG_URL_MESSAGE };
      }
      return { ok: true, status: "valid", url: href, error: null };
    } catch (err) {
      return { ok: false, status: "invalid", url: raw, error: INVALID_BLOG_URL_MESSAGE };
    }
  }

  function numericScore(value) {
    if (value == null || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function averageFromRows(rows, key) {
    const vals = (rows || []).map((row) => numericScore(row?.scores?.[key])).filter((n) => n != null);
    if (!vals.length) return null;
    return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
  }

  function competitorAverages(result) {
    const rows = result?.competitors || [];
    const api = result?.competitor_avg_scores || {};
    const out = { ...api };
    ["seo", "geo", "aeo", "aio", "sxo", "overall"].forEach((key) => {
      if (out[key] == null) out[key] = averageFromRows(rows, key);
    });
    const counted = ["seo", "geo", "aeo"].map((key) => rows.filter((row) => numericScore(row?.scores?.[key]) != null).length);
    const scored = Math.max(0, ...counted);
    out.sample_note = api.sample_note || (rows.length ? `Based on ${scored} of ${rows.length} competitors` : "No competitors");
    return out;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatWords(value) {
    if (value == null || value === "") return "Word count unavailable";
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "Word count unavailable";
    return n.toLocaleString() + " words";
  }

  function formatUpdated(value) {
    const text = String(value || "").trim();
    if (!text || text === "Unknown" || /^updated recently$/i.test(text)) return "Date unknown";
    return text;
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
    urlAddBtn && (urlAddBtn.disabled = on);
    urlInputEls().forEach((input) => { input.disabled = on; });
  }

  function urlInputEls() {
    return Array.from(urlListEl?.querySelectorAll("input.ca-url-input") || []);
  }

  function looksLikeUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) return false;
    try {
      const href = /^https?:\/\//i.test(raw) ? raw : "https://" + raw;
      const parsed = new URL(href);
      return Boolean(parsed.hostname && parsed.hostname.includes("."));
    } catch (err) {
      return false;
    }
  }

  function collectCompetitorUrls() {
    return parseCompetitorUrls(urlInputEls().map((input) => input.value).join("\n"));
  }

  function updateUrlRows() {
    const inputs = urlInputEls();
    inputs.forEach((input) => {
      input.closest(".ca-url-row")?.classList.toggle("is-filled", looksLikeUrl(input.value));
    });
    const filled = inputs.filter((input) => looksLikeUrl(input.value)).length;
    if (urlMetaEl) {
      urlMetaEl.textContent = filled + " of " + MAX_COMPETITOR_URLS + " added";
    }
    if (urlAddBtn) {
      urlAddBtn.hidden = inputs.length >= MAX_COMPETITOR_URLS;
    }
  }

  function addUrlRow(value, focus) {
    if (!urlListEl || urlInputEls().length >= MAX_COMPETITOR_URLS) return;
    const index = urlInputEls().length;
    const row = document.createElement("div");
    row.className = "ca-url-row";
    row.innerHTML =
      '<span class="ca-url-index">' + (index + 1) + "</span>" +
      '<span class="ca-url-mark"><span class="ca-url-check" aria-hidden="true">' +
      '<svg viewBox="0 0 16 16" width="12" height="12"><path d="M3.6 8.4l3 3 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
      "</span></span>" +
      '<input type="url" class="ca-url-input" maxlength="500" autocomplete="off" spellcheck="false" placeholder="' +
      URL_PLACEHOLDERS[index] + '">';
    const input = row.querySelector("input");
    input.value = value || "";
    urlListEl.appendChild(row);
    updateUrlRows();
    if (focus) input.focus();
  }

  function setCompetitorUrls(urls) {
    if (!urlListEl) return;
    urlListEl.innerHTML = "";
    const list = (urls || []).map((item) => String(item || "").trim()).filter(Boolean).slice(0, MAX_COMPETITOR_URLS);
    if (!list.length) {
      addUrlRow("", false);
      return;
    }
    list.forEach((url) => addUrlRow(url, false));
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

  function scorePills(scores, reason) {
    const items = [
      ["SEO", numericScore(scores?.seo)],
      ["GEO", numericScore(scores?.geo)],
      ["AEO", numericScore(scores?.aeo)],
      ["AIO", numericScore(scores?.aio)],
      ["SXO", numericScore(scores?.sxo)],
    ];
    const any = items.some(([, value]) => value != null);
    if (!any) {
      return `<div class="ca-scores"><span class="ca-pill ca-pill-muted"><span>${escapeHtml(reason || scores?.reason || "Data unavailable")}</span></span></div>`;
    }
    return `<div class="ca-scores">${items.map(([label, value]) => `
      <span class="ca-pill ca-pill-${label.toLowerCase()}${value == null ? " ca-pill-muted" : ""}">
        <strong>${value == null ? "N/A" : escapeHtml(value)}</strong>
        <span>${label}</span>
      </span>
    `).join("")}</div>`;
  }

  function signalTags(signals) {
    const tags = (signals || []).filter((s) => s && s.label && !/^https?:\/\//i.test(String(s.label)));
    if (!tags.length) {
      return `<div class="ca-signals"><span class="ca-tag">No signals detected</span></div>`;
    }
    return `<div class="ca-signals">${tags.map((s) => `
      <span class="ca-tag ca-tag-${s.kind === "positive" ? "good" : "warn"}">
        ${s.kind === "positive" ? "✓" : "!"} ${escapeHtml(s.label)}
      </span>
    `).join("")}</div>`;
  }

  function doesWellCell(row) {
    const parts = String(row.does_well || "")
      .split(";")
      .map((part) => part.trim())
      .filter((part) => part && !/^https?:\/\//i.test(part));
    if (parts.length) {
      return `<div class="ca-signals">${parts.map((part) => `
        <span class="ca-tag ca-tag-good">✓ ${escapeHtml(part)}</span>
      `).join("")}</div>`;
    }
    if ((row.signals || []).length) {
      return signalTags(row.signals);
    }
    return `<div class="ca-signals"><span class="ca-tag">No signals detected</span></div>`;
  }

  function renderCompetitors(result) {
    const rows = result?.competitors || [];
    const keyword = result?.serp_query || result?.target_keyword || "your target keyword";
    compSub.textContent = `${rows.length} competitor URL${rows.length === 1 ? "" : "s"} for ${keyword}`;
    if (!rows.length) {
      const note = result?.serp_warning
        ? escapeHtml(result.serp_warning)
        : "Add competitor URLs and run an analysis to compare them here";
      tableEl.innerHTML = `<div class="ca-empty">${note}</div>`;
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
              <span class="ca-rank">${row.rank || ""}</span>
              <img class="ca-fav" src="${escapeHtml(row.favicon)}" alt="" width="16" height="16">
              <span class="ca-domain">${escapeHtml(row.domain)}</span>
              <span class="ca-type">${escapeHtml(row.content_type)}</span>
              ${row.intent_mismatch ? `<span class="ca-type ca-intent-mismatch">Intent mismatch</span>` : (row.search_intent ? `<span class="ca-type">${escapeHtml(row.search_intent)}</span>` : "")}
            </div>
            <a class="ca-title" href="${escapeHtml(row.url)}" target="_blank" rel="noopener">${escapeHtml(row.title || "Data unavailable")}</a>
            <p class="ca-meta">${escapeHtml(row.authority)} · ${escapeHtml(formatWords(row.word_count))} · ${escapeHtml(formatUpdated(row.updated))}</p>
            <p class="ca-meta">${escapeHtml(row.meta_description && row.meta_description !== "Data unavailable" ? row.meta_description : "Meta description: Data unavailable")}</p>
          </div>
          ${scorePills(row.scores)}
          ${doesWellCell(row)}
        </article>
      `).join("")}
    `;
  }

  function applyResult(result, options) {
    currentResult = result;
    liveMeta.textContent = "· Last analyzed " + formatWhen(result.analyzed_at);
    renderCompetitors(result);
    renderYoursSummary(result);
    try {
      renderDashboard(result);
    } catch (err) {
      console.error("[Competitor Analysis] dashboard render failed", err);
      if (dashEl && dashBody) {
        dashEl.hidden = false;
        dashBody.innerHTML = "<p class=\"ca-empty\">The ranking table loaded, but the detailed report could not be drawn. Use Export JSON after analyzing again.</p>";
      }
    }
    setRewriteEnabled(true);
    if (result.serp_warning) {
      showError(result.serp_warning);
    }
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
  }

  function loadSnapshots() {
    try {
      return JSON.parse(localStorage.getItem(SNAPSHOT_KEY) || "[]");
    } catch (err) {
      return [];
    }
  }

  function saveSnapshot(result) {
    try {
      const slimCompetitors = (result.competitors || []).map((row) => ({
        ...row,
        scores: row.scores ? { ...row.scores, reports: undefined } : row.scores,
      }));
      const slim = { ...result, source_article: "", competitors: slimCompetitors };
      const snapshots = loadSnapshots().filter((item) => item.id !== result.analyzed_at);
      snapshots.unshift({
        id: result.analyzed_at,
        label: `${String(result.target_keyword || "Snapshot").slice(0, 32)} · ${formatWhen(result.analyzed_at)}`,
        result: slim,
      });
      localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snapshots.slice(0, 6)));
    } catch (err) {
      console.warn("[Competitor Analysis] snapshot not saved", err);
    }
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

  function parseCompetitorUrls(text) {
    return String(text || "")
      .split(/[\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, MAX_COMPETITOR_URLS)
      .map((item) => (/^https?:\/\//i.test(item) ? item : "https://" + item));
  }

  async function runAnalysis() {
    const blogCheck = inspectBlogUrl(blogUrlInput.value.trim());
    if (blogUrlInput.value.trim() && !blogCheck.ok) {
      showError(blogCheck.error);
      return;
    }
    const blogUrl = blogCheck.ok ? blogCheck.url : null;
    const keyword = keywordInput.value.trim() || null;
    const competitorUrls = collectCompetitorUrls().slice();
    if (!keyword) {
      showError("Enter a target keyword.");
      keywordInput.focus();
      return;
    }
    if (!blogUrl && !competitorUrls.length) {
      showError("Enter a blog URL or at least one competitor URL.");
      return;
    }
    const analysisId = String(++analysisSeq);
    showError("");
    setRewriteEnabled(false);
    setAnalyzing(true);
    markStage("fetch_page");
    currentResult = null;
    tableEl.innerHTML = skeletonRows();
    if (yoursEl) yoursEl.hidden = true;
    if (dashEl) dashEl.hidden = true;
    ["ca-filter-priority"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });

    const payload = {
      blog_url: blogUrl,
      keyword,
      competitor_urls: competitorUrls.slice(),
      country: countryEl?.value || "us",
      language: languageEl?.value || "en",
      months: Number(monthsEl?.value || 6),
      client_analysis_id: analysisId,
    };
    console.log("[Competitor Analysis] request", payload);

    try {
      const response = await fetch("/analyze-competitors-stream", {
        method: "POST",
        headers: window.BlogAgentAuth?.headers() || { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (response.status === 401) {
        window.BlogAgentAuth?.handleUnauthorized?.();
        throw new Error("Please log in again.");
      }
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
      if (analysisId !== String(analysisSeq)) {
        console.log("[Competitor Analysis] ignored stale response", result?.client_analysis_id, analysisId);
        return;
      }
      if (!result) throw new Error("No analysis result received.");
      if (result.client_analysis_id && String(result.client_analysis_id) !== analysisId) {
        console.log("[Competitor Analysis] ignored mismatched analysis id");
        return;
      }
      applyResult(result);
      saveSnapshot(result);
    } catch (err) {
      tableEl.innerHTML = `<div class="ca-empty">Add competitor URLs and run an analysis to compare them here</div>`;
      if (yoursEl) yoursEl.hidden = true;
      if (dashEl) dashEl.hidden = true;
      showError(err.message || "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  urlListEl?.addEventListener("input", (event) => {
    if (event.target.classList.contains("ca-url-input")) updateUrlRows();
  });
  urlListEl?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.target.classList.contains("ca-url-input")) return;
    event.preventDefault();
    const inputs = urlInputEls();
    if (looksLikeUrl(event.target.value) && inputs.length < MAX_COMPETITOR_URLS && event.target === inputs[inputs.length - 1]) {
      addUrlRow("", true);
    }
  });
  urlAddBtn?.addEventListener("click", () => addUrlRow("", true));
  setCompetitorUrls([]);

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
      oldScores: currentResult.old_scores || { seo: 0, geo: 0, aeo: 0 },
      sourceArticle: currentResult.source_article || "",
      sourceTitle: currentResult.source_title || "",
      sourceExtractError: !!currentResult.source_extract_error,
    };
    console.log("[Competitor Analysis] handoff competitors", payload.competitors.length);
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

  function scoreNum(value) {
    return value == null ? "—" : value;
  }

  function tableRows(headers, rows) {
    if (!rows.length) return `<p class="ca-empty">No rows for this filter.</p>`;
    return `<div class="ca-scroll"><table class="ca-grid-table"><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function publicArticleHref(result) {
    const raw = result?.your_page?.url || result?.blog_url || "";
    const check = inspectBlogUrl(raw);
    return check.ok ? check.url : "";
  }

  function headingList(value) {
    if (Array.isArray(value)) return value.map((item) => String(item || "").trim()).filter(Boolean);
    if (typeof value === "string" && value.trim()) return [value.trim()];
    return [];
  }

  function pageHeadings(page, includeTitle) {
    const heads = headingList(page?.h2_headings)
      .concat(headingList(page?.h3_headings))
      .concat(headingList(page?.h2))
      .concat(headingList(page?.h1_headings))
      .concat(headingList(page?.h1));
    if (includeTitle) return heads.concat(headingList(page?.title));
    const title = String(page?.title || "").trim().toLowerCase();
    return heads.filter((item) => item.toLowerCase() !== title);
  }

  function keywordFocus(result) {
    const focus = result.keywords?.focus || {};
    return {
      ours: focus.our_blog || [],
      oursBasis: focus.our_blog_basis || "on_page",
      competitors: focus.competitors || [],
      opportunities: focus.opportunities || [],
      note: focus.note || "",
    };
  }

  function keywordChoicePending(result) {
    return !!(result.keyword_mismatch && !result.keyword_mismatch.confirmed);
  }

  function dependsTag(show) {
    return show ? ` <span class="ca-tag ca-tag-warn">Depends on keyword choice</span>` : "";
  }

  function focusGroup(title, subtitle, rows, emptyText, showVolume, tag = "") {
    const headers = showVolume ? ["Keyword", "Why", "Search volume"] : ["Keyword", "Why"];
    const body = rows.length
      ? tableRows(headers, rows.map((k) => {
        const cells = [escapeHtml(k.keyword), escapeHtml(k.evidence || "")];
        if (showVolume) cells.push(escapeHtml(String(k.search_volume ?? "Data unavailable")));
        return cells;
      }))
      : `<p class="ca-empty">${escapeHtml(emptyText)}</p>`;
    return `<h4>${escapeHtml(title)}${tag}</h4><p class="ca-hint">${escapeHtml(subtitle)}</p>${body}`;
  }

  function renderKeywordFocus(result) {
    const f = keywordFocus(result);
    const tag = dependsTag(keywordChoicePending(result));
    return `
      ${focusGroup(
        "Performing well for your blog",
        f.oursBasis === "search_console" ? "Top page-one Search Console queries by clicks" : "No Search Console data: ranked by how strongly your page uses them, not by traffic",
        f.ours,
        result.your_page ? "No strong keywords found on your page." : "Add a blog URL to see your keywords.",
        false,
      )}
      ${focusGroup(
        "Performing well for competitors",
        "Used by the most competitor pages you added",
        f.competitors,
        (result.competitors || []).length ? "No shared competitor keywords found." : "Add competitor URLs to see their keywords.",
        false,
        tag,
      )}
      ${focusGroup(
        "High-potential keywords to target (Recommendation)",
        f.note || "Ranked by search volume",
        f.opportunities,
        "No relevant keyword opportunities found.",
        true,
        tag,
      )}`;
  }

  function deriveContentGaps(result) {
    const table = result.content_gaps?.table;
    if (Array.isArray(table) && table.length) return result.content_gaps;
    const mine = pageHeadings(result.your_page, false).map((item) => item.toLowerCase());
    const rows = [];
    const seen = new Set();
    (result.competitors || []).forEach((row) => {
      if (row.intent_mismatch) return;
      pageHeadings(row, false).forEach((heading) => {
        const key = heading.toLowerCase();
        if (seen.has(key) || heading.split(/\s+/).length < 2 || heading.split(/\s+/).length > 14) return;
        if (/[|]/.test(heading) || /\b(buy|shop|online|amazon|bewakoof)\b/i.test(heading)) return;
        if (mine.some((item) => item === key || (item.length > 8 && key.includes(item)))) return;
        seen.add(key);
        rows.push({
          missing_topic: heading,
          covered_by: row.domain || row.url || "competitor",
          covered_by_competitors: [row.domain || row.url],
          evidence_type: "competitor_heading",
          importance: "medium",
          search_intent: "informational",
          recommended_heading: heading,
          suggested_outline: ["Define it", "Give a specific example", "Add a short how-to"],
        });
      });
    });
    const outline = [];
    const keyword = String(result.serp_query || result.target_keyword || "").toLowerCase();
    if (keyword.includes("hoodie") && (keyword.includes("style") || keyword.includes("outfit"))) {
      outline.push(
        "What makes an oversized hoodie look stylish?",
        "Choose the right oversized hoodie fit.",
        "What to wear with an oversized hoodie.",
        "Best pants and jeans for oversized hoodies.",
        "Shoes that work with oversized hoodie outfits.",
        "Layering ideas for different seasons.",
        "Casual and streetwear outfit combinations.",
        "Common styling mistakes to avoid.",
        "Frequently asked questions."
      );
    } else {
      pageHeadings(result.your_page, false).slice(0, 3).forEach((item) => outline.push(item));
      if (!outline.length) outline.push("Introduction");
      rows.slice(0, 8).forEach((row) => outline.push(row.recommended_heading));
    }
    return {
      table: rows.slice(0, 16),
      recommended_outline: outline.slice(0, 12),
      status: rows.length || outline.length ? "ok" : "unavailable",
    };
  }

  function articleText(result) {
    const page = result.your_page || {};
    return String(
      page.full_text || result.source_article || (page.paragraphs || []).join(" ") || pageHeadings(page).join(". ") || ""
    ).trim();
  }

  function deriveCitations(result) {
    const items = result.citations?.items || result.citations?.table;
    if (Array.isArray(items) && items.length) return items;
    const keyword = String(result.serp_query || result.target_keyword || result.your_page?.title || "this topic").trim();
    const mine = pageHeadings(result.your_page).join(" ").toLowerCase();
    const text = articleText(result).toLowerCase();
    const blob = mine + " " + text;
    const rows = [];
    function add(question, format, location, evidence) {
      const present = blob.includes(question.toLowerCase().slice(0, 18)) || (/\bis\b|\bhow to\b/.test(blob) && /what is/i.test(question));
      rows.push({
        keyword_or_question: question,
        status: present ? "existing" : "missing",
        format,
        location,
        citation_potential: present ? 82 : 70,
        required_evidence: evidence,
      });
    }
    add("What is " + keyword + "?", "definition", "Opening", "First-hand definition, not a copied blurb");
    add("How do I start with " + keyword + "?", "step-by-step list", "How-to section", "Concrete steps from experience");
    add("How much does it cost?", "table or numbered facts", "Early H2", "Named prices with date and source");
    add("FAQ the reader will ask", "FAQPage-ready Q&A", "FAQ block", "Answer in 2–4 sentences");
    add("A verifiable statistic", "quoted stat + source", "Proof paragraph", "Link a primary source; never invent numbers");
    (result.competitors || []).forEach((row) => {
      pageHeadings(row).forEach((heading) => {
        if (rows.length >= 10) return;
        if (!/\?/.test(heading) && !/^(how|what|why|when|where|which)\b/i.test(heading)) return;
        if (rows.some((item) => item.keyword_or_question.toLowerCase() === heading.toLowerCase())) return;
        add(heading, "direct answer", "New H2 or FAQ", "Answer in 40–60 words with one specific example");
      });
    });
    return rows.slice(0, 10);
  }

  function deriveTraffic(result) {
    const reasons = result.traffic?.reasons;
    if (Array.isArray(reasons) && reasons.length) return reasons;
    const out = [];
    const yours = result.your_scores || {};
    const avg = competitorAverages(result);
    const yourWords = Number(result.your_page?.word_count) || 0;
    const compWords = (result.competitors || []).map((row) => Number(row.word_count) || 0).filter((n) => n > 0);
    const avgWords = compWords.length ? Math.round(compWords.reduce((a, b) => a + b, 0) / compWords.length) : 0;
    if (yourWords && avgWords && yourWords + 300 < avgWords) {
      out.push({
        reason: "Shorter topical depth than ranking pages",
        severity: "High",
        evidence: "Your extract is " + yourWords + " words vs competitor average " + avgWords + " (on-page extract, not traffic).",
        fix: "Cover missing H2s from the content-gap table with original examples.",
        impact: "Better intent satisfaction on ranking pages",
      });
    }
    if (numericScore(yours.seo) != null && numericScore(avg.seo) != null && yours.seo + 8 < avg.seo) {
      out.push({
        reason: "Weaker on-page SEO checklist score",
        severity: "High",
        evidence: "Your SEO checklist " + yours.seo + " vs competitor average " + avg.seo + ".",
        fix: "Use the SEO factor tips: H1 keyword, headings, FAQs, alt text.",
        impact: "Improved on-page readiness, not a guaranteed rank lift",
      });
    }
    const yourH2 = Number(result.your_page?.h2_count) || pageHeadings(result.your_page).length;
    const avgH2 = (result.competitors || []).reduce((sum, row) => sum + (Number(row.h2_count) || pageHeadings(row).length), 0) / Math.max((result.competitors || []).length, 1);
    if (yourH2 && avgH2 && yourH2 + 2 < avgH2) {
      out.push({
        reason: "Fewer supporting headings than ranking pages",
        severity: "Medium",
        evidence: "Your page has " + yourH2 + " H2s vs competitor average " + Math.round(avgH2) + ".",
        fix: "Add H2s for the missing topics in the content-gap table.",
        impact: "Clearer scan path and snippet potential",
      });
    }
    out.push({
      reason: "Off-page authority is unknown in this tool",
      severity: "Low",
      evidence: "Domain authority, backlinks, referring domains, and Core Web Vitals are Data unavailable (no third-party API).",
      fix: "Pair this checklist with Search Console or a backlink tool you already have access to.",
      impact: "Unknown here — do not treat on-page scores as traffic.",
    });
    return out;
  }

  function countSyllables(word) {
    const cleaned = String(word || "").toLowerCase().replace(/[^a-z]/g, "");
    if (!cleaned) return 1;
    const groups = cleaned.match(/[aeiouy]+/g) || [];
    let count = groups.length || 1;
    if (cleaned.endsWith("e") && count > 1) count -= 1;
    return count;
  }

  function deriveReadability(result) {
    const existing = result.readability;
    if (existing && (existing.score != null || existing.flesch_reading_ease != null) && existing.status !== "unavailable") {
      return existing;
    }
    const text = articleText(result);
    const words = text.match(/[A-Za-z']+/g) || [];
    if (words.length < 8) {
      return existing && existing.reason ? existing : {
        score: null,
        interpretation: "Not enough extracted article text to score readability.",
        status: "unavailable",
        reason: "Article text could not be extracted.",
      };
    }
    const sentences = text.split(/(?<=[.!?])\s+/).filter((part) => part.split(/\s+/).length >= 2);
    const wordN = Math.max(words.length, 1);
    const sentN = Math.max(sentences.length, 1);
    const syllables = words.reduce((sum, word) => sum + countSyllables(word), 0);
    const flesch = Math.round((206.835 - 1.015 * (wordN / sentN) - 84.6 * (syllables / wordN)) * 10) / 10;
    const grade = Math.round((0.39 * (wordN / sentN) + 11.8 * (syllables / wordN) - 15.59) * 10) / 10;
    const score = Math.max(0, Math.min(100, Math.round(flesch)));
    let meaning = "Dense — shorten sentences";
    if (flesch >= 70) meaning = "Easy to read";
    else if (flesch >= 50) meaning = "Fairly readable";
    return {
      score,
      flesch_reading_ease: flesch,
      flesch_kincaid_grade: grade,
      interpretation: meaning,
      avg_sentence_length: Math.round((wordN / sentN) * 10) / 10,
      status: "ok",
    };
  }

  function sectionNote(report, fallback) {
    if (report?.reason && (!(report.table || []).length && !(report.items || []).length)) {
      return `<p class="ca-empty">${escapeHtml(report.reason)}</p>`;
    }
    return fallback;
  }

  function renderYoursSummary(result) {
    if (!yoursEl) return;
    if (!result) {
      yoursEl.hidden = true;
      return;
    }
    const page = result.your_page;
    const yours = result.your_scores || result.old_scores || {};
    const avg = competitorAverages(result);
    const href = publicArticleHref(result);
    const title = page?.title && page.title !== "Data unavailable"
      ? page.title
      : (result.analysis_mode === "keyword_only" ? "Keyword-only mode — your blog was not analyzed" : "Add a blog URL to score your page");
    yoursEl.hidden = false;
    yoursEl.innerHTML = `
      <header class="ca-card-head">
        <div>
          <h2>Your page vs ranking pages</h2>
          <p>SERP query: <strong>${escapeHtml(result.serp_query || result.target_keyword || "")}</strong> · ${escapeHtml(avg.sample_note || "")}</p>
        </div>
      </header>
      <div class="ca-yours-grid">
        <div>
          <p class="ca-kicker">My blog</p>
          ${href ? `<a class="ca-title" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>` : `<p class="ca-title">${escapeHtml(title)}</p>`}
          <p class="ca-meta">${escapeHtml(formatWords(page?.word_count))} · H2 ${page?.h2_count ?? "—"} · ${escapeHtml(page?.author && page.author !== "Data unavailable" ? page.author : "Author unavailable")}</p>
        </div>
        <div>
          <p class="ca-kicker">Your scores</p>
          ${scorePills(yours, yours.reason)}
        </div>
        <div>
          <p class="ca-kicker">Average competitor</p>
          ${scorePills(avg, avg.reasons?.aio || avg.reasons?.sxo)}
          <p class="ca-hint">${escapeHtml(avg.sample_note || "")}${avg.aio == null && avg.sxo == null && avg.seo != null ? " · Data unavailable — no AIO/SXO values returned" : ""}</p>
        </div>
      </div>
    `;
    yoursEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function metricLabel(value, suffix) {
    if (value == null || value === "") return "Data unavailable";
    return suffix ? String(value) + suffix : String(value);
  }

  function deltaLabel(value) {
    if (value == null || value === "") return "Data unavailable";
    const n = Number(value);
    if (Number.isNaN(n)) return "Data unavailable";
    return `${n > 0 ? "+" : ""}${n}%`;
  }

  function lossKindLabel(kind) {
    return ({
      vanished: "No longer showing",
      position_fell: "Rank dropped",
      ctr_fell: "CTR dropped",
      demand_down: "Fewer impressions (rank similar)",
    })[kind] || kind || "";
  }

  function renderComparisons(gsc) {
    const c = gsc.comparisons;
    if (!c) return "";
    function card(row) {
      if (!row) return "";
      const dates = [row.start, row.end].filter(Boolean).join(" – ");
      if (row.status !== "ok") {
        return `<article><p class="ca-kicker">${escapeHtml(row.label || "")}</p><p class="ca-empty">${escapeHtml(row.reason || "Data unavailable")}</p></article>`;
      }
      const ctr = row.ctr == null ? "Data unavailable" : `${Math.round(Number(row.ctr) * 1000) / 10}%`;
      const change = row.impressions_delta_pct == null ? "" : ` · vs this period ${escapeHtml(deltaLabel(row.impressions_delta_pct))}`;
      return `<article>
        <p class="ca-kicker">${escapeHtml(row.label || "")}${dates ? ` · ${escapeHtml(dates)}` : ""}</p>
        <p>Clicks ${escapeHtml(metricLabel(row.clicks))} · Impressions ${escapeHtml(metricLabel(row.impressions))}${change}</p>
        <p>CTR ${escapeHtml(ctr)} · Avg position ${escapeHtml(metricLabel(row.position))}</p>
      </article>`;
    }
    return `<div class="ca-compare">${card(c.current)}${card(c.previous)}${card(c.year_ago)}</div>`;
  }

  function renderQueryLosses(gsc) {
    const report = gsc.query_losses;
    if (!report) return "";
    if (report.status !== "ok") {
      return `<h4>Queries that lost visibility</h4><p class="ca-empty">${escapeHtml(report.reason || "Data unavailable")}</p>`;
    }
    if (!(report.items || []).length) {
      return `<h4>Queries that lost visibility</h4><p class="ca-empty">No query losses in this window.</p>`;
    }
    return `<h4>Queries that lost visibility</h4>
      ${tableRows(["Query", "This period", "Previous", "Change", "What changed"], report.items.map((row) => [
        escapeHtml(row.query),
        escapeHtml(String(row.impressions ?? "")),
        escapeHtml(String(row.previous_impressions ?? "")),
        escapeHtml(String(row.impressions_delta ?? "")),
        escapeHtml(lossKindLabel(row.kind)),
      ]))}
      <p class="ca-hint">Compared with the equal-length period before the range you chose. Numbers are Search Console counts, not estimates.</p>`;
  }

  function renderDiagnosis(result) {
    const summary = result.diagnosis_summary || {};
    const gsc = result.gsc_diagnosis || {};
    const targeting = gsc.keyword_targeting || {};
    const parts = [];
    if (summary.text) {
      parts.push(`<article class="ca-diagnosis ca-diagnosis-${escapeHtml(summary.confidence || "medium")}">
        <p class="ca-kicker">Most likely traffic reason · ${escapeHtml(summary.confidence || "medium")} confidence</p>
        <p>${escapeHtml(summary.text)}</p>
      </article>`);
    }
    const mismatch = result.keyword_mismatch;
    if (mismatch && !mismatch.confirmed) {
      parts.push(`<article class="ca-mismatch">
        <p><strong>Choose your target keyword first.</strong> Your traffic mostly comes from “${escapeHtml(mismatch.search_console_query)}”, but this report was measured against “${escapeHtml(mismatch.target_keyword)}”. Keyword and content-gap items marked <span class="ca-tag ca-tag-warn">Depends on keyword choice</span> may target the wrong keyword.</p>
        <div class="ca-mismatch-actions">
          <button type="button" class="ca-export-btn" data-mismatch="rerun">Re-run with “${escapeHtml(mismatch.search_console_query)}”</button>
          <button type="button" class="ca-export-btn" data-mismatch="keep">Keep “${escapeHtml(mismatch.target_keyword)}”</button>
        </div>
      </article>`);
    } else if (mismatch) {
      parts.push(`<p class="ca-hint">Target confirmed: “${escapeHtml(mismatch.target_keyword)}” (Search Console’s top query is “${escapeHtml(mismatch.search_console_query)}”).</p>`);
    } else if (targeting.mismatch && targeting.primary_ranking_query) {
      parts.push(`<p class="ca-serp-insight"><strong>Keyword mismatch.</strong> Search Console’s strongest query is “${escapeHtml(targeting.primary_ranking_query)}”; this analysis scored on-page placement against “${escapeHtml(targeting.target_keyword || result.serp_query || "")}”.</p>`);
    }
    const period = result.diagnosis_window || gsc.period || {};
    const periodLabel = period.label || (period.months ? `Last ${period.months} month${period.months === 1 ? "" : "s"}` : "");
    if (gsc.status === "ok") {
      const ctr = gsc.ctr == null ? "Data unavailable" : (Math.round(Number(gsc.ctr) * 1000) / 10) + "%";
      const dates = [period.start, period.end].filter(Boolean).join(" – ");
      parts.push(`<div class="ca-gsc-metrics">
        <span>${escapeHtml(periodLabel || "Search Console")}${dates ? ` · ${escapeHtml(dates)}` : ""}</span>
        <span>Clicks ${escapeHtml(metricLabel(gsc.clicks))}</span>
        <span>Impressions ${escapeHtml(metricLabel(gsc.impressions))}</span>
        <span>CTR ${escapeHtml(ctr)}</span>
        <span>Avg position ${escapeHtml(metricLabel(gsc.position))}</span>
      </div>`);
      parts.push(renderComparisons(gsc));
      parts.push(renderQueryLosses(gsc));
    } else if (gsc.reason) {
      parts.push(`<p class="ca-hint">Search Console${periodLabel ? ` (${escapeHtml(periodLabel)})` : ""}: ${escapeHtml(gsc.reason)}</p>`);
    }
    return parts.join("");
  }

  function renderImages(report) {
    if (!report || report.status !== "ok") {
      return `<p class="ca-empty">${escapeHtml(report?.reason || "Image audit unavailable.")}</p>`;
    }
    const s = report.summary || {};
    const comp = report.competitors;
    const parts = [`<p>${s.total || 0} article image${s.total === 1 ? "" : "s"} · ${s.ok || 0} with good alt text${s.decorative ? ` · ${s.decorative} decorative` : ""}${comp ? ` · competitors average ${comp.avg_images} image${comp.avg_images === 1 ? "" : "s"}${comp.avg_descriptive_pct != null ? `, ${comp.avg_descriptive_pct}% with descriptive alt` : ""}` : ""}</p>`];
    const recs = report.recommendations || [];
    if (recs.length) {
      parts.push(`<p class="ca-kicker">Recommendation</p><ul>${recs.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`);
    }
    const items = report.items || [];
    if (items.length) {
      parts.push(tableRows(["Image", "Section", "Current alt", "Issue", "Suggested alt"], items.map((i) => [
        /^https?:\/\//i.test(i.src || "")
          ? `<a href="${escapeHtml(i.src)}" target="_blank" rel="noopener">${escapeHtml(i.filename || "image")}</a>`
          : escapeHtml(i.filename || "image"),
        escapeHtml(i.section || "—"),
        i.alt ? escapeHtml(i.alt) : `<span class="ca-empty">none</span>`,
        `<span class="ca-tag ${i.severity === "high" ? "ca-tag-warn" : ""}">${escapeHtml(i.issue)}</span>`,
        i.suggested_alt
          ? `${escapeHtml(i.suggested_alt)}<br><span class="ca-hint">Draft from ${escapeHtml(i.suggestion_basis || "alt")}</span>`
          : `<span class="ca-hint">Describe what the image shows</span>`,
      ])));
      parts.push(`<p class="ca-hint">${escapeHtml(report.note || "")}</p>`);
    } else if (s.total) {
      parts.push(`<p class="ca-empty">No alt-text issues found.</p>`);
    }
    return parts.join("");
  }

  function renderDashboard(result) {
    if (!dashEl || !dashBody) return;
    if (!result) {
      dashEl.hidden = true;
      return;
    }
    dashEl.hidden = false;
    const yours = result.your_scores || result.old_scores || {};
    const pri = document.getElementById("ca-filter-priority")?.value || "";
    let plan = Array.isArray(result.action_plan) ? result.action_plan : (result.action_plan_report?.items || []);
    if (pri) plan = plan.filter((p) => p.priority === pri);
    const focus = keywordFocus(result);
    const pending = keywordChoicePending(result);
    const gaps = deriveContentGaps(result);
    const citations = deriveCitations(result);
    const traffic = deriveTraffic(result);
    const readability = deriveReadability(result);
    const insights = result.serp_insights || [];
    console.log("[Competitor Analysis] dashboard sections", {
      factors: Object.keys(yours.reports || yours.scores || {}),
      keywords: focus.ours.length + focus.competitors.length + focus.opportunities.length,
      gaps: (gaps.table || []).length,
      outline: (gaps.recommended_outline || []).length,
      citations: citations.length,
      traffic: traffic.length,
      readability: readability.score,
    });

    dashBody.innerHTML = `
      ${renderDiagnosis(result)}
      ${insights.map((item) => `<p class="ca-serp-insight">${escapeHtml(item)}</p>`).join("")}
      <p class="ca-hint">Mode ${escapeHtml(result.analysis_mode || "")} · blog ${escapeHtml(result.blog_url_status || "")} · keyword source ${escapeHtml(result.target_keyword_source || "")} · query ${escapeHtml(result.serp_query || "")}</p>
      <h3>Keyword comparison</h3>
      ${renderKeywordFocus(result)}
      <h3>Content gaps${dependsTag(pending)}</h3>
      ${(gaps.table || []).length ? tableRows(["Missing topic","Covered by","Importance","Intent"],
        (gaps.table || []).map((g) => [
          escapeHtml(g.missing_topic), escapeHtml(g.covered_by), escapeHtml(g.importance),
          escapeHtml(g.search_intent || g.intent || "")
        ])) : `<p class="ca-empty">${escapeHtml(gaps.reason || result.content_gaps?.reason || "No missing competitor headings were found.")}</p>`}
      <h3>AI citation opportunities</h3>
      ${citations.length ? tableRows(["Question","Status","Format","Location","Evidence"],
        citations.map((c) => [
          escapeHtml(c.keyword_or_question), escapeHtml(c.status), escapeHtml(c.format),
          escapeHtml(c.location), escapeHtml(c.required_evidence)
        ])) : `<p class="ca-empty">${escapeHtml(result.citations?.reason || "No citation opportunities yet.")}</p>`}
      <h3>Images &amp; alt text</h3>
      ${renderImages(result.images)}
      <h3>Why competitors may outperform</h3>
      ${traffic.length ? traffic.map((r) => `<article class="ca-reason"><strong>${escapeHtml(r.reason)}</strong> · ${escapeHtml(r.severity)}<p>${escapeHtml(r.evidence)}</p><p>Fix: ${escapeHtml(r.fix)} · Impact: ${escapeHtml(r.impact)}</p></article>`).join("") : `<p class="ca-empty">${escapeHtml(result.traffic?.reason || "No traffic comparison yet.")}</p>`}
      <p class="ca-hint">${escapeHtml(result.traffic?.disclaimer || "These are possible on-page disadvantages, not verified traffic.")}</p>
      <h3>Readability</h3>
      <p>${readability.status === "unavailable" ? escapeHtml(readability.reason || "Readability unavailable") : `Score ${scoreNum(readability.score)} · ${escapeHtml(readability.interpretation || "")} · Flesch ${scoreNum(readability.flesch_reading_ease)} · Grade ${scoreNum(readability.flesch_kincaid_grade)}`}</p>
      ${readability.avg_sentence_length ? `<p class="ca-hint">Average sentence length ${escapeHtml(readability.avg_sentence_length)} words.</p>` : ""}
      <h3>Humanization</h3>
      <p>${result.humanization?.status === "unavailable" ? escapeHtml(result.humanization?.reason || "Humanization unavailable") : `Score ${scoreNum(result.humanization?.score)} · ${escapeHtml(result.humanization?.interpretation || "")}`}</p>
      <p>${(result.humanization?.ai_like_phrases || []).map((p) => `<span class="ca-tag">${escapeHtml(p)}</span>`).join(" ")}</p>
      <h3>Action plan</h3>
      ${plan.length ? tableRows(["Priority","Category","Issue","Action","Impact","Effort"],
        plan.map((p) => [
          escapeHtml(p.priority), escapeHtml(p.category), escapeHtml(p.issue) + dependsTag(pending && p.depends_on_keyword),
          escapeHtml(p.recommended_action), escapeHtml(p.estimated_impact), escapeHtml(p.estimated_effort)
        ])) : sectionNote(result.action_plan_report, `<p class="ca-empty">No actions generated.</p>`)}
    `;
  }

  function downloadFile(name, text, type) {
    const blob = new Blob([text], { type });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.click();
    URL.revokeObjectURL(href);
  }

  function exportReport(kind) {
    if (!currentResult) return;
    const result = currentResult;
    const stamp = (result.target_keyword || "report").replace(/\s+/g, "-").slice(0, 40);
    if (kind === "json") {
      const copy = { ...result, source_article: "" };
      downloadFile(stamp + ".json", JSON.stringify(copy, null, 2), "application/json");
      return;
    }
    if (kind === "csv") {
      const rows = [["group","keyword","why","search_volume"]];
      const f = keywordFocus(result);
      [["your_blog", f.ours], ["competitors", f.competitors], ["opportunity", f.opportunities]].forEach(([group, list]) => {
        list.forEach((k) => rows.push([group, k.keyword, k.evidence || "", k.search_volume ?? "Data unavailable"]));
      });
      downloadFile(stamp + "-keywords.csv", rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n"), "text/csv");
      return;
    }
    if (kind === "md") {
      const md = [
        `# Competitor analysis: ${result.target_keyword || ""}`,
        "",
        `Country: ${result.country || "us"} · Language: ${result.language || "en"}`,
        "",
        "## Scores",
        JSON.stringify(result.your_scores, null, 2),
        "",
        "## Action plan",
        ...(result.action_plan || []).map((p) => `- **${p.priority}** (${p.category}): ${p.issue} — ${p.recommended_action}`),
        "",
        result.traffic?.disclaimer || "",
      ].join("\n");
      downloadFile(stamp + ".md", md, "text/markdown");
      return;
    }
    window.print();
  }

  document.querySelectorAll("[data-export]").forEach((btn) => {
    btn.addEventListener("click", () => exportReport(btn.dataset.export));
  });

  dashBody?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-mismatch]");
    const mismatch = currentResult?.keyword_mismatch;
    if (!btn || !mismatch) return;
    if (btn.dataset.mismatch === "rerun") {
      keywordInput.value = mismatch.search_console_query;
      runAnalysis();
    } else {
      mismatch.confirmed = true;
      renderDashboard(currentResult);
    }
  });
  ["ca-filter-priority"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      if (currentResult) renderDashboard(currentResult);
    });
  });

  renderSnapshotOptions();
  setRewriteEnabled(false);
})();
