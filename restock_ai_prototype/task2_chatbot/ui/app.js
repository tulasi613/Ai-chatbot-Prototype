/* ==========================================================
   Smart Restock AI — chat client
   Renders the block-structured turns returned by POST /api/chat
   and mirrors the database side-effects in the live system panel.
   ========================================================== */
const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");
const quickEl = $("#quickReplies");

let sessionId = null;
let knownAlertIds = new Set();
let firstLoad = true;
let renderCounter = 0;
const paneSignatures = {}; // avoids re-rendering (and re-animating) unchanged panels

/* ------------------------------------------------------- transport */
async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: "Bad JSON from server" }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

/* ------------------------------------------------------- helpers */
function el(tag, cls, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

/** Tiny markdown: **bold**, _italic_, bullet lines. */
function md(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/_(.+?)_/g, "<em>$1</em>")
    .replace(/\n/g, "<br/>");
}

function money(value) {
  return "$" + Number(value).toFixed(2);
}

function scrollDown() {
  requestAnimationFrame(() => (messagesEl.scrollTop = messagesEl.scrollHeight));
}

/* ------------------------------------------------------- message rows */
function addRow(who, nodes) {
  const row = el("div", `row ${who}`);
  row.appendChild(el("div", "avatar", who === "user" ? "You" : "SR"));
  const stack = el("div", "stack");
  nodes.forEach((n) => stack.appendChild(n));
  row.appendChild(stack);
  messagesEl.appendChild(row);
  scrollDown();
  return row;
}

function addUser(text) {
  addRow("user", [el("div", "bubble", md(text))]);
}

function addTyping() {
  return addRow("bot", [
    el("div", "bubble", '<span class="typing"><i></i><i></i><i></i></span>'),
  ]);
}

/* ------------------------------------------------------- block renderers */
function renderBlock(block) {
  switch (block.type) {
    case "text":
      return el("div", "bubble", md(block.text));

    case "product": {
      const inStock = block.stock_level > 0;
      const card = el("div", "card product-card");
      card.innerHTML = `
        <img class="thumb" src="${esc(block.image_url)}" alt="" onerror="this.style.visibility='hidden'"/>
        <div class="meta">
          <div class="name">${esc(block.name)}</div>
          <div class="sub">${esc(block.category)} · ${money(block.price)}</div>
        </div>
        <span class="pill ${inStock ? "" : "out"}">${
          inStock ? block.stock_level + " in stock" : "Out of stock"
        }</span>`;
      return card;
    }

    case "prediction":
      return renderPrediction(block);

    case "alternatives": {
      const wrap = el("div", "alts");
      block.items.forEach((item) => wrap.appendChild(renderAlternative(item)));
      return wrap;
    }

    case "subscribe_form":
      return renderSubscribeForm(block);

    case "subscription_confirmed": {
      const card = el("div", "card confirm");
      card.innerHTML = `
        <div class="tick">✓</div>
        <div>
          <div><strong>${esc(block.channel === "email" ? "Email" : "SMS")} alert saved</strong>
            — ${esc(block.contact)}</div>
          <div class="small muted">Row #${block.subscription_id} in customer_subscriptions ·
            ${block.total_waiting} customer${block.total_waiting === 1 ? "" : "s"} waiting on
            ${esc(block.product_name)}</div>
        </div>`;
      return card;
    }

    case "catalog": {
      const wrap = el("div", "catalog");
      block.items.forEach((item) => {
        const pct = Math.min(100, (item.score / item.threshold) * 100);
        const row = el("div", "catalog-row");
        row.innerHTML = `
          <span class="name">${esc(item.name)}</span>
          <span class="small muted">${item.score} / ${item.threshold}</span>
          <span class="meter"><i style="width:${pct}%"></i></span>`;
        row.onclick = () => send(`When will ${item.name} be back in stock?`);
        wrap.appendChild(row);
      });
      return wrap;
    }

    default:
      return el("div", "bubble", md(JSON.stringify(block)));
  }
}

