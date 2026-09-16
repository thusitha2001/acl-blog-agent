(function () {
  const HANDOFF_KEY = "ba-editor-handoff";
  const PENDING_KEY = "ba-editor-handoff-pending";
  const AUTOSAVE_KEY = "ba-editor-autosave";
  const HISTORY_KEY = "ba-editor-history";

  const emptyEl = document.getElementById("ed-empty");
  const workspace = document.getElementById("ed-workspace");
  const canvas = document.getElementById("ed-canvas");
  const titleEl = document.getElementById("ed-title");
  const statusEl = document.getElementById("ed-status");
  const saveInd = document.getElementById("ed-save-ind");
  const seoTitle = document.getElementById("ed-seo-title");
  const metaEl = document.getElementById("ed-meta");
  const slugEl = document.getElementById("ed-slug");
  const keywordEl = document.getElementById("ed-keyword");
  const chipInput = document.getElementById("ed-chip-input");
  const chipsEl = document.getElementById("ed-chips");

  let secondary = [];
  let slugLocked = false;
  let lastEdited = Date.now();
  let saveTimer = null;
  let scoreTimer = null;
  let scores = { seo: { score: 0 }, geo: { score: 0 }, aeo: { score: 0 } };
  let competitorAvgWords = null;
  let loaded = false;
  let lastSyncedTitle = "";

  const SCORE_COPY = {
    seo: "On-page search signals: keyword placement, metadata, structure, and links.",
    geo: "How easily generative engines can extract, cite, and trust this article.",
    aeo: "Fit for featured snippets, People Also Ask, and voice answers.",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function wordCount(html) {
    const text = String(html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    return text ? text.split(" ").length : 0;
  }

  function slugify(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80) || "article";
  }

  function grade(score) {
    if (score >= 90) return "Excellent";
    if (score >= 75) return "Good";
    if (score >= 60) return "Fair";
    return "Poor";
  }

  function isHtml(src) {
    return /<(h[1-3]|p|ul|ol|table|article)\b/i.test(src || "");
  }

  function markdownToHtml(md) {
    const source = (md || "").trim();
    if (!source) return "";
    if (isHtml(source)) return source;
    const lines = source.split("\n");
    let html = "";
    let listType = null;
    const closeList = () => {
      if (listType) { html += "</" + listType + ">"; listType = null; }
    };
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) { closeList(); continue; }
      if (/^###\s+/.test(trimmed)) { closeList(); html += "<h3>" + escapeHtml(trimmed.slice(4)) + "</h3>"; continue; }
      if (/^##\s+/.test(trimmed)) { closeList(); html += "<h2>" + escapeHtml(trimmed.slice(3)) + "</h2>"; continue; }
      if (/^#\s+/.test(trimmed)) { closeList(); html += "<h1>" + escapeHtml(trimmed.slice(2)) + "</h1>"; continue; }
      if (/^>\s+/.test(trimmed)) { closeList(); html += "<blockquote>" + escapeHtml(trimmed.slice(2)) + "</blockquote>"; continue; }
      if (/^[-*]\s+/.test(trimmed)) {
        if (listType !== "ul") { closeList(); html += "<ul>"; listType = "ul"; }
        html += "<li>" + escapeHtml(trimmed.slice(2)) + "</li>";
        continue;
      }
      if (/^\d+[.)]\s+/.test(trimmed)) {
        if (listType !== "ol") { closeList(); html += "<ol>"; listType = "ol"; }
        html += "<li>" + escapeHtml(trimmed.replace(/^\d+[.)]\s+/, "")) + "</li>";
        continue;
      }
      closeList();
      html += "<p>" + escapeHtml(trimmed) + "</p>";
    }
    closeList();
    return html;
  }

  function relativeTime(ts) {
    const mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
    if (mins <= 0) return "just now";
    if (mins === 1) return "1 minute ago";
    if (mins < 60) return mins + " minutes ago";
    const hours = Math.round(mins / 60);
    return hours === 1 ? "1 hour ago" : hours + " hours ago";
  }

  function headings() {
    return [...canvas.querySelectorAll("h1, h2, h3")].map((el, i) => {
      if (!el.id) el.id = "ed-h-" + i;
      return { id: el.id, level: Number(el.tagName[1]), text: el.textContent.trim() };
    });
  }

  function keywordHits() {
    const kw = keywordEl.value.trim();
    if (!kw) return 0;
    const text = canvas.innerText || "";
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const matches = text.match(new RegExp(escaped, "gi"));
    return matches ? matches.length : 0;
  }

  function renderChips() {
    chipsEl.innerHTML = secondary.map((kw, i) =>
      `<span class="ed-chip">${escapeHtml(kw)}<button type="button" data-i="${i}" aria-label="Remove">×</button></span>`
    ).join("");
    chipsEl.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        secondary.splice(Number(btn.dataset.i), 1);
        renderChips();
        scheduleSave();
      });
    });
  }

  function renderScores() {
    const pack = (key, label) => {
      const report = scores[key] || {};
      const score = Number(report.score || 0);
      return `
        <div class="score-card score-${score >= 80 ? "high" : score >= 60 ? "mid" : "low"}">
          <div class="score-ring" style="--pct:${score}"><span class="score-ring-value">${score}</span></div>
          <div class="score-card-copy">
            <div class="score-name">${label}</div>
            <div class="score-grade">${grade(score)}</div>
            <p class="score-summary">${SCORE_COPY[key]}</p>
          </div>
        </div>`;
    };
    document.getElementById("ed-scores").innerHTML =
      pack("seo", "SEO") + pack("geo", "GEO") + pack("aeo", "AEO");
  }

  function renderStructure() {
    const list = headings();
    const h1 = list.filter((h) => h.level === 1).length;
    const h2 = list.filter((h) => h.level === 2).length;
    const h3 = list.filter((h) => h.level === 3).length;
    const words = wordCount(canvas.innerHTML);
    document.getElementById("ed-counts").innerHTML = `
      <span>H1 ${h1}</span><span>H2 ${h2}</span><span>H3 ${h3}</span><span>${words.toLocaleString()} words</span>
    `;
    document.getElementById("ed-outline").innerHTML = list.length
      ? list.map((h) =>
        `<button type="button" class="ed-outline-item lv${h.level}" data-id="${h.id}">${escapeHtml(h.text || "(empty)")}</button>`
      ).join("")
      : `<p class="ed-empty-mini">Headings will appear as you write.</p>`;
    document.querySelectorAll(".ed-outline-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.getElementById(btn.dataset.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
  }

  function renderChecklist() {
    const html = canvas.innerHTML;
    const text = canvas.innerText || "";
    const title = titleEl.textContent.trim();
    const kw = keywordEl.value.trim().toLowerCase();
    const meta = metaEl.value.trim();
    const words = wordCount(html);
    const h2s = [...canvas.querySelectorAll("h2")].map((el) => el.textContent);
    const items = [
      ["Title includes primary keyword", !!(kw && title.toLowerCase().includes(kw))],
      ["Meta description under 160 characters", meta.length > 0 && meta.length <= 160],
      ["At least one H2 contains a question", h2s.some((h) => /\?|(how|what|why|when|where|which|who)\b/i.test(h))],
      ["FAQ section present", /faq|frequently asked/i.test(text)],
      [
        competitorAvgWords
          ? `Word count is competitive (≥ ${Math.round(competitorAvgWords * 0.7).toLocaleString()} vs avg ${competitorAvgWords.toLocaleString()})`
          : "Word count is competitive",
        competitorAvgWords ? words >= competitorAvgWords * 0.7 : words >= 800,
      ],
      ["At least 2 internal links present", (html.match(/<a\b[^>]*href=["'][^"']+["']/gi) || []).length >= 2],
      [
        "Images have alt text",
        canvas.querySelectorAll("img").length > 0
          && ![...canvas.querySelectorAll("img")].some((img) => !(img.getAttribute("alt") || "").trim()),
      ],
    ];
    document.getElementById("ed-check").innerHTML = items.map(([label, ok]) =>
      `<li class="${ok ? "is-on" : ""}"><span>${ok ? "✓" : ""}</span>${escapeHtml(label)}</li>`
    ).join("");
  }

  function updateStatus() {
    const words = wordCount(canvas.innerHTML);
    statusEl.textContent = `Draft · ${words.toLocaleString()} words · Last edited ${relativeTime(lastEdited)}`;
    const hits = keywordHits();
    const dens = words ? ((hits / words) * 100).toFixed(1) : "0.0";
    document.getElementById("ed-density").textContent =
      `Keyword density: ${hits} hit${hits === 1 ? "" : "s"} · ${dens}%`;
    const titleCount = document.getElementById("ed-seo-title-count");
    const metaCount = document.getElementById("ed-meta-count");
    titleCount.textContent = `${seoTitle.value.length} · ideal 50–60`;
    metaCount.textContent = `${metaEl.value.length} · ideal 150–160`;
    const titleLen = seoTitle.value.length;
    const metaLen = metaEl.value.length;
    titleCount.classList.toggle("ideal", titleLen >= 50 && titleLen <= 60);
    titleCount.classList.toggle("over", titleLen > 60 || (titleLen > 0 && titleLen < 50));
    metaCount.classList.toggle("ideal", metaLen >= 150 && metaLen <= 160);
    metaCount.classList.toggle("over", metaLen > 160 || (metaLen > 0 && metaLen < 150));
  }

  function snapshot() {
    return {
      title: titleEl.textContent.trim(),
      html: canvas.innerHTML,
      seoTitle: seoTitle.value,
      meta: metaEl.value,
      slug: slugEl.value,
      keyword: keywordEl.value,
      secondary,
      scores,
      competitorAvgWords,
      savedAt: Date.now(),
    };
  }

  function applySnapshot(data, markSaved) {
    titleEl.textContent = data.title || "Untitled article";
    canvas.innerHTML = data.html || "";
    seoTitle.value = data.seoTitle || data.title || "";
    metaEl.value = data.meta || "";
    slugEl.value = data.slug || slugify(data.title);
    keywordEl.value = data.keyword || "";
    secondary = Array.isArray(data.secondary) ? data.secondary.slice() : [];
    scores = data.scores || scores;
    competitorAvgWords = data.competitorAvgWords || competitorAvgWords;
    lastEdited = data.savedAt || Date.now();
    lastSyncedTitle = titleEl.textContent.trim();
    renderChips();
    renderScores();
    renderStructure();
    renderChecklist();
    updateStatus();
    if (markSaved) saveInd.textContent = "Saved";
  }

  function persistAutosave() {
    localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(snapshot()));
    saveInd.textContent = "Saved";
  }

  function pushHistory(label) {
    const item = { ...snapshot(), label: label || "Autosave" };
    let history = [];
    try { history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch (err) { history = []; }
    history.unshift(item);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 12)));
    renderHistory();
  }

  function renderHistory() {
    let history = [];
    try { history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch (err) { history = []; }
    const empty = document.getElementById("ed-history-empty");
    const list = document.getElementById("ed-history-list");
    empty.hidden = history.length > 0;
    list.innerHTML = history.map((item, i) => `
      <li>
        <span>${escapeHtml(item.label || "Version")} · ${new Date(item.savedAt).toLocaleString()}</span>
        <button type="button" class="ed-btn-secondary" data-restore="${i}">Restore</button>
      </li>
    `).join("");
    list.querySelectorAll("[data-restore]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.dataset.restore);
        if (history[idx]) {
          applySnapshot(history[idx], true);
          persistAutosave();
        }
      });
    });
  }

  function scheduleSave() {
    lastEdited = Date.now();
    saveInd.textContent = "Saving…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      persistAutosave();
      updateStatus();
      renderStructure();
      renderChecklist();
    }, 4000);
    clearTimeout(scoreTimer);
    scoreTimer = setTimeout(recalculate, 8000);
    updateStatus();
    renderStructure();
    renderChecklist();
  }

  async function recalculate() {
    const article = canvas.innerHTML.trim();
    if (wordCount(article) < 20) return;
    const btn = document.getElementById("ed-recalc");
    if (btn) btn.disabled = true;
    try {
      const response = await fetch("/score-article", {
        method: "POST",
        headers: window.BlogAgentAuth?.headers() || { "Content-Type": "application/json" },
        body: JSON.stringify({
          article,
          keyword: keywordEl.value.trim() || null,
          title: titleEl.textContent.trim() || null,
          meta_title: seoTitle.value.trim() || null,
          meta_description: metaEl.value.trim() || null,
          secondary_keywords: secondary,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        if (data.scores) scores = data.scores;
        renderScores();
      }
    } catch (err) {
      /* keep last scores */
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function showWorkspace() {
    emptyEl.hidden = true;
    workspace.hidden = false;
    loaded = true;
  }

  function showEmpty() {
    emptyEl.hidden = false;
    workspace.hidden = true;
    loaded = false;
  }

  function loadIncoming() {
    const pending = sessionStorage.getItem(PENDING_KEY) === "1";
    const nav = performance.getEntriesByType("navigation")[0];
    const isReload = nav?.type === "reload";
    if (pending) {
      let data = null;
      try { data = JSON.parse(sessionStorage.getItem(HANDOFF_KEY) || "null"); } catch (err) { data = null; }
      sessionStorage.removeItem(PENDING_KEY);
      sessionStorage.removeItem(HANDOFF_KEY);
      if (!data) { showEmpty(); return; }
      const html = markdownToHtml(data.article || "");
      applySnapshot({
        title: data.title || "Untitled article",
        html,
        seoTitle: data.metaTitle || data.title || "",
        meta: data.metaDescription || "",
        slug: data.slug || slugify(data.title),
        keyword: data.keyword || "",
        secondary: data.secondaryKeywords || [],
        scores: data.scores || scores,
        competitorAvgWords: data.competitorAvgWords || null,
        savedAt: Date.now(),
      }, true);
      slugLocked = !!data.slug;
      showWorkspace();
      persistAutosave();
      pushHistory("Opened from " + (data.source || "draft"));
      recalculate();
      return;
    }
    if (isReload) {
      try {
        const saved = JSON.parse(localStorage.getItem(AUTOSAVE_KEY) || "null");
        if (saved?.html) {
          applySnapshot(saved, true);
          showWorkspace();
          renderHistory();
          return;
        }
      } catch (err) { /* empty */ }
    }
    showEmpty();
  }

  document.querySelectorAll(".ed-toolbar [data-cmd]").forEach((btn) => {
    btn.addEventListener("click", () => {
      canvas.focus();
      document.execCommand(btn.dataset.cmd, false, null);
      scheduleSave();
    });
  });
  document.querySelectorAll(".ed-toolbar [data-block]").forEach((btn) => {
    btn.addEventListener("click", () => {
      canvas.focus();
      document.execCommand("formatBlock", false, btn.dataset.block);
      scheduleSave();
    });
  });
  document.querySelector("[data-action='link']")?.addEventListener("click", () => {
    const url = window.prompt("Link URL");
    if (!url) return;
    document.execCommand("createLink", false, url);
    scheduleSave();
  });
  document.querySelector("[data-action='table']")?.addEventListener("click", () => {
    document.execCommand("insertHTML", false, "<table><thead><tr><th>Heading</th><th>Heading</th></tr></thead><tbody><tr><td>Cell</td><td>Cell</td></tr></tbody></table>");
    scheduleSave();
  });
  document.querySelector("[data-action='image']")?.addEventListener("click", () => {
    const url = window.prompt("Image URL");
    if (!url) return;
    const alt = window.prompt("Alt text") || "";
    document.execCommand("insertHTML", false, `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}">`);
    scheduleSave();
  });

  canvas.addEventListener("input", scheduleSave);
  titleEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });
  titleEl.addEventListener("input", () => {
    const nextTitle = titleEl.textContent.trim();
    if (!slugLocked) slugEl.value = slugify(nextTitle);
    if (!seoTitle.value.trim() || seoTitle.value.trim() === lastSyncedTitle) {
      seoTitle.value = nextTitle;
    }
    lastSyncedTitle = nextTitle;
    scheduleSave();
  });
  slugEl.addEventListener("input", () => { slugLocked = true; scheduleSave(); });
  seoTitle.addEventListener("input", scheduleSave);
  metaEl.addEventListener("input", scheduleSave);
  keywordEl.addEventListener("input", scheduleSave);
  chipInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const value = chipInput.value.trim();
    if (!value || secondary.includes(value)) return;
    secondary.push(value);
    chipInput.value = "";
    renderChips();
    scheduleSave();
  });

  document.querySelectorAll(".ed-side .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ed-side .tab-btn").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".ed-side .tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      document.getElementById("tab-" + btn.dataset.tab)?.classList.add("active");
    });
  });

  document.getElementById("ed-save")?.addEventListener("click", () => {
    persistAutosave();
    pushHistory("Saved draft");
    saveInd.textContent = "Saved";
  });
  document.getElementById("ed-publish")?.addEventListener("click", async () => {
    persistAutosave();
    pushHistory("Published snapshot");
    const html = canvas.innerHTML.trim();
    try {
      await navigator.clipboard.writeText(html);
      document.getElementById("ed-publish").textContent = "Copied HTML";
      setTimeout(() => { document.getElementById("ed-publish").textContent = "Publish"; }, 1600);
    } catch (err) {
      window.alert("Copy the article HTML from the editor to publish.");
    }
  });
  document.getElementById("ed-recalc")?.addEventListener("click", recalculate);
  document.getElementById("ed-history-toggle")?.addEventListener("click", () => {
    const body = document.getElementById("ed-history-body");
    const open = body.hidden;
    body.hidden = !open;
    document.getElementById("ed-history-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  });

  loadIncoming();
  renderHistory();
})();
