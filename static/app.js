"use strict";

/* fashion·ai: one screen at a time.
   Routes: #/  ->  #/vibe/1..5  ->  #/swipe  ->  #/taste  ->  #/designing  ->  #/looks */

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const ORDER = ["upload", "vibe", "swipe", "taste", "designing", "looks"];

let S = null;                      // last /api/state
let intake = {};                   // question id -> [values]
let currentRoute = { name: "upload", index: 0 };
let renderChoice = "both";         // both | model id
const rendering = new Set();       // "look:model"
let pollTimer = null;

// ---------------------------------------------------------------------------
// helpers

async function api(path, body, method) {
  const opts = {};
  if (body instanceof FormData) Object.assign(opts, { method: "POST", body });
  else if (body !== undefined) Object.assign(opts, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (method) opts.method = method;
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const ICONS = {
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  heart: '<path d="M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 010 12h-3"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  image: '<rect x="4" y="4" width="16" height="16" rx="2"/><circle cx="9" cy="9" r="1.6"/><path d="M20 15l-5-5-9 9"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  sparkle: '<path d="M12 4v4M12 16v4M4 12h4M16 12h4M6.5 6.5l2.5 2.5M15 15l2.5 2.5M17.5 6.5L15 9M9 15l-2.5 2.5"/>',
};
const icon = (name) => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = ICONS[name]; return s; };

let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, isError ? 7000 : 2600);
}

const haptic = (ms = 12) => { try { navigator.vibrate?.(ms); } catch { /* not supported */ } };
const photoUrl = (name) => `/api/photos/${encodeURIComponent(name)}?s=${S.session.id}`;
const intakeComplete = () => S.intake_questions.every((q) => (intake[q.id] || []).length > 0);
const intakeSaved = () => S.intake_questions.every((q) => (S.session.intake_answers[q.id] || []).length > 0);
const anyJobRunning = () => Object.values(S.jobs).some((j) => j.state === "running");

/** A tap that triggers a paid re-run must be confirmed with a second tap. */
function confirmTap(button, label) {
  if (button.dataset.armed) { delete button.dataset.armed; return true; }
  const original = button.innerHTML;
  button.dataset.armed = "1";
  button.textContent = label;
  setTimeout(() => { if (button.dataset.armed) { delete button.dataset.armed; button.innerHTML = original; } }, 4000);
  return false;
}

// ---------------------------------------------------------------------------
// state + routing

async function refresh() {
  S = await api("/api/state");
  intake = { ...S.session.intake_answers, ...intake };
  $("#sheet-cost").textContent = `$${S.session_cost_usd.toFixed(3)}`;
  renderJobPill();
  clearTimeout(pollTimer);
  if (anyJobRunning()) pollTimer = setTimeout(onPoll, 3500);
  return S;
}

async function onPoll() {
  const before = JSON.stringify(S.jobs);
  await refresh().catch(() => {});
  if (JSON.stringify(S.jobs) === before) return;
  // A background job finished: refresh the screens that show its result.
  if (currentRoute.name === "taste") rerender();
  if (currentRoute.name === "designing" && S.jobs.styles.state !== "running") continueDesign();
}

function renderJobPill() {
  const pill = $("#job-pill");
  const a = S.jobs.analysis.state, st = S.jobs.styles.state;
  let text = "";
  if (a === "running") text = "Analyzing";
  else if (st === "running") text = "Styling";
  pill.hidden = !text || currentRoute.name === "designing";
  pill.textContent = text;
}

