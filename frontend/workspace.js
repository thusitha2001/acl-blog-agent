(function () {
  const AUTH_KEY = "ba-auth";
  const page = document.body?.dataset?.page || "dashboard";

  function getAuth() {
    try { return JSON.parse(localStorage.getItem(AUTH_KEY) || "null"); } catch (err) { return null; }
  }
  function setAuth(user) {
    localStorage.setItem(AUTH_KEY, JSON.stringify({
      token: user.token,
      name: user.name,
      user_id: user.user_id,
    }));
  }
  function clearAuth() {
    localStorage.removeItem(AUTH_KEY);
  }
  function authHeaders() {
    const auth = getAuth();
    const headers = { "Content-Type": "application/json" };
    if (auth?.token) headers.Authorization = "Bearer " + auth.token;
    return headers;
  }
  function initials(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "BA";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  function firstName(name) {
    return String(name || "").trim().split(/\s+/)[0] || "there";
  }

  window.BlogAgentAuth = { get: getAuth, set: setAuth, clear: clearAuth, headers: authHeaders };

  const auth = getAuth();
  if (page === "login") {
    if (auth?.token) {
      const next = new URLSearchParams(location.search).get("next") || "/";
      const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";
      window.location.replace(safeNext === "/login" ? "/" : safeNext);
    }
    return;
  }
  if (!auth?.token) {
    const next = location.pathname + location.search;
    window.location.replace("/login?next=" + encodeURIComponent(next || "/"));
    return;
  }

  const HIDE_ICON = '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true"><rect x="2.2" y="2.2" width="13.6" height="13.6" rx="2.6" stroke="currentColor" stroke-width="1.55"/><path d="M6.55 2.2v13.6" stroke="currentColor" stroke-width="1.55"/><rect x="2.2" y="2.2" width="4.35" height="13.6" rx="2.6" fill="currentColor"/></svg>';
  const items = [
    ["dashboard", "/", "Dashboard", '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>'],
    ["writer", "/writer", "Blog Writer", '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8 13h8M8 17h5"/>'],
    ["rewriter", "/rewriter", "Blog Rewriter", '<path d="M4 12a8 8 0 0 1 13.7-5.6L20 8"/><path d="M20 4v4h-4"/><path d="M20 12a8 8 0 0 1-13.7 5.6L4 16"/><path d="M4 20v-4h4"/>'],
    ["competitors", "/competitors", "Competitor Analysis", '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/><path d="M8 11h6M11 8v6"/>'],
    ["editor", "/editor", "Editor", '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>'],
  ];

  function navItem(id, href, label, icon) {
    const active = id === page ? " is-active" : "";
    const current = id === page ? ' aria-current="page"' : "";
    return `<a class="ws-nav-item${active}" href="${href}"${current}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icon}</svg>${label}</a>`;
  }

  function sidebarHTML() {
    const settingsActive = page === "settings" ? " is-active" : "";
    const ini = initials(auth.name);
    return `
  <aside class="ws-sidebar" id="ws-sidebar" aria-label="Workspace">
    <a href="/" class="ws-logo">
      <span class="ws-logo-mark" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M4 7.5L12 3l8 4.5v9L12 21l-8-4.5v-9z" stroke="currentColor" stroke-width="2"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" stroke="currentColor" stroke-width="2"/></svg>
      </span>
      <span class="ws-logo-text">Blog Agent</span>
    </a>
    <div class="ws-label-row">
      <p class="ws-label">Workspace</p>
      <button type="button" class="ws-hide-btn" id="ws-hide-sidebar" aria-label="Hide sidebar">${HIDE_ICON}</button>
    </div>
    <nav class="ws-nav" aria-label="Main">${items.map((row) => navItem(...row)).join("")}</nav>
    <div class="ws-sidebar-spacer"></div>
    <div class="ws-sidebar-foot">
      <a class="ws-nav-item" href="#help"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>Help &amp; Tutor</a>
      <a class="ws-nav-item${settingsActive}" href="/settings"${page === "settings" ? ' aria-current="page"' : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1-.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1-.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l.1-.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>Settings</a>
    </div>
    <div class="ws-user">
      <span class="ws-avatar">${ini}</span>
      <span><span class="ws-user-name">${auth.name}</span><span class="ws-user-role">Account</span></span>
    </div>
  </aside>`;
  }

  const workspace = document.querySelector(".workspace");
  if (workspace && !document.getElementById("ws-sidebar")) {
    workspace.insertAdjacentHTML("afterbegin", sidebarHTML());
  }

  function paintUser() {
    const ini = initials(auth.name);
    document.querySelectorAll(".ws-avatar").forEach((el) => { el.textContent = ini; });
    document.querySelectorAll(".ws-user-name").forEach((el) => { el.textContent = auth.name; });
    document.querySelectorAll(".ws-user-role").forEach((el) => { el.textContent = "Account"; });
    document.querySelectorAll(".ws-user-chip").forEach((chip) => {
      chip.setAttribute("href", "/settings");
      const strong = chip.querySelector("strong");
      if (strong) strong.textContent = auth.name;
      const role = chip.querySelector("span span");
      if (role && !role.classList.contains("ws-avatar")) role.textContent = "Account";
    });
    const settingsName = document.getElementById("settings-name");
    const settingsMeta = document.getElementById("settings-meta");
    if (settingsName) settingsName.textContent = auth.name;
    if (settingsMeta) settingsMeta.textContent = auth.user_id ? "Signed in · " + auth.user_id : "Signed in to Blog Agent";
    const greetingEl = document.getElementById("dash-greeting");
    if (greetingEl) {
      const hour = new Date().getHours();
      const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
      greetingEl.textContent = part + ", " + firstName(auth.name);
    }
    document.querySelectorAll('.ws-nav-item[href="#settings"]').forEach((link) => {
      link.setAttribute("href", "/settings");
      if (page === "settings") {
        link.classList.add("is-active");
        link.setAttribute("aria-current", "page");
      }
    });
  }
  paintUser();

  function ensureHideSidebar() {
    document.querySelector(".ws-topbar #ws-hide-sidebar")?.remove();
    const sidebar = document.getElementById("ws-sidebar");
    if (!sidebar) return;

    let btn = sidebar.querySelector("#ws-hide-sidebar");
    if (!btn) {
      let row = sidebar.querySelector(".ws-label-row");
      if (!row) {
        const label = sidebar.querySelector(".ws-label");
        row = document.createElement("div");
        row.className = "ws-label-row";
        if (label) {
          label.replaceWith(row);
          row.appendChild(label);
        } else {
          sidebar.insertBefore(row, sidebar.querySelector(".ws-nav"));
          row.insertAdjacentHTML("afterbegin", '<p class="ws-label">Workspace</p>');
        }
      }
      btn = document.createElement("button");
      btn.type = "button";
      btn.id = "ws-hide-sidebar";
      btn.className = "ws-hide-btn";
      btn.innerHTML = HIDE_ICON;
      row.appendChild(btn);
    }

    const key = "ba-sidebar-hidden";
    const apply = (hidden) => {
      document.body.classList.toggle("sidebar-hidden", hidden);
      btn.setAttribute("aria-pressed", hidden ? "true" : "false");
      btn.setAttribute("aria-label", hidden ? "Show sidebar" : "Hide sidebar");
      btn.title = hidden ? "Show sidebar" : "Hide sidebar";
    };
    apply(localStorage.getItem(key) === "1");
    btn.addEventListener("click", () => {
      const next = !document.body.classList.contains("sidebar-hidden");
      localStorage.setItem(key, next ? "1" : "0");
      apply(next);
    });
  }
  ensureHideSidebar();

  const overlay = document.getElementById("how-overlay");
  document.getElementById("see-how")?.addEventListener("click", () => {
    overlay?.classList.remove("hidden");
  });
  document.getElementById("how-close")?.addEventListener("click", () => {
    overlay?.classList.add("hidden");
  });
  overlay?.addEventListener("click", (event) => {
    if (event.target === overlay) overlay.classList.add("hidden");
  });

  const menu = document.getElementById("ws-menu");
  const backdrop = document.getElementById("ws-backdrop");
  const closeNav = () => document.body.classList.remove("nav-open");
  menu?.addEventListener("click", () => document.body.classList.toggle("nav-open"));
  backdrop?.addEventListener("click", closeNav);

  document.getElementById("settings-logout")?.addEventListener("click", async () => {
    const btn = document.getElementById("settings-logout");
    if (btn) btn.disabled = true;
    try {
      await fetch("/auth/logout", { method: "POST", headers: authHeaders() });
    } catch (err) { /* still sign out locally */ }
    clearAuth();
    window.location.replace("/login");
  });
})();