function renderPrediction(block) {
  const card = el("div", "card prediction");
  const pct = block.confidence_pct;
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const dash = (pct / 100) * circumference;
  const gradientId = `ring-${++renderCounter}`; // unique per card: duplicate SVG ids break gradients

  card.innerHTML = `
    <div class="pred-top">
      <div>
        <div class="eta">
          <span class="num">${block.min_days}–${block.max_days}</span>
          <span class="unit">days until restock</span>
        </div>
        <div class="eta-date">Window: ${esc(block.eta_from)} → ${esc(block.eta_to)}
          · via ${esc(block.supplier_name)}</div>
      </div>
      <div class="ring">
        <svg width="86" height="86">
          <circle cx="43" cy="43" r="${radius}" fill="none" stroke="#253158" stroke-width="7"/>
          <circle cx="43" cy="43" r="${radius}" fill="none" stroke="url(#${gradientId})" stroke-width="7"
                  stroke-linecap="round" stroke-dasharray="${dash} ${circumference}"/>
          <defs><linearGradient id="${gradientId}" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#35d0a5"/><stop offset="100%" stop-color="#6c8cff"/>
          </linearGradient></defs>
        </svg>
        <div class="val">${pct}%<small>confidence</small></div>
      </div>
    </div>`;

  const details = el("details", "factors");
  details.appendChild(el("summary", null, "How this prediction was made"));
  block.factors.forEach((factor) => {
    const icon = { positive: "▲", negative: "▼", neutral: "•" }[factor.impact] || "•";
    const colour = { positive: "#35d0a5", negative: "#ffb84d", neutral: "#94a0c4" }[factor.impact];
    const row = el("div", "factor");
    row.innerHTML = `
      <span class="ico" style="color:${colour}">${icon}</span>
      <span>
        <span class="lbl">${esc(factor.label)}</span>
        <span class="det">${esc(factor.detail)}</span>
      </span>
      <span class="amt">${esc(factor.value || "")}</span>`;
    details.appendChild(row);
  });
  card.appendChild(details);
  return card;
}

function renderAlternative(item) {
  const node = el("div", "alt");
  node.innerHTML = `
    <img class="thumb" src="${esc(item.image_url)}" alt="" onerror="this.style.visibility='hidden'"/>
    <div class="meta">
      <div class="name">${esc(item.name)}</div>
      <div class="small muted">${money(item.price)} · ${item.stock_level} in stock</div>
      <div class="reasons">${item.reasons
        .map((r) => `<span class="tag">${esc(r)}</span>`)
        .join("")}</div>
    </div>
    <div class="match">
      <div class="pct">${item.match_score}%</div>
      <div class="bar"><i style="width:${item.match_score}%"></i></div>
      <div class="lbl">MATCH</div>
    </div>`;
  node.title =
    `vector similarity ${item.breakdown.vector_similarity}% · ` +
    `attribute overlap ${item.breakdown.attribute_overlap}% · ` +
    `price closeness ${item.breakdown.price_closeness}%`;
  node.onclick = () => send(`Is ${item.name} available?`);
  return node;
}

function renderSubscribeForm(block) {
  const card = el("div", "card sub-form");
  card.innerHTML = `
    <div class="small muted">Notify me when <strong>${esc(block.product_name)}</strong> is back</div>
    <div class="inputs">
      <input type="email" placeholder="you@example.com" />
      <input type="tel" placeholder="+1 555 0100 (optional)" />
      <button class="btn primary" type="button">Notify me</button>
    </div>`;
  const [emailInput, phoneInput] = card.querySelectorAll("input");
  const button = card.querySelector("button");

  const submit = async () => {
    const email = emailInput.value.trim();
    const phone = phoneInput.value.trim();
    if (!email && !phone) {
      emailInput.focus();
      return;
    }
    button.disabled = true;
    addUser(email || phone);
    const typing = addTyping();
    try {
      const data = await api("/api/chat/subscribe", "POST", {
        product_id: block.product_id,
        email,
        phone,
      });
      typing.remove();
      addRow("bot", [
        el("div", "bubble", md(data.message)),
        renderBlock({
          type: "subscription_confirmed",
          subscription_id: data.subscription_id,
          product_id: data.product_id,
          product_name: data.product_name,
          contact: data.email || data.phone,
          channel: data.email ? "email" : "sms",
          total_waiting: data.total_waiting,
        }),
      ]);
      if (data.admin_alert) {
        toast("Admin demand alert", data.admin_alert.alert_message);
      }
      refreshSystem();
    } catch (err) {
      typing.remove();
      addRow("bot", [el("div", "bubble", md(err.message))]);
      button.disabled = false;
    }
  };

  button.onclick = submit;
  [emailInput, phoneInput].forEach((input) => {
    input.onkeydown = (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    };
  });
  return card;
}