function parseRoute() {
  const [name = "", arg] = location.hash.replace(/^#\/?/, "").split("/");
  return { name: ORDER.includes(name) ? name : "upload", arg };
}

/** The furthest screen the user is allowed to be on, given what's done. */
function guard(route) {
  if (route.name !== "upload" && S.photos.length === 0) return { name: "upload" };
  if (["swipe", "taste", "designing", "looks"].includes(route.name) && !intakeSaved()) return { name: "vibe", arg: "1" };
  if (route.name === "looks" && !S.styles) return { name: "taste" };
  if (route.name === "designing" && S.styles && S.jobs.styles.state !== "running") return { name: "looks" };
  return route;
}

function go(hash) { if (location.hash === hash) show(); else location.hash = hash; }

function show() {
  const wanted = parseRoute();
  const route = guard(wanted);
  if (route.name !== wanted.name || (route.arg && route.arg !== wanted.arg)) {
    history.replaceState(null, "", `#/${route.name}${route.arg ? "/" + route.arg : ""}`);
  }
  const index = ORDER.indexOf(route.name) + (route.name === "vibe" ? (Number(route.arg || 1) - 1) / 10 : 0);
  const back = index < currentRoute.index;
  currentRoute = { ...route, index };
  const node = SCREENS[route.name](route.arg);
  node.classList.add("screen");
  if (back) node.classList.add("back");
  app.replaceChildren(node);
  window.scrollTo({ top: 0 });
  document.querySelectorAll(".dock").forEach((d) => d.remove());
  node._dock && document.body.append(node._dock);
  node._mounted?.();
  // chrome
  $("#nav-back").hidden = route.name === "upload" || route.name === "designing";
  const progress = { upload: 8, vibe: 14 + Number(route.arg || 1) * 5, swipe: 50, taste: 72, designing: 86, looks: 100 }[route.name];
  $("#bar-progress").style.width = `${progress}%`;
  renderJobPill();
}

function rerender() {
  const node = SCREENS[currentRoute.name](currentRoute.arg);
  node.classList.add("screen");
  node.style.animation = "none";
  app.replaceChildren(node);
  document.querySelectorAll(".dock").forEach((d) => d.remove());
  node._dock && document.body.append(node._dock);
  node._mounted?.();
}

function goBack() {
  const r = currentRoute;
  if (r.name === "vibe" && Number(r.arg) > 1) return go(`#/vibe/${Number(r.arg) - 1}`);
  const prev = { vibe: "#/", swipe: `#/vibe/${S.intake_questions.length}`, taste: "#/swipe", looks: "#/taste" }[r.name];
  if (prev) go(prev);
}

function dock(...children) { return h("div", { class: "dock" }, children); }

// ---------------------------------------------------------------------------
// 1. upload

function uploadScreen() {
  const count = S.photos.length;
  const fileInput = (capture) => h("input", {
    type: "file", accept: "image/*", multiple: capture ? null : true, capture: capture || null, hidden: true,
    onchange: (e) => { handleFiles([...e.target.files]); e.target.value = ""; },
  });
  const pick = fileInput(null), cam = fileInput("environment");

  const grid = count ? h("div", { class: "thumbs-grid" },
    S.photos.map((name) => h("div", { class: "thumb" },
      h("img", { src: photoUrl(name), alt: "" }),
      h("button", { class: "x", "aria-label": "Remove photo", onclick: () => removePhoto(name) }, icon("x")))),
    count < S.max_photos ? h("button", { class: "thumb add", "aria-label": "Add photos", onclick: () => pick.click() }, icon("plus")) : null)
    : null;

  const drop = h("div", { class: "drop", id: "drop" },
    h("p", { class: "h3" }, count ? "Add more photos" : "Add a photo of yourself"),
    h("p", { class: "small" }, "One is enough. A few angles helps."),
    h("div", { class: "drop-actions" },
      h("button", { class: "btn small", onclick: () => cam.click() }, icon("camera"), "Take a photo"),
      h("button", { class: "btn small ghost", onclick: () => pick.click() }, icon("image"), "Choose photos")));

  const node = h("section", { class: "upload-hero reveal" },
    h("p", { class: "eyebrow" }, "Your personal stylist"),
    h("h1", { class: "display" }, "Dress like the ", h("em", {}, "best"), " version of you."),
    h("p", { class: "lede" }, "Show us you, tell us your vibe, swipe through some clothes, and we'll style three looks on you."),
    grid, count ? null : drop, count && count < S.max_photos ? null : null,
    h("div", { class: "tip" }, h("span", {}, "✦"), h("span", {}, h("b", {}, "Best results: "), "a full-length photo in good light, nothing covering your face.")),
    pick, cam);
  if (count) node.insertBefore(h("p", { class: "eyebrow", style: "margin-top:6px" }, `${count} photo${count > 1 ? "s" : ""}`), grid);

  // desktop drag & drop onto the whole screen
  node.addEventListener("dragover", (e) => { e.preventDefault(); $("#drop")?.classList.add("over"); });
  node.addEventListener("dragleave", () => $("#drop")?.classList.remove("over"));
  node.addEventListener("drop", (e) => { e.preventDefault(); $("#drop")?.classList.remove("over"); handleFiles([...e.dataTransfer.files]); });

  node._dock = dock(h("button", { class: "btn", disabled: !count, onclick: () => go("#/vibe/1") }, "Continue", icon("arrow")));
  return node;
}

/** Downscale on the phone before uploading: faster over Wi-Fi, and the server only keeps 2048px anyway. */
async function shrink(file) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.9));
    return blob ? new File([blob], (file.name || "photo").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;   // e.g. HEIC on desktop browsers: the server converts it
  }
}

async function handleFiles(files) {
  files = files.filter((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name));
  if (!files.length) return;
  if (S.analysis && !window.__photoChangeOk) {
    toast("Changing photos means the stylist will look again.");
    window.__photoChangeOk = true;
  }
  const grid = $(".thumbs-grid") || (() => { const g = h("div", { class: "thumbs-grid" }); $("#drop")?.before(g); return g; })();
  const placeholders = files.map(() => { const p = h("div", { class: "thumb loading" }); grid.prepend(p); return p; });
  try {
    const form = new FormData();
    for (const f of await Promise.all(files.map(shrink))) form.append("files", f);
    await api("/api/photos", form);
    haptic();
  } catch (err) {
    toast(err.message, true);
  }
  placeholders.forEach((p) => p.remove());
  await refresh();
  rerender();
}

