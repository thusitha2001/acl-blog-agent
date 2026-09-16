(function () {
  const form = document.getElementById("auth-form");
  if (!form) return;

  const nameEl = document.getElementById("auth-name");
  const passwordEl = document.getElementById("auth-password");
  const errorEl = document.getElementById("auth-error");
  const submitBtn = document.getElementById("auth-submit");
  const titleEl = document.getElementById("auth-title");
  const leadEl = document.getElementById("auth-lead");
  const kickerEl = document.getElementById("auth-kicker");
  let mode = "login";

  function setMode(next) {
    mode = next;
    document.querySelectorAll(".auth-tabs .tab-btn").forEach((btn) => {
      const active = btn.dataset.mode === mode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (mode === "signup") {
      kickerEl.textContent = "Get started";
      titleEl.textContent = "Create your workspace";
      leadEl.textContent = "Pick a name and password. You can log in from any browser on this app.";
      submitBtn.textContent = "Create account";
      passwordEl.autocomplete = "new-password";
    } else {
      kickerEl.textContent = "Welcome back";
      titleEl.textContent = "Log in to your workspace";
      leadEl.textContent = "Use your name and password to continue writing.";
      submitBtn.textContent = "Log in";
      passwordEl.autocomplete = "current-password";
    }
    errorEl.hidden = true;
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  document.querySelectorAll(".auth-tabs .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = nameEl.value.trim();
    const password = passwordEl.value;
    if (!name) {
      showError("Enter your name.");
      nameEl.focus();
      return;
    }
    if (password.length < 4) {
      showError("Password must be at least 4 characters.");
      passwordEl.focus();
      return;
    }
    showError("");
    submitBtn.disabled = true;
    try {
      const response = await fetch(mode === "signup" ? "/auth/signup" : "/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data.detail;
        throw new Error(
          (typeof detail === "string" && detail)
          || detail?.message
          || (mode === "signup" ? "Could not create that account." : "Invalid name or password.")
        );
      }
      window.BlogAgentAuth.set(data);
      const next = new URLSearchParams(location.search).get("next") || "/";
      const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";
      window.location.replace(safeNext === "/login" ? "/" : safeNext);
    } catch (err) {
      showError(err.message || "Could not log in.");
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