/* ------------------------------------------------------- conversation loop */
function renderQuickReplies(list) {
  quickEl.innerHTML = "";
  (list || []).forEach((qr) => {
    const button = el("button", `qr ${qr.style === "primary" ? "primary" : ""}`, esc(qr.label));
    button.onclick = () => send(qr.message);
    quickEl.appendChild(button);
  });
}

async function send(text, opts = {}) {
  if (!text || !text.trim()) return;
  if (!opts.silent) addUser(text);
  quickEl.innerHTML = "";
  $("#input").value = "";

  const typing = addTyping();
  try {
    const turn = await api("/api/chat", "POST", { session_id: sessionId, message: text });
    sessionId = turn.session_id;
    await new Promise((r) => setTimeout(r, 320)); // human-feeling pause
    typing.remove();

    addRow("bot", turn.reply.map(renderBlock));
    renderQuickReplies(turn.quick_replies);

    (turn.events || []).forEach((event) => {
      if (event.type === "admin_alert") {
        toast(
          event.is_new ? "New admin demand alert" : "Demand alert updated",
          event.message
        );
      }
    });
    refreshSystem();
  } catch (err) {
    typing.remove();
    addRow("bot", [
      el("div", "bubble", md(`I hit a problem talking to the server: ${err.message}`)),
    ]);
  }
}

/* ------------------------------------------------------- live system panel */
async function refreshSystem() {
  try {
    const [alertData, demandData, subData] = await Promise.all([
      api("/api/admin/alerts"),
      api("/api/admin/demand"),
      api("/api/admin/subscriptions?limit=12"),
    ]);

    // --- stats
    $("#statAlerts").textContent = alertData.alerts.length;
    $("#statWaiting").textContent = subData.subscriptions.filter((s) => !s.notified).length;
    $("#statOos").textContent = demandData.demand.length;

    // --- demand log pane (alerts on top, then live demand meters)
    if (changed("demand", [alertData.alerts, demandData.demand])) {
      const pane = $("#pane-demand");
      pane.innerHTML = "";
      if (!alertData.alerts.length) {
        pane.appendChild(
          el("div", "empty", "No open alerts. Ask about an out-of-stock item to build demand.")
        );
      }
      alertData.alerts.forEach((alert) => {
        const isNew = !firstLoad && !knownAlertIds.has(alert.alert_id);
        const card = el("div", `alert-card ${isNew ? "flash" : ""}`);
        card.innerHTML = `
          <div class="head">
            <span class="title">${esc(alert.product_name)}</span>
            <span class="score">demand ${alert.interest_count}</span>
          </div>
          <div class="msg">${esc(alert.alert_message)}</div>`;
        pane.appendChild(card);
      });
      knownAlertIds = new Set(alertData.alerts.map((a) => a.alert_id));

      pane.appendChild(el("div", "small muted", "Live demand score by product"));
      demandData.demand.forEach((row) => {
        const pct = Math.min(100, (row.score / row.threshold) * 100);
        const node = el("div", `demand-row ${row.alerting ? "alerting" : ""}`);
        node.innerHTML = `
          <div class="top"><span>${esc(row.name)}</span>
            <span class="${row.alerting ? "score" : "muted small"}">${row.score} / ${row.threshold}</span></div>
          <div class="sub">${row.queries} chat quer${row.queries === 1 ? "y" : "ies"}
            · ${row.subscriptions} subscription${row.subscriptions === 1 ? "" : "s"}</div>
          <div class="bar"><i style="width:${pct}%"></i></div>`;
        pane.appendChild(node);
      });
    }

    // --- subscriptions pane
    if (changed("subs", subData.subscriptions)) {
      const subPane = $("#pane-subs");
      subPane.innerHTML = "";
      if (!subData.subscriptions.length) {
        subPane.appendChild(el("div", "empty", "No subscriptions captured yet."));
      }
      subData.subscriptions.forEach((sub) => {
        const row = el("div", "sub-row");
        row.innerHTML = `
          <span class="who">${esc(sub.customer_email || sub.customer_phone)}
            <div class="for">${esc(sub.product_name)}</div></span>
          <span class="pill ${sub.notified ? "" : "warn"}">${sub.notified ? "notified" : "waiting"}</span>`;
        subPane.appendChild(row);
      });
    }

    // --- restock dropdown (keeps whatever the admin already selected)
    const options = demandData.demand.map((row) => [row.product_id, row.name]);
    if (changed("restock", options)) {
      const select = $("#restockProduct");
      const current = select.value;
      select.innerHTML = options
        .map(([id, name]) => `<option value="${id}">${esc(name)}</option>`)
        .join("");
      if (current && options.some(([id]) => String(id) === current)) select.value = current;
    }

    firstLoad = false;
  } catch (err) {
    console.warn("system refresh failed", err);
  }
}