async function removePhoto(name) {
  try { await api(`/api/photos/${encodeURIComponent(name)}`, undefined, "DELETE"); await refresh(); rerender(); }
  catch (err) { toast(err.message, true); }
}

// ---------------------------------------------------------------------------
// 2. vibe check

function vibeScreen(arg) {
  const qs = S.intake_questions;
  const i = Math.max(1, Math.min(qs.length, Number(arg) || 1)) - 1;
  const q = qs[i];
  const selected = intake[q.id] || [];
  const last = i === qs.length - 1;

  const tiles = h("div", { class: "tiles" }, q.options.map((opt, k) => {
    const on = selected.includes(opt.value);
    const art = opt.image.src
      ? h("img", { src: opt.image.src, alt: "", loading: "eager" })
      : h("div", { class: "swatches" }, (opt.image.swatch || []).map((c) => h("i", { style: `background:${c}` })));
    return h("button", {
      class: `tile${on ? " on" : ""}`, style: `animation-delay:${60 + k * 45}ms`, "aria-pressed": on,
      onclick: (e) => toggle(q, opt.value, e.currentTarget),
    }, h("div", { class: "art" }, art), h("div", { class: "label" }, h("span", {}, opt.label), h("span", { class: "tick" }, icon("check"))));
  }));

  const node = h("section", {},
    h("div", { class: "reveal" },
      h("p", { class: "eyebrow" }, h("span", { class: "q-count" }, `${String(i + 1).padStart(2, "0")} / ${String(qs.length).padStart(2, "0")}`)),
      h("h1", { class: "title" }, q.question),
      h("p", { class: "small" }, q.subtitle)),
    tiles);

  node._dock = dock(h("button", {
    class: "btn", id: "vibe-next", disabled: selected.length === 0,
    onclick: () => last ? finishIntake() : go(`#/vibe/${i + 2}`),
  }, last ? "Start swiping" : "Next", icon("arrow")));
  return node;
}

function toggle(q, value, tile) {
  let selected = intake[q.id] || [];
  if (q.type === "single") selected = [value];
  else if (selected.includes(value)) selected = selected.filter((v) => v !== value);
  else if (selected.length < (q.max || 99)) selected = [...selected, value];
  else { toast(`Pick up to ${q.max}`); return; }
  intake[q.id] = selected;
  haptic(8);
  document.querySelectorAll(".tile").forEach((t) => {
    const label = t.querySelector(".label span").textContent;
    const opt = q.options.find((o) => o.label === label);
    const on = selected.includes(opt.value);
    t.classList.toggle("on", on);
    t.setAttribute("aria-pressed", on);
  });
  $("#vibe-next").disabled = selected.length === 0;
  const idx = S.intake_questions.indexOf(q);
  if (q.type === "single" && idx < S.intake_questions.length - 1) setTimeout(() => go(`#/vibe/${idx + 2}`), 380);
}

