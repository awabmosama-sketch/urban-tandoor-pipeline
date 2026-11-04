/* ============================================================
   Urban Tandoor — frontend behaviour
   No frameworks, no bundler. Talks to the FastAPI service.
   ============================================================ */
(() => {
  "use strict";

  const API = "/api/v1";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    categories: [],
    items: [],
    branches: [],
    activeCategory: "all",
    branchId: null,
    dishId: null,
    history: [],
    busy: false,
  };

  /* ---------------- helpers ---------------- */

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);

  const money = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString("en-PK", { maximumFractionDigits: 0 });
  };

  const slug = (s) => String(s || "").trim().toLowerCase();

  let toastTimer = null;
  function toast(message) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 4200);
  }

  async function api(path, options = {}) {
    const { headers, ...rest } = options;
    const res = await fetch(`${API}${path}`, {
      ...rest,
      headers: { Accept: "application/json", ...(headers || {}) },
    });
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        if (body && body.detail) {
          detail = typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
        }
      } catch { /* non-JSON error body */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function countUp(el, target) {
    if (!el) return;
    const end = Number(target);
    if (!Number.isFinite(end)) { el.textContent = "—"; return; }
    const start = performance.now();
    const dur = 900;
    const from = 0;
    const final = end.toLocaleString("en-PK");
    function frame(now) {
      const p = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(from + (end - from) * eased).toLocaleString("en-PK");
      if (p < 1) requestAnimationFrame(frame);
    }
    if (document.hidden) { el.textContent = final; return; }
    requestAnimationFrame(frame);
    setTimeout(() => {
      if (el.textContent === "—") el.textContent = final;
    }, 1200);
  }

  /* ---------------- ambience: clock, glow, reveal ---------------- */

  function startClock() {
    const el = $("#clock");
    if (!el) return;
    const tick = () => {
      const now = new Date();
      el.textContent = now.toLocaleTimeString("en-GB", {
        hour: "2-digit", minute: "2-digit",
      });
      el.setAttribute("datetime", now.toISOString());
    };
    tick();
    setInterval(tick, 15000);
  }

  function startGlow() {
    const glow = $("#emberGlow");
    if (!glow || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = null;
    let tx = -300, ty = -300;
    window.addEventListener("pointermove", (e) => {
      tx = e.clientX;
      ty = e.clientY;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        glow.style.transform = `translate(${tx}px, ${ty}px)`;
        raf = null;
      });
    }, { passive: true });
  }

  function startReveal() {
    const nodes = $$(".reveal");
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((n) => n.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    nodes.forEach((n) => io.observe(n));
  }

  /* ---------------- menu ---------------- */

  function renderChips() {
    const wrap = $("#categoryChips");
    if (!wrap) return;
    const counts = new Map();
    state.items.forEach((item) => {
      counts.set(item.category, (counts.get(item.category) || 0) + 1);
    });

    const chips = [{
      name: "all",
      label: "Everything",
      count: state.items.length,
    }].concat(
      state.categories
        .filter((c) => counts.has(c.category_name))
        .map((c) => ({
          name: c.category_name,
          label: c.category_name,
          count: counts.get(c.category_name),
        }))
    );

    wrap.innerHTML = chips.map((chip) => `
      <button class="chip" type="button" data-category="${esc(chip.name)}"
        aria-pressed="${chip.name === state.activeCategory}">
        ${esc(chip.label)}<sup>${chip.count}</sup>
      </button>
    `).join("");

    wrap.onclick = (e) => {
      const btn = e.target.closest(".chip");
      if (!btn) return;
      state.activeCategory = btn.dataset.category;
      $$(".chip", wrap).forEach((c) =>
        c.setAttribute("aria-pressed", String(c.dataset.category === state.activeCategory))
      );
      renderMenu();
    };
  }

  function visibleItems() {
    if (state.activeCategory === "all") return state.items;
    return state.items.filter((i) => i.category === state.activeCategory);
  }

  function renderMenu() {
    const list = $("#menuList");
    if (!list) return;
    const items = visibleItems();
    if (!items.length) {
      list.innerHTML = `<p class="empty">Nothing in this part of the ledger.</p>`;
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <button class="dish" type="button" data-menu-id="${esc(item.menu_id)}">
        <span class="dish-index">${String(index + 1).padStart(2, "0")}</span>
        <span>
          <span class="dish-name">${esc(item.item_name)}</span>
          <span class="dish-cat">${esc(item.category)} · ${esc(item.prep_time_min)} min</span>
        </span>
        <span class="dish-leader" aria-hidden="true"></span>
        <span class="dish-price">${money(item.base_price_pkr)}<small>${esc(item.currency || "PKR")}</small></span>
      </button>
    `).join("");

    list.onclick = (event) => {
      const btn = event.target.closest("[data-menu-id]");
      if (!btn) return;
      openDish(btn.dataset.menuId);
    };
  }

  /* ---------------- dish sheet ---------------- */

  const AVAIL_LABEL = {
    AVAILABLE: "available tonight",
    UNAVAILABLE: "out of stock",
    NO_RECIPE: "recipe not costed",
    NOT_ACTIVE: "not on the menu",
  };

  async function openDish(menuId) {
    state.dishId = menuId;
    const dialog = $("#dishDialog");
    const body = $("#dishBody");
    if (!dialog || !body) return;

    body.innerHTML = `<p class="empty">Reading the passport…</p>`;
    if (!dialog.open) dialog.showModal();

    try {
      const requests = [
        api(`/menu/items/${encodeURIComponent(menuId)}`),
        api(`/menu/items/${encodeURIComponent(menuId)}/addons`).catch(() => []),
      ];
      if (state.branchId) {
        requests.push(
          api(`/inventory/availability/${encodeURIComponent(menuId)}?branch_id=${encodeURIComponent(state.branchId)}`)
            .catch(() => null)
        );
      }

      const [detail, addons, availability] = await Promise.all(requests);
      const branch = state.branches.find((b) => b.branch_id === state.branchId);

      const facts = [
        detail.item_type,
        `${detail.prep_time_min} min`,
        detail.service_window,
        detail.dietary_hint,
        detail.allergen_hint ? `allergens: ${detail.allergen_hint}` : null,
      ].filter(Boolean);

      const variants = (detail.variants || []).map((v) => `
        <div class="variant">
          <span>${esc(v.variant_name)}
            ${v.approved_for_orders ? "" : "<small>not orderable</small>"}
          </span>
          <b>${money(v.price_pkr)}</b>
        </div>
      `).join("");

      const addonPills = (addons || []).map((a) => `
        <span>${esc(a.addon_name)}<i>+${money(a.price_pkr)}</i></span>
      `).join("");

      let availabilityHtml = "";
      if (availability) {
        const portions = Number(availability.max_portions) || 0;
        availabilityHtml = `
          <div class="avail-box" data-status="${esc(availability.status)}">
            <b>${portions}</b>
            <p>${esc(AVAIL_LABEL[availability.status] || availability.status)}
              ${branch ? `· ${esc(branch.branch_name)}` : ""}</p>
            <p>${esc(availability.reason || "Estimated from today's recipe and branch stock.")}</p>
          </div>
        `;
      }

      body.innerHTML = `
        <p class="sheet-kicker">${esc(detail.menu_id)} · ${esc(detail.category)}</p>
        <h3 class="sheet-title">${esc(detail.item_name)}</h3>
        <p class="sheet-price">${money(detail.base_price_pkr)} <small>${esc(detail.currency || "PKR")} · base</small></p>
        ${detail.description ? `<p class="sheet-desc">${esc(detail.description)}</p>` : ""}
        <div class="sheet-facts">${facts.map((f) => `<span>${esc(f)}</span>`).join("")}</div>
        ${variants ? `<p class="sheet-sub">Portions</p>${variants}` : ""}
        ${addonPills ? `<p class="sheet-sub">Add to it</p><div class="addon-pills">${addonPills}</div>` : ""}
        ${availabilityHtml}
      `;
    } catch (err) {
      body.innerHTML = `<p class="empty">Could not open this dish: ${esc(err.message)}</p>`;
    }
  }

  function closeDish() {
    const dialog = $("#dishDialog");
    if (dialog && dialog.open) dialog.close();
  }

  /* ---------------- supply ---------------- */

  function renderBranchOptions() {
    const sel = $("#branchSelect");
    if (!sel) return;
    sel.innerHTML = state.branches.map((b) => `
      <option value="${esc(b.branch_id)}">${esc(b.branch_name)}</option>
    `).join("");
    if (state.branches.length) {
      state.branchId = state.branchId || state.branches[0].branch_id;
      sel.value = state.branchId;
    }
  }

  function renderDishOptions() {
    const sel = $("#dishSelect");
    if (!sel) return;
    sel.innerHTML = state.items.map((i) => `
      <option value="${esc(i.menu_id)}">${esc(i.item_name)}</option>
    `).join("");
    if (state.items.length) {
      state.dishId = state.dishId || state.items[0].menu_id;
      sel.value = state.dishId;
    }
  }

  async function loadSupply() {
    if (!state.branchId) return;
    loadLowStock();
    loadAvailability();
  }

  async function loadLowStock() {
    const list = $("#lowStock");
    if (!list) return;
    list.innerHTML = `<li class="empty">Reading stock…</li>`;
    try {
      const stock = await api(
        `/inventory/branches/${encodeURIComponent(state.branchId)}/stock?limit=500`
      );
      const low = stock
        .filter((s) => s.stock_status && s.stock_status !== "OK")
        .sort((a, b) => (Number(a.available) || 0) - (Number(b.available) || 0))
        .slice(0, 7);

      if (!low.length) {
        list.innerHTML = `<li class="empty">Everything is comfortably stocked.</li>`;
        return;
      }
      list.innerHTML = low.map((s) => `
        <li>
          <span>${esc(s.ingredient_name)}
            <em>${esc(s.stock_status)}</em>
          </span>
          <span>${Number(s.available).toFixed(1)} ${esc(s.unit)}</span>
        </li>
      `).join("");
    } catch (err) {
      list.innerHTML = `<li class="empty">Stock unavailable: ${esc(err.message)}</li>`;
    }
  }

  async function loadAvailability() {
    const gauge = $("#gauge");
    const number = $("#portions");
    const status = $("#portionStatus");
    const detail = $("#portionDetail");
    const bar = $("#portionBar");
    if (!gauge || !state.branchId || !state.dishId) return;

    gauge.dataset.status = "idle";
    if (status) status.textContent = "reading the pass…";
    if (detail) detail.textContent = "";
    if (bar) bar.style.width = "0%";

    try {
      const a = await api(
        `/inventory/availability/${encodeURIComponent(state.dishId)}?branch_id=${encodeURIComponent(state.branchId)}`
      );
      const portions = Number(a.max_portions) || 0;
      const branch = state.branches.find((b) => b.branch_id === state.branchId);
      const dish = state.items.find((i) => i.menu_id === state.dishId);

      gauge.dataset.status = a.status === "AVAILABLE" ? "ok" : "no";
      if (number) countUp(number, portions);
      if (status) {
        status.textContent = `${AVAIL_LABEL[a.status] || a.status}${branch ? ` · ${branch.branch_name}` : ""}`;
      }
      if (detail) {
        detail.textContent = a.reason
          || `${dish ? dish.item_name : "This dish"} — estimated from the recipe and today's ${branch ? branch.branch_name : "branch"} stock.`;
      }
      if (bar) {
        const cap = Math.max(20, Math.min(60, portions * 2 || 20));
        bar.style.width = `${Math.min(100, Math.round((portions / cap) * 100))}%`;
      }
    } catch (err) {
      gauge.dataset.status = "no";
      if (number) number.textContent = "—";
      if (status) status.textContent = "not available";
      if (detail) detail.textContent = err.message;
    }
  }

  /* ---------------- archive search ---------------- */

  function highlight(text, query) {
    const safe = esc(text);
    const terms = query.split(/\s+/).map((t) => t.trim()).filter((t) => t.length > 2);
    if (!terms.length) return safe;
    const pattern = new RegExp(
      `(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
      "gi"
    );
    return safe.replace(pattern, "<mark>$1</mark>");
  }

  async function runSearch(query) {
    const box = $("#searchResults");
    if (!box) return;
    const q = query.trim();
    if (!q) {
      box.innerHTML = `<p class="empty">Type a few words first.</p>`;
      return;
    }

    box.innerHTML = `<p class="empty">Listening for “${esc(q)}” in the kitchen notes…</p>`;
    try {
      const data = await api("/search/semantic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, top_k: 6, min_score: 0 }),
      });

      if (!data.results || !data.results.length) {
        box.innerHTML = `<p class="empty">No notes matched “${esc(q)}”. Try another phrase.</p>`;
        return;
      }

      const max = Math.max(...data.results.map((r) => Number(r.score) || 0), 0.0001);
      box.innerHTML = `
        <p class="results-head">${data.count} passage${data.count === 1 ? "" : "s"} · ranked by meaning</p>
        ${data.results.map((r) => {
          const score = Math.max(0, Number(r.score) || 0);
          const width = Math.max(4, Math.round((score / max) * 100));
          return `
            <article class="result">
              <div class="result-score">${score.toFixed(3)}<i style="--w:${width}%"></i></div>
              <div>
                <p class="result-meta">
                  ${esc(r.document_title || r.document_id)}
                  ${r.section ? ` · ${esc(r.section)}` : ""}
                </p>
                <p class="result-text">${highlight(r.content, q)}</p>
              </div>
            </article>
          `;
        }).join("")}
      `;
    } catch (err) {
      box.innerHTML = `<p class="empty">Search failed: ${esc(err.message)}</p>`;
    }
  }

  /* ---------------- concierge ---------------- */

  const SUGGESTIONS = [
    "What should I order for two?",
    "Which dishes are running low tonight?",
    "Something smoky and not too spicy.",
    "What can I get for breakfast at 4am?",
  ];

  function renderSuggestions() {
    const wrap = $("#suggestions");
    if (!wrap) return;
    wrap.innerHTML = SUGGESTIONS.map((s) => `
      <button type="button">${esc(s)}</button>
    `).join("");
    wrap.onclick = (e) => {
      const btn = e.target.closest("button");
      if (!btn || state.busy) return;
      const input = $("#chatInput");
      if (input) input.value = btn.textContent.trim();
      sendChat();
    };
  }

  function addMessage(role, text, { error = false, typing = false } = {}) {
    const box = $("#messages");
    if (!box) return null;
    const el = document.createElement("div");
    el.className = `msg ${role}${error ? " error" : ""}${typing ? " typing" : ""}`;
    el.innerHTML = `
      <span class="msg-label">${role === "user" ? "You" : "Concierge"}</span>
      <p></p>
    `;
    const p = $("p", el);
    if (role === "assistant") {
      p.innerHTML = formatRich(text);
    } else {
      p.textContent = text;
    }
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  function formatRich(text) {
    return esc(text)
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  }

  async function sendChat() {
    if (state.busy) return;
    const input = $("#chatInput");
    const form = $("#chatForm");
    const button = form ? $("button", form) : null;
    if (!input) return;

    const message = input.value.trim();
    if (!message) return;

    addMessage("user", message);
    state.history.push({ role: "user", content: message });
    input.value = "";
    input.style.height = "auto";
    state.busy = true;
    if (button) button.disabled = true;

    const typing = addMessage("assistant", "consulting the pass", { typing: true });

    try {
      const data = await api("/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history: state.history.slice(-8),
          branch_id: state.branchId || null,
        }),
      });
      if (typing) typing.remove();
      addMessage("assistant", data.reply);
      state.history.push({ role: "assistant", content: data.reply });
    } catch (err) {
      if (typing) typing.remove();
      addMessage("assistant", err.message, { error: true });
    } finally {
      state.busy = false;
      if (button) button.disabled = false;
      input.focus();
    }
  }

  /* ---------------- ops ---------------- */

  function setOpsOpen(open) {
    document.body.classList.toggle("ops-open", open);
    const panel = $("#opsPanel");
    if (panel) panel.setAttribute("aria-hidden", String(!open));
  }

  async function refreshDomain(domain) {
    const token = ($("#opsToken")?.value || "").trim();
    const jobBox = $("#opsJob");
    const buttons = $$(".ops-buttons button");
    if (!token) { toast("Add the admin token first."); return; }

    buttons.forEach((b) => { b.disabled = true; });
    if (jobBox) jobBox.textContent = `Queueing ${domain} refresh…`;

    try {
      const job = await api(`/admin/refresh/${encodeURIComponent(domain)}`, {
        method: "POST",
        headers: { "X-Admin-Token": token },
      });
      if (jobBox) jobBox.textContent = `Job ${job.job_id} · ${job.domain} · ${job.status}`;
      toast(`${domain} refresh queued.`);

      let attempts = 0;
      const timer = setInterval(async () => {
        attempts += 1;
        try {
          const status = await api(`/admin/jobs/${encodeURIComponent(job.job_id)}`, {
            headers: { "X-Admin-Token": token },
          });
          if (jobBox) {
            jobBox.textContent =
              `Job ${status.job_id}\n` +
              `${status.domain} · ${status.status}\n` +
              (status.error ? `error: ${status.error}` : JSON.stringify(status.result || {}, null, 0));
          }
          if (["success", "error"].includes(status.status) || attempts > 45) {
            clearInterval(timer);
            buttons.forEach((b) => { b.disabled = false; });
            if (status.status === "success") {
              toast(`${domain} refresh finished.`);
              await boot({ silent: true });
            }
          }
        } catch (err) {
          clearInterval(timer);
          buttons.forEach((b) => { b.disabled = false; });
          if (jobBox) jobBox.textContent = `Job lookup failed: ${err.message}`;
        }
      }, 1200);
    } catch (err) {
      buttons.forEach((b) => { b.disabled = false; });
      if (jobBox) jobBox.textContent = err.message;
      toast(err.message);
    }
  }

  /* ---------------- boot ---------------- */

  async function loadStats() {
    try {
      const [health, branches] = await Promise.all([
        api("/search/health").catch(() => null),
        api("/inventory/branches").catch(() => []),
      ]);
      countUp($("#statItems"), state.items.length);
      countUp($("#statChunks"), health ? health.chunks_total : 0);
      countUp($("#statBranches"), branches.length);
    } catch {
      /* stats are decorative; never block the page */
    }
  }

  async function boot({ silent = false } = {}) {
    try {
      const [categories, items, branches] = await Promise.all([
        api("/menu/categories"),
        api("/menu/items?limit=500"),
        api("/inventory/branches"),
      ]);
      state.categories = categories;
      state.items = items;
      state.branches = branches;

      if (!state.items.some((i) => i.menu_id === state.dishId)) {
        state.dishId = state.items.length ? state.items[0].menu_id : null;
      }
      if (!state.branches.some((b) => b.branch_id === state.branchId)) {
        state.branchId = state.branches.length ? state.branches[0].branch_id : null;
      }

      renderChips();
      renderMenu();
      renderBranchOptions();
      renderDishOptions();
      await loadSupply();
      loadStats();
      if (!silent) toast("Ledger loaded from the live kitchen.");
    } catch (err) {
      const list = $("#menuList");
      if (list) list.innerHTML = `<p class="empty">Could not reach the kitchen: ${esc(err.message)}</p>`;
      toast(`Backend unreachable: ${err.message}`);
    }
  }

  function wire() {
    const branchSel = $("#branchSelect");
    if (branchSel) {
      branchSel.onchange = () => {
        state.branchId = branchSel.value;
        loadSupply();
        if (state.dishId && $("#dishDialog")?.open) openDish(state.dishId);
      };
    }

    const dishSel = $("#dishSelect");
    if (dishSel) {
      dishSel.onchange = () => {
        state.dishId = dishSel.value;
        loadAvailability();
      };
    }

    const searchForm = $("#searchForm");
    if (searchForm) {
      searchForm.onsubmit = (e) => {
        e.preventDefault();
        runSearch($("#searchInput")?.value || "");
      };
    }

    const chatForm = $("#chatForm");
    const chatInput = $("#chatInput");
    if (chatForm) {
      chatForm.onsubmit = (e) => { e.preventDefault(); sendChat(); };
    }
    if (chatInput) {
      chatInput.onkeydown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendChat();
        }
      };
      chatInput.oninput = () => {
        chatInput.style.height = "auto";
        chatInput.style.height = `${Math.min(120, chatInput.scrollHeight)}px`;
      };
    }

    $("#dishClose")?.addEventListener("click", closeDish);
    $("#dishDialog")?.addEventListener("click", (e) => {
      if (e.target.id === "dishDialog") closeDish();
    });

    $("#opsToggle")?.addEventListener("click", () => setOpsOpen(true));
    $("#opsClose")?.addEventListener("click", () => setOpsOpen(false));

    $$(".ops-buttons button").forEach((btn) => {
      btn.addEventListener("click", () => refreshDomain(btn.dataset.domain));
    });

    document.addEventListener("keydown", (e) => {
      const tag = (e.target.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "textarea" || tag === "select";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        $("#searchInput")?.focus();
      }
      if (e.key === "Escape") {
        setOpsOpen(false);
        closeDish();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    startClock();
    startGlow();
    startReveal();
    renderSuggestions();
    wire();
    boot();
  });
})();
