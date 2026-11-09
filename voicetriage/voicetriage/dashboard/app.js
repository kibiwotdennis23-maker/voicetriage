"use strict";

const LABELS = { emergency: "EMERGENCY", today: "GO TODAY", within_3_days: "WITHIN 3 DAYS" };
const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("vt_token") || "";
let timer = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Authorization": "Bearer " + token, "Content-Type": "application/json" },
  });
  if (res.status === 401) {
    signOut("That token was not accepted.");
    throw new Error("unauthorised");
  }
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function minutesAgo(ts) {
  return Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
}

function card(alert) {
  const c = el("article", "card " + alert.level);
  const head = el("div", "head");
  head.append(
    el("span", "badge", LABELS[alert.level] || alert.level),
    el("span", "", "#" + alert.id + " · " + minutesAgo(alert.created_at) + " min ago · " + alert.facility)
  );
  c.append(head, el("h2", "", alert.group || "Patient group not given"));

  const list = el("ul");
  const signs = alert.reported.length ? alert.reported : ["No danger signs reported"];
  signs.forEach((s) => list.append(el("li", "", s)));
  c.append(list);

  const foot = el("div", "foot");
  const contact = el("span", "contact", "Caller " + alert.caller_masked);
  const show = el("button", "", "Show number");
  show.onclick = async () => {
    const data = await api("/api/alerts/" + alert.id + "/contact");  // logged server-side
    contact.textContent = "Caller " + data.number;
    show.remove();
  };
  foot.append(contact, show);
  if (alert.status === "new") {
    const ack = el("button", "primary", "Acknowledge");
    ack.onclick = async () => {
      await api("/api/alerts/" + alert.id + "/ack", { method: "POST", body: "{}" });
      refresh();
    };
    foot.append(ack);
  } else {
    foot.append(el("span", "", "Acknowledged"));
  }
  c.append(foot);
  return c;
}

async function refresh() {
  try {
    const all = $("showAll").checked ? "?include=all" : "";
    const data = await api("/api/alerts" + all);
    const items = data.alerts.length ? data.alerts.map(card) : [el("p", "empty", "No alerts right now.")];
    $("board").replaceChildren(...items);
    $("status").textContent = "Updated " + new Date().toLocaleTimeString();
  } catch (err) {
    if (token) $("status").textContent = "Could not refresh: " + err.message;
  }
}

function signIn() {
  $("login").hidden = true;
  $("board").hidden = false;
  $("signOut").hidden = false;
  refresh();
  timer = setInterval(refresh, 10000);
}

function signOut(message) {
  token = "";
  sessionStorage.removeItem("vt_token");
  clearInterval(timer);
  $("login").hidden = false;
  $("board").hidden = true;
  $("signOut").hidden = true;
  $("status").textContent = "";
  $("loginError").textContent = typeof message === "string" ? message : "";
}

$("login").addEventListener("submit", (event) => {
  event.preventDefault();
  token = $("token").value.trim();
  sessionStorage.setItem("vt_token", token);
  $("token").value = "";
  signIn();
});
$("signOut").addEventListener("click", () => signOut());
$("showAll").addEventListener("change", refresh);

if (token) signIn();
