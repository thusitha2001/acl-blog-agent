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
    const fallback = scores?.status === "ok" && scores?.confidence === "low";
    const split = (scores?.keyword_targeting_score != null || scores?.onpage_technical_score != null)
      ? `<p class="ca-hint">Keyword targeting ${escapeHtml(String(scores.keyword_targeting_score ?? "N/A"))} · On-page technical ${escapeHtml(String(scores.onpage_technical_score ?? "N/A"))}</p>`
      : "";
    const pills = items.map(([label, value]) => {
      const key = label.toLowerCase();
      const factors = scores?.reports?.[key]?.factors || [];
      return `<button type="button" class="ca-pill ca-pill-${key}${value == null ? " ca-pill-muted" : ""}" data-score-toggle="${key}" ${factors.length ? "" : "disabled"} aria-expanded="false">
        <strong>${value == null ? "N/A" : escapeHtml(value)}</strong>
        <span>${label}${factors.length ? " ▾" : ""}</span>
      </button>`;
    }).join("");
    const panels = items.map(([label]) => {
      const key = label.toLowerCase();
      const factors = scores?.reports?.[key]?.factors || [];
      if (!factors.length) return "";
      return `<div class="ca-factors" data-factors="${key}" hidden>
        ${factors.map((factor) => `
          <p><strong>${escapeHtml(factor.name || "")}</strong> ${escapeHtml(String(factor.score ?? "—"))}/${escapeHtml(String(factor.max ?? ""))}
          ${factor.note ? `<span class="ca-hint"> — ${escapeHtml(factor.note)}</span>` : ""}
          ${!factor.passed && factor.tip ? `<br><span class="ca-hint">${escapeHtml(factor.tip)}</span>` : ""}</p>
        `).join("")}
      </div>`;
    }).join("");
    return `<div class="ca-scores">${pills}${fallback ? `<span class="ca-tag ca-tag-warn">⚠ fallback scorer used</span>` : ""}${panels}</div>${split}`;
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
            ${row.vs_you ? `<p class="ca-vs-you">${escapeHtml(row.vs_you)}</p>` : ""}
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
        dashBody.innerHTML = "<p class=\"ca-empty\">The ranking table loaded, but the detailed report could not be drawn. Re-run the analysis.</p>";
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
        scores: row.scores || {},
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
    const close = focus.close_to_ranking || [];
    const topics = focus.new_topics || [];
    return {
      ours: focus.our_blog || [],
      oursBasis: focus.our_blog_basis || "on_page",
      competitors: focus.competitors || [],
      closeToRanking: close,
      closeNote: focus.close_to_ranking_note || "",
      newTopics: topics,
      newTopicsNote: focus.new_topics_note || "",
      opportunities: close.length || topics.length ? close.concat(topics) : (focus.opportunities || []),
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
    const headers = showVolume ? ["Keyword", "Notes", "Search volume"] : ["Keyword", "Notes"];
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
        "Topics competitors cover",
        "Used by the most competitor pages you added",
        f.competitors,
        (result.competitors || []).length ? "No shared competitor keywords found." : "Add competitor URLs to see their keywords.",
        false,
        tag,
      )}
      ${focusGroup(
        "Close to ranking (Recommendation)",
        f.closeNote || "Queries you already get impressions for but rank below position 10.",
        f.closeToRanking,
        "No striking-distance Search Console queries found.",
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
    pageHeadings(result.your_page, false).slice(0, 3).forEach((item) => outline.push(item));
    if (!outline.length) outline.push("Introduction");
    rows.slice(0, 8).forEach((row) => outline.push(row.recommended_heading));
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
        note: "Better intent satisfaction on ranking pages",
      });
    }
    if (numericScore(yours.seo) != null && numericScore(avg.seo) != null && yours.seo + 8 < avg.seo) {
      out.push({
        reason: "Weaker on-page SEO checklist score",
        severity: "High",
        evidence: "Your SEO checklist " + yours.seo + " vs competitor average " + avg.seo + ".",
        fix: "Use the SEO factor tips: H1 keyword, headings, FAQs, alt text.",
        note: "Improved on-page readiness, not a guaranteed rank lift",
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
        note: "Clearer scan path and snippet potential",
      });
    }
    out.push({
      reason: "Off-page authority is unknown in this tool",
      severity: "Low",
      evidence: "Domain authority, backlinks, referring domains, and Core Web Vitals are Data unavailable (no third-party API).",
      fix: "Pair this checklist with Search Console or a backlink tool you already have access to.",
      note: "Unknown here — do not treat on-page scores as traffic.",
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
          <h2>Your page</h2>
          <p>${escapeHtml(result.serp_query || result.target_keyword || "")} · ${escapeHtml(formatWords(page?.word_count))} · ${escapeHtml(String(page?.h2_count ?? "—"))} H2s</p>
        </div>
      </header>
      <div class="ca-yours-grid">
        <div>
          ${href ? `<a class="ca-title" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>` : `<p class="ca-title">${escapeHtml(title)}</p>`}
        </div>
        <div>
          <p class="ca-kicker">On-page scores</p>
          ${scorePills(yours, yours.reason)}
        </div>
        ${(result.competitors || []).length ? `<div>
          <p class="ca-kicker">Competitor average</p>
          ${scorePills(avg, avg.reasons?.aio || avg.reasons?.sxo)}
        </div>` : ""}
      </div>
    `;
    (dashEl || yoursEl).scrollIntoView({ behavior: "smooth", block: "start" });
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

  function renderQueryOpportunities(report) {
    if (!report) return "";
    const block = (title, rows) => `<h5>${escapeHtml(title)}</h5>${
      (rows || []).length
        ? tableRows(["Query", "Position", "Impressions"], rows.map((row) => [
          escapeHtml(row.query || ""),
          escapeHtml(String(row.position ?? "")),
          escapeHtml(String(row.impressions ?? "Data unavailable")),
        ]))
        : `<p class="ca-empty">None in this band.</p>`
    }`;
    return `${block("Quick wins (position 4–10)", report.quick_wins)}
      ${block("Page-two opportunities (11–20)", report.page_two)}
      ${block("Content opportunities (21–50)", report.content)}
      <p class="ca-hint">${escapeHtml(report.note || "Current Search Console positions, not a traffic forecast.")}</p>`;
  }

  function renderCtrChecklist(report) {
    if (!report || report.status === "unavailable") return "";
    if (report.status !== "gap") {
      return report.observed ? `<h5>CTR</h5><p>${escapeHtml(report.observed)}</p><p class="ca-hint">${escapeHtml(report.note || "")}</p>` : "";
    }
    return `<h5>CTR checklist</h5>
      <p>${escapeHtml(report.observed || "")}</p>
      <ul>${(report.possible_checks || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      <p class="ca-hint">${escapeHtml(report.note || "")}</p>`;
  }

  function renderCopyDraft(block, label) {
    if (!block || !block.recommended) return "";
    return `<div class="ca-llm-draft">
      <p class="ca-kicker">${escapeHtml(label)}</p>
      <p class="ca-hint">Now: ${escapeHtml(block.current || "—")}</p>
      <p><strong>${escapeHtml(block.recommended)}</strong></p>
    </div>`;
  }

  function renderLlmAdvice(advice) {
    if (!advice) return "";
    if (advice.status !== "ok") {
      return advice.reason
        ? `<p class="ca-hint">Recommendation model unavailable: ${escapeHtml(advice.reason)}</p>`
        : "";
    }
    const steps = advice.next_steps || [];
    return `<article class="ca-llm-advice">
      <p class="ca-kicker">Recommendation</p>
      ${advice.editor_summary ? `<p>${escapeHtml(advice.editor_summary)}</p>` : ""}
      <div class="ca-llm-drafts">
        ${renderCopyDraft(advice.title, "Title")}
        ${renderCopyDraft(advice.h1, "H1")}
        ${renderCopyDraft(advice.meta_description, "Meta")}
      </div>
      ${steps.length ? `<ol>${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>` : ""}
    </article>`;
  }

  function renderIndexStatus(result) {
    const report = result?.index_status || result?.gsc_diagnosis?.index_status;
    if (!report) return "";
    const tone = report.indexed === true ? "good" : report.indexed === false ? "warn" : "";
    const sourceLabel = report.source === "url_inspection"
      ? "URL Inspection"
      : report.source === "robots_only"
        ? "Robots only"
        : "Not verified";
    const bits = [];
    if (report.coverage_state) bits.push(`Coverage: ${report.coverage_state}`);
    if (report.last_crawl) bits.push(`Last crawl: ${report.last_crawl}`);
    if (report.indexing_state) bits.push(`Indexing state: ${report.indexing_state}`);
    return `<article class="ca-index-status${tone ? ` ca-index-${tone}` : ""}">
      <p class="ca-kicker">Google index</p>
      <p><strong>${escapeHtml(report.label || "Inspection unavailable")}</strong>
        <span class="ca-tag${tone ? ` ca-tag-${tone}` : ""}">${escapeHtml(sourceLabel)}</span></p>
      ${bits.length ? `<p class="ca-hint">${escapeHtml(bits.join(" · "))}</p>` : ""}
      <p class="ca-hint">${escapeHtml(report.note || "")}</p>
      ${report.impressions_hint ? `<p class="ca-hint">${escapeHtml(report.impressions_hint)}</p>` : ""}
    </article>`;
  }

  function renderDiagnosis(result) {
    const gsc = result.gsc_diagnosis || {};
    const parts = [renderIndexStatus(result)];
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
    const plan = Array.isArray(result.action_plan) ? result.action_plan : (result.action_plan_report?.items || []);
    const focus = keywordFocus(result);
    const pending = keywordChoicePending(result);
    const gaps = deriveContentGaps(result);
    const citations = deriveCitations(result);
    const traffic = deriveTraffic(result);
    const readability = deriveReadability(result);
    const insights = result.serp_insights || [];
    console.log("[Competitor Analysis] dashboard sections", {
      factors: Object.keys(yours.reports || yours.scores || {}),
      keywords: focus.ours.length + focus.competitors.length + focus.closeToRanking.length + focus.newTopics.length,
      gaps: (gaps.table || []).length,
      outline: (gaps.recommended_outline || []).length,
      citations: citations.length,
      traffic: traffic.length,
      readability: readability.score,
    });

    const verdict = result.verdict || {};
    const gsc = result.gsc_diagnosis || {};
    const period = result.diagnosis_window || gsc.period || {};
    const addRows = (result.what_to_add && result.what_to_add.table) || [];
    const topPlan = plan.slice(0, 6);
    const morePlan = plan.slice(6);
    const fixList = (rows) => rows.length
      ? `<ol class="ca-fix-list">${rows.map((p) => `
          <li>
            <span class="ca-fix-cat">${escapeHtml(p.category || "Fix")}</span>
            <p>${escapeHtml(p.recommended_action || p.issue || "")}${dependsTag(pending && p.depends_on_keyword)}</p>
          </li>`).join("")}</ol>`
      : "";
    const mismatchBlock = (() => {
      const mismatch = result.keyword_mismatch;
      const targeting = (result.gsc_diagnosis || {}).keyword_targeting || {};
      if (mismatch && !mismatch.confirmed) {
        return `<article class="ca-mismatch">
          <p><strong>Choose your target keyword first.</strong> Your traffic mostly comes from “${escapeHtml(mismatch.search_console_query)}”, but this report was measured against “${escapeHtml(mismatch.target_keyword)}”. Keyword and content-gap items marked <span class="ca-tag ca-tag-warn">Depends on keyword choice</span> may target the wrong keyword.</p>
          <div class="ca-mismatch-actions">
            <button type="button" class="ca-export-btn" data-mismatch="rerun">Re-run with “${escapeHtml(mismatch.search_console_query)}”</button>
            <button type="button" class="ca-export-btn" data-mismatch="keep">Keep “${escapeHtml(mismatch.target_keyword)}”</button>
          </div>
        </article>`;
      }
      if (mismatch) {
        return `<p class="ca-hint">Target confirmed: “${escapeHtml(mismatch.target_keyword)}” (Search Console’s top query is “${escapeHtml(mismatch.search_console_query)}”).</p>`;
      }
      if (targeting.mismatch && targeting.primary_ranking_query) {
        return `<p class="ca-serp-insight"><strong>Keyword mismatch.</strong> Search Console’s strongest query is “${escapeHtml(targeting.primary_ranking_query)}”; this analysis scored on-page placement against “${escapeHtml(targeting.target_keyword || result.serp_query || "")}”.</p>`;
      }
      return "";
    })();

    const ctrLabel = gsc.ctr == null ? "Data unavailable" : `${Math.round(Number(gsc.ctr) * 1000) / 10}%`;
    const posLabel = gsc.position == null ? "Data unavailable" : Number(gsc.position).toFixed(1);
    dashBody.innerHTML = `
      <section class="ca-section">
        <h3>What's happening</h3>
        ${renderIndexStatus(result)}
        ${gsc.status === "ok" ? `<div class="ca-stat-row">
          <div class="ca-stat"><span>Clicks${period.label ? ` · ${escapeHtml(period.label)}` : ""}</span><strong>${escapeHtml(metricLabel(gsc.clicks))}</strong></div>
          <div class="ca-stat"><span>Impressions</span><strong>${escapeHtml(metricLabel(gsc.impressions))}</strong></div>
          <div class="ca-stat"><span>CTR</span><strong>${escapeHtml(ctrLabel)}</strong></div>
          <div class="ca-stat"><span>Avg position</span><strong>${escapeHtml(posLabel)}</strong></div>
        </div>` : `<p class="ca-empty">${escapeHtml(gsc.reason || "Search Console numbers are Data unavailable.")}</p>`}
        <ul class="ca-plain">${(verdict.observed || [verdict.text || result.diagnosis_summary?.text || "No status is available for this run."]).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
        ${(verdict.areas_to_check || []).length ? `<p class="ca-hint">Also check: ${escapeHtml((verdict.areas_to_check || []).join(" · "))}</p>` : ""}
      </section>
      ${mismatchBlock}
      <section class="ca-section">
        <h3>What to fix</h3>
        ${topPlan.length ? fixList(topPlan) : sectionNote(result.action_plan_report, `<p class="ca-empty">No actions on this run.</p>`)}
        ${morePlan.length ? `<details class="ca-fold"><summary>Show ${morePlan.length} more</summary>${fixList(morePlan)}</details>` : ""}
      </section>
      <section class="ca-section">
        <h3>Recommended copy</h3>
        ${renderLlmAdvice(result.llm_advice) || `<p class="ca-empty">No copy drafts on this run.</p>`}
      </section>
      <section class="ca-section">
        <h3>Topics to add${dependsTag(pending)}</h3>
        ${addRows.length ? `<ol class="ca-topic-list">${addRows.slice(0, 10).map((row) => `<li>${escapeHtml(row.topic)}</li>`).join("")}</ol>` : `<p class="ca-empty">${escapeHtml(result.what_to_add?.note || gaps.reason || result.content_gaps?.reason || "No missing topics found.")}</p>`}
      </section>
      <details class="ca-fold">
        <summary>Search Console details</summary>
        ${renderDiagnosis(result)}
        ${insights.map((item) => `<p class="ca-serp-insight">${escapeHtml(item)}</p>`).join("")}
        <h4>Query opportunities</h4>
        ${renderQueryOpportunities(result.query_opportunities)}
        ${renderCtrChecklist(result.ctr_checklist)}
        <h4>Keywords</h4>
        ${renderKeywordFocus(result)}
      </details>
      <details class="ca-fold">
        <summary>Images and readability</summary>
        <h4>Images &amp; alt text</h4>
        ${renderImages(result.images)}
        <h4>Readability</h4>
        <p>${readability.status === "unavailable" ? escapeHtml(readability.reason || "Readability unavailable") : `${escapeHtml(readability.interpretation || "")} · Flesch ${scoreNum(readability.flesch_reading_ease)}`}</p>
        ${citations.length ? `<h4>Citation opportunities</h4>${tableRows(["Question","Status"], citations.map((c) => [escapeHtml(c.keyword_or_question), escapeHtml(c.status)]))}` : ""}
        ${traffic.length ? `<h4>On-page gaps vs competitors</h4>${traffic.map((r) => `<p>${escapeHtml(r.reason)} — ${escapeHtml(r.fix)}</p>`).join("")}` : ""}
      </details>
    `;
  }

  function ctrPct(value) {
    if (value == null || value === "") return "Data unavailable";
    const n = Number(value);
    return Number.isFinite(n) ? `${Math.round(n * 1000) / 10}%` : "Data unavailable";
  }

  function posLabel(value) {
    if (value == null || value === "") return "Data unavailable";
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(1) : String(value);
  }

  function scoreLine(scores) {
    return ["seo", "geo", "aeo", "aio", "sxo"].map((key) => {
      const n = numericScore(scores?.[key]);
      return `${key.toUpperCase()} ${n == null ? "N/A" : n}`;
    }).join("  ·  ");
  }

  function pdfFilename(result) {
    const kw = String(result.target_keyword || result.serp_query || "report")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "report";
    const when = String(result.analyzed_at || "").slice(0, 10) || new Date().toISOString().slice(0, 10);
    return `competitor-analysis-${kw}-${when}.pdf`;
  }

  function createPdfWriter() {
    const JsPDF = window.jspdf && window.jspdf.jsPDF;
    if (!JsPDF) throw new Error("PDF library failed to load. Refresh the page and try again.");
    const doc = new JsPDF({ unit: "mm", format: "a4", compress: true });
    const pageW = 210;
    const pageH = 297;
    const L = 15;
    const R = 15;
    const T = 16;
    const B = 18;
    const W = pageW - L - R;
    let y = T;
    const ink = [28, 28, 36];
    const muted = [100, 102, 114];
    const brand = [30, 64, 175];
    const rule = [226, 228, 235];

    function need(h) {
      if (y + h <= pageH - B) return false;
      doc.addPage();
      y = T;
      return true;
    }

    function wrap(str, width) {
      return doc.splitTextToSize(String(str || "").replace(/\s+/g, " ").trim() || "—", width || W);
    }

    function writeLines(lines, size, style, color, extraGap) {
      const lh = size * 0.42;
      doc.setFont("helvetica", style);
      doc.setFontSize(size);
      doc.setTextColor(color[0], color[1], color[2]);
      lines.forEach((ln) => {
        need(lh + 1);
        doc.text(ln, L, y);
        y += lh;
      });
      y += extraGap == null ? 2.2 : extraGap;
    }

    function h1(str) { writeLines(wrap(str), 18, "bold", ink, 2); }
    function h2(str) {
      need(14);
      y += 3;
      writeLines(wrap(str), 13, "bold", brand, 1.2);
      doc.setDrawColor(rule[0], rule[1], rule[2]);
      doc.setLineWidth(0.3);
      doc.line(L, y, L + W, y);
      y += 3.4;
    }
    function h3(str) { writeLines(wrap(str), 11, "bold", ink, 1.8); }
    function p(str) { if (str) writeLines(wrap(str), 10, "normal", ink, 2.4); }
    function note(str) { if (str) writeLines(wrap(str), 9, "italic", muted, 2.2); }
    function item(n, str) {
      writeLines(wrap((n == null ? "•  " : `${n}.  `) + str, W - 2), 10, "normal", ink, 1.8);
    }

    function kv(label, value) {
      const labelW = 42;
      const lines = wrap(value, W - labelW);
      const lh = 4.2;
      need(Math.max(5.2, lines.length * lh));
      doc.setFont("helvetica", "bold");
      doc.setFontSize(8.5);
      doc.setTextColor(muted[0], muted[1], muted[2]);
      doc.text(String(label).toUpperCase(), L, y);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(10);
      doc.setTextColor(ink[0], ink[1], ink[2]);
      lines.forEach((ln) => {
        need(lh);
        doc.text(ln, L + labelW, y);
        y += lh;
      });
      y += 1.2;
    }

    function table(headers, rows) {
      if (!rows.length) {
        note("None on this run.");
        return;
      }
      const n = headers.length;
      const widths = n === 2 ? [W * 0.36, W * 0.64]
        : n === 3 ? [W * 0.48, W * 0.26, W * 0.26]
        : n === 4 ? [W * 0.36, W * 0.16, W * 0.16, W * 0.32]
        : n === 5 ? [W * 0.30, W * 0.14, W * 0.16, W * 0.12, W * 0.28]
        : Array.from({ length: n }, () => W / n);

      function drawHeader() {
        const wrapped = headers.map((h, i) => doc.splitTextToSize(String(h), widths[i] - 2.4));
        const lh = 3.5;
        const h = Math.max(...wrapped.map((part) => part.length)) * lh + 3;
        need(h + 2);
        doc.setFillColor(244, 245, 249);
        doc.rect(L, y - 3.6, W, h, "F");
        doc.setFont("helvetica", "bold");
        doc.setFontSize(8);
        doc.setTextColor(muted[0], muted[1], muted[2]);
        let x = L;
        wrapped.forEach((lines, i) => {
          doc.text(lines, x + 1.2, y);
          x += widths[i];
        });
        y += h;
      }

      drawHeader();
      rows.forEach((row) => {
        const wrapped = row.map((cell, i) => doc.splitTextToSize(String(cell ?? "—"), widths[i] - 2.4));
        const lh = 3.6;
        const h = Math.max(...wrapped.map((part) => part.length)) * lh + 2.4;
        if (need(h + 1)) drawHeader();
        doc.setFont("helvetica", "normal");
        doc.setFontSize(8.5);
        doc.setTextColor(ink[0], ink[1], ink[2]);
        let x = L;
        wrapped.forEach((lines, i) => {
          doc.text(lines, x + 1.2, y);
          x += widths[i];
        });
        y += h;
        doc.setDrawColor(236, 237, 242);
        doc.setLineWidth(0.2);
        doc.line(L, y - 1, L + W, y - 1);
      });
      y += 2.5;
    }

    function finish(filename) {
      const pages = doc.getNumberOfPages();
      for (let i = 1; i <= pages; i += 1) {
        doc.setPage(i);
        doc.setFont("helvetica", "normal");
        doc.setFontSize(8);
        doc.setTextColor(muted[0], muted[1], muted[2]);
        doc.text("Blog Agent  ·  Competitor analysis", L, pageH - 8);
        doc.text(`${i} / ${pages}`, pageW - R, pageH - 8, { align: "right" });
      }
      doc.save(filename);
    }

    return { h1, h2, h3, p, note, item, kv, table, finish };
  }

  function writeScoreFactors(pdf, scores) {
    ["seo", "geo", "aeo", "aio", "sxo"].forEach((key) => {
      const factors = scores?.reports?.[key]?.factors || [];
      if (!factors.length) return;
      pdf.h3(`${key.toUpperCase()} checks`);
      factors.forEach((factor) => {
        const bits = [`${factor.name || "Check"}: ${factor.score ?? "—"}/${factor.max ?? ""}`];
        if (factor.note) bits.push(factor.note);
        if (!factor.passed && factor.tip) bits.push(factor.tip);
        pdf.item(null, bits.join(" — "));
      });
    });
  }

  function writeKeywordGroup(pdf, title, subtitle, rows, empty, showVolume) {
    pdf.h3(title);
    pdf.note(subtitle);
    if (!(rows || []).length) {
      pdf.p(empty);
      return;
    }
    const headers = showVolume ? ["Keyword", "Notes", "Search volume"] : ["Keyword", "Notes"];
    pdf.table(headers, rows.map((row) => {
      const cells = [row.keyword || "", row.evidence || ""];
      if (showVolume) cells.push(String(row.search_volume ?? "Data unavailable"));
      return cells;
    }));
  }

  function writeAnalysisPdf(result) {
    const pdf = createPdfWriter();
    const page = result.your_page || {};
    const gsc = result.gsc_diagnosis || {};
    const period = result.diagnosis_window || gsc.period || {};
    const index = result.index_status || gsc.index_status || {};
    const verdict = result.verdict || {};
    const advice = result.llm_advice || {};
    const plan = Array.isArray(result.action_plan) ? result.action_plan : (result.action_plan_report?.items || []);
    const wins = result.quick_wins || [];
    const topics = (result.what_to_add && result.what_to_add.table) || [];
    const queries = gsc.queries || [];
    const losses = (gsc.query_losses && gsc.query_losses.items) || [];
    const comps = gsc.comparisons || result.comparisons || {};
    const competitors = result.competitors || [];
    const yours = result.your_scores || result.old_scores || {};
    const avg = competitorAverages(result);
    const focus = keywordFocus(result);
    const pending = keywordChoicePending(result);
    const readability = deriveReadability(result);
    const citations = deriveCitations(result);
    const traffic = deriveTraffic(result);
    const title = page.title || result.source_title || result.target_keyword || "Page report";

    pdf.h1("Competitor analysis report");
    pdf.note("Blog Agent");
    pdf.p(title);
    pdf.kv("Page", page.url || result.blog_url || "Not submitted");
    pdf.kv("Target keyword", result.target_keyword || result.serp_query || "—");
    pdf.kv("Prepared", formatWhen(result.analyzed_at));
    pdf.kv("Range", `${period.label || "Last 6 months"}${period.start && period.end ? ` · ${period.start} to ${period.end}` : ""}`);

    pdf.h2("1. What's happening");
    if (index.label) {
      const source = index.source === "url_inspection"
        ? "URL Inspection"
        : index.source === "robots_only"
          ? "Robots only — not a Google index check"
          : "Not verified";
      pdf.p(`Google index: ${index.label}${index.coverage_state ? ` — ${index.coverage_state}` : ""} (${source})`);
      if (index.last_crawl) pdf.p(`Last crawl: ${index.last_crawl}`);
      if (index.indexing_state) pdf.p(`Indexing state: ${index.indexing_state}`);
      pdf.note(index.note);
      if (index.impressions_hint) pdf.note(index.impressions_hint);
    } else {
      pdf.p("Inspection unavailable.");
    }
    if (gsc.status === "ok") {
      pdf.p(`Search Console ${period.label || "this period"}: ${metricLabel(gsc.clicks)} clicks · ${metricLabel(gsc.impressions)} impressions · CTR ${ctrPct(gsc.ctr)} · avg position ${posLabel(gsc.position)}`);
    } else {
      pdf.p(gsc.reason || "Search Console numbers are Data unavailable.");
    }
    (verdict.observed || [verdict.text || result.diagnosis_summary?.text || "No status is available for this run."]).forEach((line, i) => {
      pdf.item(i + 1, line);
    });
    if ((verdict.areas_to_check || []).length) {
      pdf.p(`Also check: ${verdict.areas_to_check.join(" · ")}`);
    }

    const mismatch = result.keyword_mismatch;
    const targeting = gsc.keyword_targeting || {};
    if (mismatch && !mismatch.confirmed) {
      pdf.p(`Choose your target keyword first. Search Console traffic mostly comes from “${mismatch.search_console_query}”, but this report was measured against “${mismatch.target_keyword}”.`);
    } else if (mismatch) {
      pdf.note(`Target confirmed: “${mismatch.target_keyword}” (Search Console’s top query is “${mismatch.search_console_query}”).`);
    } else if (targeting.mismatch && targeting.primary_ranking_query) {
      pdf.p(`Keyword mismatch. Search Console’s strongest query is “${targeting.primary_ranking_query}”; this analysis scored on-page placement against “${targeting.target_keyword || result.serp_query || ""}”.`);
    }

    pdf.h2("2. What to fix");
    if (wins.length) {
      pdf.h3("Start here");
      wins.forEach((item, i) => {
        const dep = pending && item.depends_on_keyword ? " (Depends on keyword choice)" : "";
        pdf.item(i + 1, `${item.category || "Fix"} — ${item.recommended_action || item.issue || ""}${dep}`);
      });
    }
    if (plan.length) {
      if (wins.length) pdf.h3("Full action list");
      plan.forEach((item, i) => {
        const dep = pending && item.depends_on_keyword ? " (Depends on keyword choice)" : "";
        pdf.item(i + 1, `${item.category || "Fix"} — ${item.recommended_action || item.issue || ""}${dep}`);
      });
    }
    if (!wins.length && !plan.length) {
      pdf.p(result.action_plan_report?.reason || "No actions on this run.");
    }

    pdf.h2("3. Recommended copy");
    pdf.note("Draft copy only. It is not a measured ranking change.");
    if (advice.status === "ok") {
      if (advice.editor_summary) pdf.p(`Recommendation. ${advice.editor_summary}`);
      [["title", "Title"], ["h1", "H1"], ["meta_description", "Meta"]].forEach(([key, label]) => {
        const block = advice[key] || {};
        const current = block.current || (key === "title" ? page.title : key === "h1" ? (page.h1 || headingList(page.h1_headings)[0]) : page.meta_description) || "—";
        pdf.h3(label);
        pdf.p(`Now: ${current || "—"}`);
        pdf.p(`Recommended: ${block.recommended || "No draft on this run"}`);
      });
      (advice.next_steps || []).forEach((step, i) => pdf.item(i + 1, step));
    } else {
      pdf.p(advice.reason ? `Recommendation model unavailable: ${advice.reason}` : "No copy drafts on this run.");
    }

    pdf.h2(`4. Topics to add${pending ? " (Depends on keyword choice)" : ""}`);
    if (topics.length) topics.forEach((row, i) => pdf.item(i + 1, row.topic || ""));
    else pdf.p(result.what_to_add?.note || "No missing topics found.");

    pdf.h2("5. Search Console details");
    if (gsc.status === "ok") {
      if (comps.current || comps.previous || comps.year_ago) {
        pdf.h3("Period comparison");
        ["current", "previous", "year_ago"].forEach((key) => {
          const row = comps[key];
          if (!row) return;
          const dates = [row.start, row.end].filter(Boolean).join(" to ");
          if (row.status && row.status !== "ok") {
            pdf.p(`${row.label || key}${dates ? ` (${dates})` : ""}: ${row.reason || "Data unavailable"}`);
            return;
          }
          const change = row.impressions_delta_pct == null ? "" : ` · vs this period ${deltaLabel(row.impressions_delta_pct)}`;
          pdf.p(`${row.label || key}${dates ? ` (${dates})` : ""}: clicks ${metricLabel(row.clicks)} · impressions ${metricLabel(row.impressions)}${change} · CTR ${ctrPct(row.ctr)} · avg position ${posLabel(row.position)}`);
        });
      }
      pdf.h3("Queries");
      if (queries.length) {
        pdf.table(
          ["Query", "Clicks", "Impressions", "CTR", "Position"],
          queries.map((row) => [row.query || "", metricLabel(row.clicks), metricLabel(row.impressions), ctrPct(row.ctr), posLabel(row.position)]),
        );
      } else {
        pdf.p("No query rows for this window.");
      }
      pdf.h3("Queries that lost visibility");
      if (gsc.query_losses && gsc.query_losses.status && gsc.query_losses.status !== "ok") {
        pdf.p(gsc.query_losses.reason || "Data unavailable");
      } else if (losses.length) {
        pdf.table(
          ["Query", "This period", "Previous", "Change", "What changed"],
          losses.map((row) => [
            row.query || "",
            String(row.impressions ?? ""),
            String(row.previous_impressions ?? ""),
            String(row.impressions_delta ?? ""),
            lossKindLabel(row.kind),
          ]),
        );
        pdf.note("Compared with the equal-length period before the range you chose. Numbers are Search Console counts, not estimates.");
      } else {
        pdf.p("No query losses in this window.");
      }
      const qo = result.query_opportunities;
      if (qo) {
        [
          ["Quick wins (position 4–10)", qo.quick_wins],
          ["Page-two opportunities (11–20)", qo.page_two],
          ["Content opportunities (21–50)", qo.content],
        ].forEach(([label, rows]) => {
          pdf.h3(label);
          if ((rows || []).length) {
            pdf.table(["Query", "Position", "Impressions"], rows.map((row) => [row.query || "", posLabel(row.position), metricLabel(row.impressions)]));
          } else {
            pdf.note("None in this band.");
          }
        });
        pdf.note(qo.note || "");
      }
      const ctr = result.ctr_checklist;
      if (ctr && ctr.status !== "unavailable") {
        pdf.h3("CTR");
        pdf.p(ctr.observed || "");
        (ctr.possible_checks || []).forEach((item) => pdf.item(null, item));
        pdf.note(ctr.note || "");
      }
    } else {
      pdf.p(gsc.reason || "Search Console is not connected for this URL.");
    }
    (result.serp_insights || []).forEach((item) => pdf.p(item));

    pdf.h2("6. Keywords");
    writeKeywordGroup(
      pdf,
      "Performing well for your blog",
      focus.oursBasis === "search_console"
        ? "Top page-one Search Console queries by clicks"
        : "No Search Console data: ranked by how strongly your page uses them, not by traffic",
      focus.ours,
      result.your_page ? "No strong keywords found on your page." : "Add a blog URL to see your keywords.",
      false,
    );
    writeKeywordGroup(
      pdf,
      `Topics competitors cover${pending ? " — Depends on keyword choice" : ""}`,
      "Used by the most competitor pages you added",
      focus.competitors,
      competitors.length ? "No shared competitor keywords found." : "Add competitor URLs to see their keywords.",
      false,
    );
    writeKeywordGroup(
      pdf,
      `Close to ranking (Recommendation)${pending ? " — Depends on keyword choice" : ""}`,
      focus.closeNote || "Queries you already get impressions for but rank below position 10.",
      focus.closeToRanking,
      "No striking-distance Search Console queries found.",
      true,
    );
    if (focus.newTopics.length) {
      writeKeywordGroup(pdf, "New topics", focus.newTopicsNote || "", focus.newTopics, "None.", false);
    }
    pdf.note(focus.note);

    pdf.h2("7. Images and alt text");
    const images = result.images;
    if (!images || images.status !== "ok") {
      pdf.p(images?.reason || "Image audit unavailable.");
    } else {
      const summary = images.summary || {};
      const comp = images.competitors;
      pdf.p(`${summary.total || 0} article images · ${summary.ok || 0} with good alt text${summary.decorative ? ` · ${summary.decorative} decorative` : ""}${comp ? ` · competitors average ${comp.avg_images} images${comp.avg_descriptive_pct != null ? `, ${comp.avg_descriptive_pct}% with descriptive alt` : ""}` : ""}`);
      (images.recommendations || []).forEach((rec) => pdf.item(null, rec));
      const items = images.items || [];
      if (items.length) {
        pdf.table(
          ["Image", "Section", "Alt now", "Issue", "Suggested alt"],
          items.map((item) => [
            item.filename || item.src || "image",
            item.section || "—",
            item.alt || "none",
            item.issue || "",
            item.suggested_alt ? `${item.suggested_alt} (Draft from ${item.suggestion_basis || "alt"})` : "Describe what the image shows",
          ]),
        );
      } else if (summary.total) {
        pdf.p("No alt-text issues found.");
      }
      pdf.note(images.note || "");
    }

    pdf.h2("8. Readability and on-page gaps");
    if (readability.status === "unavailable") {
      pdf.p(readability.reason || "Readability unavailable");
    } else {
      pdf.p(`${readability.interpretation || ""} · Flesch ${scoreNum(readability.flesch_reading_ease)}${readability.flesch_kincaid_grade != null ? ` · Grade ${readability.flesch_kincaid_grade}` : ""}${readability.avg_sentence_length != null ? ` · Avg sentence ${readability.avg_sentence_length} words` : ""}`);
    }
    if (citations.length) {
      pdf.h3("Citation opportunities");
      pdf.table(["Question", "Status"], citations.map((row) => [row.keyword_or_question, row.status]));
    }
    if (traffic.length) {
      pdf.h3("On-page gaps vs competitors");
      traffic.forEach((row) => pdf.item(null, `${row.reason} — ${row.fix}`));
    }

    pdf.h2("9. Your page");
    pdf.kv("Title", page.title || "—");
    pdf.kv("URL", page.url || result.blog_url || "—");
    pdf.kv("Words", formatWords(page.word_count));
    pdf.kv("H2s", String(page.h2_count ?? "—"));
    pdf.kv("On-page scores", scoreLine(yours));
    if (yours.keyword_targeting_score != null || yours.onpage_technical_score != null) {
      pdf.p(`Keyword targeting ${yours.keyword_targeting_score ?? "N/A"} · On-page technical ${yours.onpage_technical_score ?? "N/A"}`);
    }
    if (competitors.length) {
      pdf.p(`Competitor average: ${scoreLine(avg)}${avg.sample_note ? ` (${avg.sample_note})` : ""}`);
    }
    writeScoreFactors(pdf, yours);
    const yourHeads = pageHeadings(page, false);
    if (yourHeads.length) {
      pdf.h3("Headings");
      yourHeads.forEach((heading) => pdf.item(null, heading));
    }
    if (page.meta_description) {
      pdf.h3("Meta description");
      pdf.p(page.meta_description);
    }

    pdf.h2("10. Competitors you added");
    if (!competitors.length) {
      pdf.p("No competitor URLs were added, so this is an audit of your page only.");
    } else {
      competitors.forEach((row, i) => {
        pdf.h3(`${i + 1}. ${row.domain || row.url || "Competitor"}`);
        if (row.url) pdf.p(row.url);
        pdf.p(`${formatWords(row.word_count)} · ${row.h2_count ?? "—"} H2s`);
        pdf.p(`Scores: ${scoreLine(row.scores || {})}`);
        writeScoreFactors(pdf, row.scores || {});
        const heads = headingList(row.h2_headings).concat(headingList(row.h2)).concat(headingList(row.h1_headings)).concat(headingList(row.h1));
        if (heads.length) {
          pdf.note("Headings");
          heads.forEach((heading) => pdf.item(null, heading));
        }
      });
    }

    pdf.h2("Notes");
    pdf.note("Search volume, keyword difficulty, domain authority, backlinks, and Core Web Vitals are Data unavailable unless a measured source is shown above. On-page scores are extract checks, not traffic forecasts. Recommended copy is a draft, not a guaranteed ranking change.");
    pdf.finish(pdfFilename(result));
  }

  function downloadPdfReport() {
    if (!currentResult) {
      showError("Run an analysis first, then download the PDF.");
      return;
    }
    const btn = document.querySelector('[data-export="pdf"]');
    const label = btn?.textContent;
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Preparing PDF…";
      }
      writeAnalysisPdf(currentResult);
    } catch (err) {
      console.error("[Competitor Analysis] pdf failed", err);
      showError(err.message || "Could not create the PDF.");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = label || "Download PDF";
      }
    }
  }

  document.querySelectorAll("[data-export]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.export === "pdf") downloadPdfReport();
    });
  });

  function toggleScoreFactors(event) {
    const btn = event.target.closest("[data-score-toggle]");
    if (!btn || btn.disabled) return;
    const wrap = btn.closest(".ca-scores");
    const panel = wrap?.querySelector(`[data-factors="${btn.dataset.scoreToggle}"]`);
    if (!panel) return;
    const open = panel.hidden;
    wrap.querySelectorAll("[data-factors]").forEach((el) => { el.hidden = true; });
    wrap.querySelectorAll("[data-score-toggle]").forEach((el) => el.setAttribute("aria-expanded", "false"));
    if (open) {
      panel.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    }
  }
  [dashBody, yoursEl, tableEl].forEach((el) => el?.addEventListener("click", toggleScoreFactors));
  document.getElementById("ca-snapshot")?.addEventListener("click", (event) => event.stopPropagation());

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
  renderSnapshotOptions();
  setRewriteEnabled(false);
})();