/** True when a panel's data differs from what's already on screen. */
function changed(key, data) {
  const signature = JSON.stringify(data);
  if (paneSignatures[key] === signature) return false;
  paneSignatures[key] = signature;
  return true;
}

function toast(title, detail) {
  const node = el("div", "toast");
  node.innerHTML = `<div class="t">${esc(title)}</div><div class="d">${esc(detail)}</div>`;
  $("#toasts").appendChild(node);
  setTimeout(() => node.remove(), 7000);
}

/* ------------------------------------------------------- admin restock */
$("#restockBtn").onclick = async () => {
  const productId = Number($("#restockProduct").value);
  const qty = Number($("#restockQty").value);
  if (!productId || !qty) return;

  const out = $("#restockResult");
  out.innerHTML = '<div class="small muted">Restocking…</div>';
  try {
    const data = await api("/api/admin/restock", "POST", {
      product_id: productId,
      new_stock_level: qty,
    });
    out.innerHTML = `<div class="notify-out"><div class="small muted">
      ${esc(data.product_name)} set to ${data.new_stock_level} units ·
      ${data.notified_count} customer${data.notified_count === 1 ? "" : "s"} notified ·
      ${data.alerts_resolved} alert${data.alerts_resolved === 1 ? "" : "s"} resolved</div></div>`;
    const wrap = out.querySelector(".notify-out");
    data.notifications.forEach((note) => {
      wrap.appendChild(
        el(
          "div",
          "notify-msg",
          `<span class="to">${esc(note.channel)} → ${esc(note.to)}</span><br/>${esc(note.body)}`
        )
      );
    });
    toast("Restock complete", `${data.product_name}: ${data.notified_count} customers notified`);
    refreshSystem();
  } catch (err) {
    out.innerHTML = `<div class="small" style="color:var(--bad)">${esc(err.message)}</div>`;
  }
};

$("#resetBtn").onclick = async () => {
  if (!confirm("Rebuild the demo database from the seed data?")) return;
  await api("/api/admin/reset", "POST", {});
  sessionId = null;
  knownAlertIds = new Set();
  firstLoad = true;
  messagesEl.innerHTML = "";
  $("#restockResult").innerHTML = "";
  boot();
};

/* ------------------------------------------------------- tabs + composer */
$("#tabs").onclick = (event) => {
  const tab = event.target.closest(".tab");
  if (!tab) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  document
    .querySelectorAll(".tab-pane")
    .forEach((p) => p.classList.toggle("active", p.id === `pane-${tab.dataset.tab}`));
};

$("#composer").onsubmit = (event) => {
  event.preventDefault();
  send($("#input").value);
};

/* ------------------------------------------------------- guided demo
   Open /?demo=1 to watch the whole Task-2 flow play itself out:
   prediction -> explanation -> alternatives -> subscription -> admin alert. */
const DEMO_SCRIPT = [
  "When will the Smart Fitness Watch be back in stock?",
  "How did you predict that?",
  "Show me alternatives",
  "Notify me at priya.sharma@example.com",
];

async function playDemo() {
  for (const line of DEMO_SCRIPT) {
    await new Promise((r) => setTimeout(r, 1800));
    await send(line);
  }
}

/* ------------------------------------------------------- boot */
async function boot() {
  try {
    const health = await api("/api/health");
    const chip = $("#engineChip");
    chip.classList.add(health.ok ? "ok" : "err");
    $("#engineText").textContent = `${health.engine.toUpperCase()} · ${
      health.row_counts.products
    } products`;
  } catch {
    $("#engineChip").classList.add("err");
    $("#engineText").textContent = "backend unreachable";
  }

  await refreshSystem();
  await send("hi", { silent: true }); // opening greeting, without a fake user turn

  if (new URLSearchParams(location.search).has("demo")) playDemo();
}

boot();
setInterval(refreshSystem, 6000);