async function finishIntake() {
  const btn = $("#vibe-next");
  btn.disabled = true;
  try {
    await api("/api/intake", { answers: intake });
    // Photo analysis doesn't depend on swipes, so it runs in the background while you swipe.
    if (!S.analysis && S.jobs.analysis.state !== "running") {
      api("/api/analyze", { force: false }).then(refresh).catch((err) => { toast(`Photo analysis failed: ${err.message}`, true); refresh(); });
      setTimeout(() => refresh().catch(() => {}), 400);
    }
    await refresh();
    go("#/swipe");
  } catch (err) {
    toast(err.message, true);
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// 3. swipe

const deck = { card: null, count: 0, busy: false, node: null };

function swipeScreen() {
  const node = h("section", { class: "swipe-screen" },
    h("div", { class: "swipe-head" },
      h("div", {}, h("p", { class: "eyebrow" }, "Train your taste"), h("h1", { class: "title" }, "Would you wear it?")),
      h("div", { class: "head-right" }, h("span", { class: "count", id: "swipe-count" }, ""), h("div", { id: "done-cta" }))),
    h("div", { class: "swipe-body" },
      h("div", { class: "stack", id: "stack" }, h("div", { class: "ghost-card g2" }), h("div", { class: "ghost-card g1" }), h("div", { class: "card-loading" })),
      h("div", { class: "learning inline", id: "learning" }),
      h("div", { class: "actions-row" },
        h("button", { class: "round undo", id: "b-undo", "aria-label": "Undo", onclick: undoSwipe }, icon("undo")),
        h("button", { class: "round nope", id: "b-nope", "aria-label": "Not for me", onclick: () => commit("dislike") }, icon("x")),
        h("button", { class: "round love", id: "b-love", "aria-label": "Love it", onclick: () => commit("love") }, icon("star")),
        h("button", { class: "round like", id: "b-like", "aria-label": "I'd wear it", onclick: () => commit("like") }, icon("heart"))),
      h("button", { class: "skip", onclick: () => commit("skip") }, "Can't tell. Skip")),
    h("aside", { class: "side-learning" },
      h("p", { class: "eyebrow" }, "What we're learning"),
      h("div", { id: "side-learning" }, h("p", { class: "small" }, "Swipe a few and your taste starts to show here."))));
  node._mounted = () => loadCard();
  return node;
}

async function loadCard() {
  try {
    const { card, count } = await api("/api/swipe/next");
    deck.card = card;
    deck.count = count;
    placeCard();
    updateSwipeChrome();
    updateLearning();
  } catch (err) {
    toast(err.message, true);
  }
}

function placeCard() {
  const stack = $("#stack");
  if (!stack) return;
  stack.querySelectorAll(".card, .card-loading, .empty").forEach((n) => n.remove());
  if (!deck.card) {
    stack.append(h("div", { class: "empty" }, h("div", {}, h("p", { class: "h3" }, "That's the whole rack."), h("p", { class: "small" }, "You've seen every item. Your profile is ready."))));
    return;
  }
  const c = deck.card;
  const node = h("div", { class: "card enter" },
    h("div", { class: "photo" }, h("img", { src: c.image, alt: c.name, draggable: "false" })),
    h("div", { class: "info" }, h("div", { class: "cat" }, c.category), h("div", { class: "name" }, c.name), h("div", { class: "desc" }, c.description)),
    h("div", { class: "stamp like" }, "yes"), h("div", { class: "stamp nope" }, "nope"), h("div", { class: "stamp love" }, "love"));
  stack.append(node);
  deck.node = node;
  requestAnimationFrame(() => requestAnimationFrame(() => { node.classList.add("settle"); node.classList.remove("enter"); }));
  attachDrag(node);
}

function attachDrag(node) {
  const st = { x: 0, y: 0, dx: 0, dy: 0, t: 0, vx: 0, vy: 0, active: false };
  const stamps = { like: $(".stamp.like", node), nope: $(".stamp.nope", node), love: $(".stamp.love", node) };
  const paint = () => {
    node.style.transform = `translate3d(${st.dx}px, ${st.dy}px, 0) rotate(${st.dx * 0.06}deg)`;
    stamps.like.style.opacity = clamp(st.dx / 100);
    stamps.nope.style.opacity = clamp(-st.dx / 100);
    stamps.love.style.opacity = Math.abs(st.dx) < 70 ? clamp(-st.dy / 120) : 0;
  };
  node.addEventListener("pointerdown", (e) => {
    if (deck.busy || e.button > 0) return;
    Object.assign(st, { active: true, x: e.clientX, y: e.clientY, t: performance.now(), vx: 0, vy: 0 });
    node.setPointerCapture(e.pointerId);
    node.classList.remove("settle");
    node.classList.add("dragging");
  });
  node.addEventListener("pointermove", (e) => {
    if (!st.active) return;
    const now = performance.now(), dt = Math.max(1, now - st.t);
    const ndx = e.clientX - st.x, ndy = e.clientY - st.y;
    st.vx = 0.8 * st.vx + 0.2 * ((ndx - st.dx) / dt);
    st.vy = 0.8 * st.vy + 0.2 * ((ndy - st.dy) / dt);
    st.dx = ndx; st.dy = ndy; st.t = now;
    paint();
  });
  const release = () => {
    if (!st.active) return;
    st.active = false;
    node.classList.remove("dragging");
    const flickX = Math.abs(st.vx) > 0.6, flickUp = st.vy < -0.6;
    if (st.dx > 110 || (flickX && st.vx > 0 && st.dx > 30)) commit("like", st);
    else if (st.dx < -110 || (flickX && st.vx < 0 && st.dx < -30)) commit("dislike", st);
    else if ((st.dy < -130 || (flickUp && st.dy < -40)) && Math.abs(st.dx) < 80) commit("love", st);
    else { node.classList.add("settle"); st.dx = 0; st.dy = 0; paint(); }
  };
  node.addEventListener("pointerup", release);
  node.addEventListener("pointercancel", release);
}
const clamp = (v) => Math.max(0, Math.min(1, v));

async function commit(verdict, drag) {
  if (!deck.card || deck.busy) return;
  deck.busy = true;
  haptic(verdict === "love" ? [10, 40, 10] : 12);
  const button = { like: "#b-like", dislike: "#b-nope", love: "#b-love" }[verdict];
  if (button) { const b = $(button); b?.classList.remove("bump"); void b?.offsetWidth; b?.classList.add("bump"); }

  const node = deck.node;
  if (node) {
    const w = window.innerWidth;
    const dx = drag?.dx || 0, dy = drag?.dy || 0;
    const to = {
      like: `translate3d(${w * 0.9 + Math.max(0, dx)}px, ${dy + (drag?.vy || 0) * 120}px, 0) rotate(28deg)`,
      dislike: `translate3d(${-w * 0.9 + Math.min(0, dx)}px, ${dy + (drag?.vy || 0) * 120}px, 0) rotate(-28deg)`,
      love: `translate3d(${dx}px, -120vh, 0) rotate(${dx * 0.05}deg)`,
      skip: "translate3d(0, 30px, 0) scale(.92)",
    }[verdict];
    const stamp = { like: ".stamp.like", dislike: ".stamp.nope", love: ".stamp.love" }[verdict];
    if (stamp) $(stamp, node).style.opacity = 1;
    node.classList.remove("settle", "dragging");
    node.classList.add("fly");
    node.style.transform = to;
    node.style.opacity = verdict === "skip" ? "0" : "0.2";
  }
  const request = api("/api/swipe", { item_id: deck.card.id, verdict });
  await new Promise((r) => setTimeout(r, 260));
  try {
    await request;
    await loadCard();
  } catch (err) {
    toast(err.message, true);
    placeCard();
  } finally {
    deck.busy = false;
  }
}

async function undoSwipe() {
  if (deck.busy || deck.count === 0) return;
  deck.busy = true;
  haptic(8);
  try { await api("/api/swipe/undo", {}); await loadCard(); }
  catch (err) { toast(err.message, true); }
  finally { deck.busy = false; }
}

function updateSwipeChrome() {
  const count = $("#swipe-count");
  if (!count) return;
  count.textContent = `${deck.count} / ${S.swipe_target}`;
  $("#b-undo").disabled = deck.count === 0;
  const cta = $("#done-cta");
  const left = S.swipe_min - deck.count;
  const wasReady = cta.dataset.ready === "1";
  cta.dataset.ready = left > 0 ? "" : "1";
  cta.replaceChildren(left > 0
    ? h("span", { class: "unlock" }, `${left} to unlock profile`)
    : h("button", { class: `btn small done-pill${wasReady ? "" : " arrive"}`, onclick: () => go("#/taste") }, "Profile", icon("arrow")));
  if (deck.count === S.swipe_min && !wasReady) { haptic([10, 50, 10]); toast("Style profile unlocked. Keep swiping or open it."); }
}

let learnSeq = 0;
async function updateLearning() {
  const seq = ++learnSeq;
  const t = await api("/api/taste").catch(() => null);
  if (!t || seq !== learnSeq) return;
  const dims = [["styles", "Style"], ["color_family", "Color"], ["pattern", "Pattern"], ["fit", "Fit"], ["category", "Pieces"]];
  const chips = [];
  const groups = [];
  for (const [dim, name] of dims) {
    const d = t.dimensions[dim];
    const row = [...d.liked.slice(0, 3).map((r) => h("span", { class: "chip pos" }, r.label)),
                 ...d.disliked.slice(0, 2).map((r) => h("span", { class: "chip neg" }, r.label))];
    if (!row.length) continue;
    chips.push(...row.map((c) => c.cloneNode(true)));
    groups.push(h("div", { class: "group" }, h("p", { class: "eyebrow" }, name), h("div", { class: "chips-wrap" }, row)));
  }
  const inline = $("#learning"), side = $("#side-learning");
  if (inline) inline.replaceChildren(...chips);
  if (side && groups.length) side.replaceChildren(...groups);
}

// ---------------------------------------------------------------------------
// 4. taste profile + stylist

function tasteScreen() {
  const node = h("section", {},
    h("div", { class: "reveal" },
      h("p", { class: "eyebrow" }, "Your style profile"),
      h("h1", { class: "title" }, "What you love, ", h("em", {}, "and"), " what loves you back.")),
    h("div", { class: "taste-cols" },
      h("div", { class: "section", id: "taste-like" }, h("div", { class: "waiting" }, h("div", { class: "spinner" }), "Reading your swipes…")),
      h("div", { class: "section", id: "taste-suits" }, stylistBlock())));
  node._mounted = () => fillTaste();
  const ready = !!S.analysis;
  node._dock = dock(
    h("button", { class: "btn ghost", onclick: () => go("#/swipe") }, "Swipe more"),
    h("button", { class: "btn", onclick: startDesign }, S.styles ? "See my looks" : ready ? "Style me" : "Style me", icon("sparkle")));
  return node;
}

async function fillTaste() {
  const t = await api("/api/taste").catch((err) => { toast(err.message, true); return null; });
  const box = $("#taste-like");
  if (!t || !box) return;
  const dims = [["styles", "Style"], ["color_family", "Color"], ["color_tone", "Mood"], ["pattern", "Pattern"], ["fit", "Fit"],
                ["formality", "Formality"], ["loudness", "Volume"], ["category", "Pieces"]];
  const traits = dims.map(([dim, name]) => {
    const d = t.dimensions[dim];
    const rows = [...d.liked.slice(0, 4), ...d.disliked.slice(0, 2)];
    if (!rows.length) return null;
    return h("div", { class: "trait" }, h("div", { class: "k" }, name), h("div", {},
      rows.map((r, k) => h("div", { class: "meter" },
        h("div", {}, h("div", { style: "display:flex;justify-content:space-between;font-size:14px" }, h("span", {}, r.label)),
          h("div", { class: "track" }, h("div", { class: `fill ${r.score >= 0.5 ? "pos" : "neg"}`, style: `width:${Math.round(r.score * 100)}%;animation-delay:${k * 60}ms` }))),
        h("span", { class: "small", style: "text-align:right" }, r.score >= 0.5 ? `${Math.round(r.score * 100)}%` : "not you")))));
  }).filter(Boolean);
  const top = t.dimensions.styles.liked.slice(0, 3).map((r) => h("span", { class: "chip plain" }, r.label));
  const loved = [...t.loved, ...t.liked].slice(0, 14);
  box.replaceChildren(
    h("p", { class: "eyebrow" }, `From ${t.swipes} swipes · ${t.counts.love} loved · ${t.counts.like} liked`),
    h("h2", { class: "h3" }, "You're drawn to"),
    top.length ? h("div", { class: "chips-wrap", style: "margin:10px 0 6px" }, top) : null,
    loved.length ? h("div", { class: "strip" }, loved.map((it) => h("div", { class: "mini" },
      h("div", { class: "art" }, h("img", { src: it.image, alt: "" }), t.loved.some((l) => l.id === it.id) ? h("span", { class: "badge" }, "★") : null),
      h("div", { class: "cap" }, it.name)))) : null,
    h("div", { style: "margin-top:12px" }, traits.length ? traits : h("p", { class: "small" }, "Swipe a little more for a clearer picture.")));
}

function stylistBlock() {
  const job = S.jobs.analysis;
  if (!S.analysis) {
    if (job.state === "running") return h("div", {}, h("h2", { class: "h3" }, "What suits you"), h("div", { class: "waiting" }, h("div", { class: "spinner" }), "The stylist is still studying your photos…"));
    return h("div", {}, h("h2", { class: "h3" }, "What suits you"),
      h("p", { class: "small" }, job.state === "error" ? `That didn't work: ${job.error}` : "Your photos haven't been analyzed yet."),
      h("button", { class: "btn small", onclick: () => runAnalysis(false) }, job.state === "error" ? "Try again" : "Analyze my photos"));
  }
  const o = S.analysis.observations, s = o.suits_you;
  const note = (k, v) => v && (Array.isArray(v) ? v.length : true) ? h("div", { class: "note" }, h("div", { class: "k" }, k), h("div", {}, Array.isArray(v) ? v.join(", ") : v)) : null;
  return h("div", {},
    h("h2", { class: "h3" }, "What suits you"),
    h("p", { class: "quote", style: "margin-top:10px" }, o.summary),
    h("div", { class: "note-grid" },
      note("Your colors", s.colors), note("Keep away from your face", s.avoid_colors), note("Necklines & collars", s.necklines_and_collars),
      note("Fit & shape", s.fits_and_silhouettes), note("Eyewear", s.eyewear), note("Accessories", s.accessories)),
    o.flags.length ? h("div", { class: "section" }, h("p", { class: "eyebrow" }, "Worth changing"),
      o.flags.map((f) => h("div", { class: "flag" }, h("div", { class: "item" }, f.item), h("div", { class: "issue" }, f.issue), h("div", { class: "try" }, h("b", {}, "Try: "), f.suggestion)))) : null,
    S.photos.length > 1 ? h("div", { class: "section" },
      h("p", { class: "eyebrow" }, "Photo we'll style"),
      h("div", { class: "refs" }, S.photos.map((name) => h("button", {
        class: `ref${name === S.reference_file ? " on" : ""}`, "aria-label": "Use this photo",
        onclick: async () => { await api("/api/reference", { file: name }).catch((e) => toast(e.message, true)); await refresh(); rerender(); },
      }, h("img", { src: photoUrl(name), alt: "" })))),
      h("p", { class: "small" }, S.analysis.reference_photo.reason)) : null);
}

async function runAnalysis(force) {
  api("/api/analyze", { force }).then(async () => { await refresh(); if (currentRoute.name === "taste") rerender(); })
    .catch(async (err) => { toast(err.message, true); await refresh(); if (currentRoute.name === "taste") rerender(); });
  setTimeout(async () => { await refresh(); if (currentRoute.name === "taste") rerender(); }, 400);
}

// ---------------------------------------------------------------------------
// 5. designing

const TICKER = ["Reading your swipes", "Matching colors to your skin tone", "Balancing your proportions", "Choosing frames for your face",
                "Picking the right shoes", "Pulling accessories", "Writing the tech pack", "Almost there"];

function designingScreen() {
  const ticker = h("div", { class: "ticker" }, h("span", {}, TICKER[0]));
  const node = h("section", { class: "designing" }, h("div", { class: "reveal" },
    h("p", { class: "eyebrow" }, "In the studio"),
    h("h1", { class: "display" }, "Styling your ", h("em", {}, "three"), " looks"),
    h("div", { class: "loader-line" }), ticker,
    h("p", { class: "small", style: "margin-top:26px" }, "Takes a minute or two. Keep this open.")));
  let k = 0;
  const timer = setInterval(() => {
    if (!document.body.contains(ticker)) return clearInterval(timer);
    k = (k + 1) % TICKER.length;
    ticker.replaceChildren(h("span", {}, TICKER[k]));
  }, 3200);
  node._mounted = () => continueDesign();
  return node;
}

function startDesign() {
  if (S.styles) return go("#/looks");
  go("#/designing");
}

let designInFlight = false;
async function continueDesign() {
  if (designInFlight || currentRoute.name !== "designing") return;
  await refresh();
  if (S.styles && S.jobs.styles.state !== "running") return go("#/looks");
  if (S.jobs.styles.state === "running") { clearTimeout(pollTimer); pollTimer = setTimeout(onPoll, 3500); return; }
  if (S.jobs.styles.state === "error") { toast(S.jobs.styles.error, true); S.jobs.styles.state = "idle"; return go("#/taste"); }
  if (!S.analysis) {
    if (S.jobs.analysis.state === "error") { toast(`Photo analysis failed: ${S.jobs.analysis.error}`, true); return go("#/taste"); }
    if (S.jobs.analysis.state !== "running") runAnalysis(false);
    setTimeout(continueDesign, 3500);   // wait for the stylist's notes first
    return;
  }
  designInFlight = true;
  try {
    await api("/api/styles", { force: false });
    await refresh();
    haptic([10, 60, 10]);
    go("#/looks");
  } catch (err) {
    toast(err.message, true);
    await refresh();
    go("#/taste");
  } finally {
    designInFlight = false;
  }
}

// ---------------------------------------------------------------------------
// 6. looks

const MODEL_SHORT = { "gemini-3.1-flash-image": "Flash", "gemini-3-pro-image": "Pro", "gemini-2.5-flash-image": "2.5" };
const modelsFor = (choice) => choice === "both" ? S.default_render_models : [choice];

function looksScreen() {
  const seg = h("div", { class: "seg", role: "tablist" },
    [["both", "Both"], ...S.default_render_models.map((m) => [m, MODEL_SHORT[m] || m])].map(([v, label]) =>
      h("button", { class: renderChoice === v ? "on" : "", onclick: () => { renderChoice = v; rerender(); } }, label)));
  const node = h("section", {},
    h("div", { class: "looks-head" },
      h("div", { class: "reveal" }, h("p", { class: "eyebrow" }, "Styled for you"), h("h1", { class: "title" }, "Your looks")),
      h("div", {}, h("p", { class: "eyebrow", style: "margin-bottom:6px" }, "Render with"), seg)),
    h("div", { class: "carousel", id: "carousel" }, S.styles.looks.map((look, i) => lookCard(look, i + 1))));
  const pending = S.styles.looks.some((_, i) => modelsFor(renderChoice).some((m) => !(S.session.renders[i + 1] || {})[m]));
  node._dock = dock(
    h("button", { class: "btn ghost", onclick: () => go("#/taste") }, "Profile"),
    h("button", { class: "btn", disabled: rendering.size > 0 || !pending, onclick: renderAll },
      rendering.size ? "Rendering…" : pending ? "Put them on me" : "All rendered", icon("sparkle")));
  return node;
}

function lookCard(look, n) {
  const renders = S.session.renders[n] || {};
  const models = [...new Set([...modelsFor(renderChoice), ...Object.keys(renders).filter((m) => renderChoice === "both" || m === renderChoice)])];
  const frames = models.map((m) => {
    const r = renders[m];
    if (rendering.has(`${n}:${m}`)) return h("div", { class: "frame" }, h("div", { class: "placeholder" }, h("div", { class: "spinner" }), `Dressing you in ${MODEL_SHORT[m] || m}…`));
    if (r?.status === "ok") return h("div", { class: "frame" }, h("img", { src: `/looks/${r.file}?t=${encodeURIComponent(r.at)}`, alt: look.name }), h("span", { class: "model-tag" }, MODEL_SHORT[m] || m));
    if (r) return h("div", { class: "frame" }, h("div", { class: "error" }, "This one didn't render. Try again.", h("br"), h("span", { class: "small" }, r.error?.slice(0, 120))));
    return h("div", { class: "frame" }, h("div", { class: "placeholder" },
      h("div", { class: "palette-bar" }, look.palette.map((c) => h("i", { style: `background:${c.hex}` }))),
      h("span", { class: "small" }, MODEL_SHORT[m] || m),
      h("button", { class: "btn small", disabled: rendering.size > 0, onclick: () => renderLook(n, [m]) }, "Put it on me")));
  });
  const frameStrip = h("div", { class: "frames" }, frames);
  const dots = frames.length > 1 ? h("div", { class: "dots-nav" }, frames.map((_, k) => h("i", { class: k === 0 ? "on" : "" }))) : null;
  if (dots) frameStrip.addEventListener("scroll", () => {
    const k = Math.round(frameStrip.scrollLeft / frameStrip.clientWidth);
    dots.querySelectorAll("i").forEach((d, j) => d.classList.toggle("on", j === k));
  }, { passive: true });

  const e = look.eyewear;
  return h("article", { class: "look" },
    h("div", { class: "look-media" }, frameStrip, dots),
    h("div", { class: "look-body" },
      h("p", { class: "eyebrow" }, `Look ${n} · ${look.direction}`),
      h("h2", { class: "name" }, look.name),
      h("p", { class: "summary" }, look.summary),
      h("ul", { class: "pieces" }, look.pieces.map((p) => h("li", {},
        h("span", { class: "k" }, p.category.replace(" layer", "").replace("base ", "")),
        h("span", { class: "v" }, h("b", {}, `${cap(p.color)} ${p.item.toLowerCase()}`), h("div", { class: "d" }, `${p.material} · ${p.fit}`))))),
      h("details", {}, h("summary", {}, "Why it works on you"), h("div", { class: "content" }, look.why_it_suits)),
      h("details", {}, h("summary", {}, "Eyewear & accessories"), h("div", { class: "content" },
        h("p", {}, h("b", {}, "Eyewear: "), e.type === "none" ? "None" : `${e.color} ${e.material} ${e.shape} ${e.type}. `, e.why),
        look.accessories.map((a) => h("p", {}, h("b", {}, `${cap(a.type)}: `), a.description)))),
      h("details", {}, h("summary", {}, "The details"), h("div", { class: "content" },
        look.pieces.map((p) => h("p", {}, h("b", {}, `${cap(p.item)}: `), p.design_details)),
        h("p", {}, h("b", {}, "Grooming: "), look.grooming))),
      h("details", {}, h("summary", {}, "Palette"), h("div", { class: "content" },
        h("div", { class: "palette" }, look.palette.map((c) => h("div", { class: "sw" }, h("i", { style: `background:${c.hex}` }), c.name))))),
      Object.keys(renders).length ? h("div", { class: "look-actions" },
        h("button", { class: "btn small ghost", disabled: rendering.size > 0, onclick: (ev) => confirmTap(ev.currentTarget, "Tap again to re-render") && renderLook(n, modelsFor(renderChoice)) }, "Re-render")) : null));
}
const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;

async function renderLook(n, models) {
  for (const model of models) {   // one at a time; a failure doesn't stop the next
    rendering.add(`${n}:${model}`);
    if (currentRoute.name === "looks") rerender();
    try {
      const r = await api("/api/render", { look: n, model });
      if (r.status !== "ok") toast(`Look ${n} (${MODEL_SHORT[model] || model}) didn't render`, true);
      else haptic();
    } catch (err) {
      toast(err.message, true);
    } finally {
      rendering.delete(`${n}:${model}`);
      await refresh();
      if (currentRoute.name === "looks") rerender();
    }
  }
}

async function renderAll() {
  for (let n = 1; n <= S.styles.looks.length; n++) {
    const missing = modelsFor(renderChoice).filter((m) => (S.session.renders[n] || {})[m]?.status !== "ok");
    if (missing.length) await renderLook(n, missing);
  }
}

// ---------------------------------------------------------------------------
// chrome: back, menu sheet, keyboard

const SCREENS = { upload: uploadScreen, vibe: vibeScreen, swipe: swipeScreen, taste: tasteScreen, designing: designingScreen, looks: looksScreen };

$("#nav-back").addEventListener("click", goBack);
const openSheet = (open) => { $("#sheet").hidden = !open; $("#sheet-backdrop").hidden = !open; if (!open) $("#prompt-preview").hidden = true; };
$("#menu-btn").addEventListener("click", () => openSheet(true));
$("#sheet-backdrop").addEventListener("click", () => openSheet(false));
document.querySelectorAll("[data-preview]").forEach((b) => b.addEventListener("click", async () => {
  try {
    const { prompt } = await api(`/api/preview/${b.dataset.preview}`);
    const pre = $("#prompt-preview");
    pre.textContent = prompt;
    pre.hidden = false;
  } catch (err) { toast(err.message, true); }
}));
$("#reset").addEventListener("click", async (e) => {
  if (!confirmTap(e.currentTarget, "Tap again: clears photos, answers and looks")) return;
  try {
    await api("/api/reset", {});
    intake = {};
    openSheet(false);
    await refresh();
    location.hash = "#/";
    show();
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("keydown", (e) => {
  if (e.target instanceof Element && e.target.matches("input, textarea, select")) return;
  if (e.key === "Escape") return openSheet(false);
  if (currentRoute.name !== "swipe") return;
  const act = { ArrowRight: () => commit("like"), ArrowLeft: () => commit("dislike"), ArrowUp: () => commit("love"), Backspace: undoSwipe }[e.key];
  if (act) { e.preventDefault(); act(); }
});

window.addEventListener("hashchange", show);

(async () => {
  try {
    await refresh();
    if (!location.hash || location.hash === "#") {
      // Resume where the session left off.
      const resume = S.styles ? "#/looks" : S.session.swipe_count >= S.swipe_min ? "#/taste"
        : intakeSaved() ? "#/swipe" : S.photos.length ? "#/vibe/1" : "#/";
      history.replaceState(null, "", resume);
    }
    show();
  } catch (err) {
    app.replaceChildren(h("section", { class: "screen" }, h("h1", { class: "title" }, "Couldn't load."), h("p", { class: "small" }, err.message)));
  }
})();
