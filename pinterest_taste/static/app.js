"use strict";

const $ = (id) => document.getElementById(id);
const form = $("search-form");
const query = $("query");
const panels = ["empty-state", "progress-panel", "message-panel", "results"];
let searches = [];
let currentJob = null;
let selected = null;
let pollTimer = null;
let pollVersion = 0;
let busy = false;
let referenceBusy = false;
let referencesSupported = false;
let rankSelectionSupported = false;
let referenceFile = null;
let referenceURL = null;
let referenceTimer = null;
let referenceVersion = 0;
let referenceRetry = null;
let maxUploadBytes = 10 * 1024 * 1024;
let retry = () => form.requestSubmit();

function showPanel(id) {
  for (const panel of panels) $(panel).hidden = panel !== id;
}

function setBusy(value) {
  busy = value;
  updateControls();
  renderHistory();
}

function updateControls() {
  $("search-button").disabled = busy || referenceBusy;
  $("search-button").querySelector("span").textContent = busy
    ? "Finding photos…"
    : referenceBusy
      ? "Describing photo…"
      : "Find photos";
  form.setAttribute("aria-busy", String(busy || referenceBusy));
  $("reference-drop").disabled = busy || referenceBusy || !referencesSupported;
  $("reference-file").disabled = busy || referenceBusy || !referencesSupported;
  $("reference-remove").disabled = referenceBusy;
  $("pick-count").disabled = busy || referenceBusy || !rankSelectionSupported;
  for (const button of document.querySelectorAll(".reference-choice"))
    button.disabled = busy || referenceBusy;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    signal: AbortSignal.timeout(20000),
  });
  const body = await response.json();
  if (!response.ok) {
    let detail = body.detail;
    if (Array.isArray(detail))
      detail = detail.map((item) => item.msg).join(" ");
    const error = new Error(detail || "The request failed. Try again.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function showError(
  heading,
  message,
  action = () => form.requestSubmit(),
  label = "Try again",
) {
  showPanel("message-panel");
  $("message-heading").textContent = heading;
  $("message-text").textContent = message;
  $("retry-button").textContent = label;
  retry = action;
}

function remember(job) {
  const index = searches.findIndex((item) => item.id === job.id);
  if (index < 0) searches.unshift(job);
  else searches[index] = job;
  searches = searches.slice(0, 10);
  renderHistory();
}

function renderHistory() {
  $("history").hidden = searches.length === 0;
  $("history-list").replaceChildren();
  for (const job of searches) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = job.query;
    button.title = job.query;
    button.disabled = busy || referenceBusy;
    button.setAttribute("aria-current", String(currentJob?.id === job.id));
    button.addEventListener("click", () => {
      clearTimeout(pollTimer);
      pollVersion += 1;
      query.value = job.query;
      updateCount();
      displayJob(job);
    });
    $("history-list").append(button);
  }
}

function formatBytes(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

function formatRemaining(seconds) {
  if (seconds < 60) return "Less than a minute left";
  const minutes = Math.ceil(seconds / 60);
  return minutes < 60
    ? `About ${minutes} min left`
    : `About ${Math.floor(minutes / 60)} h ${minutes % 60} min left`;
}

function renderModelProgress(id, detail) {
  const container = $(id);
  container.hidden = !detail;
  container.replaceChildren();
  if (!detail) return;
  const title = document.createElement("strong");
  title.textContent = detail.model;
  const status = document.createElement("p");
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.setAttribute("aria-label", `${detail.model} preparation`);
  container.append(title, status, bar);
  if (detail.phase === "loading_memory") {
    status.textContent = "Loading into memory";
    const note = document.createElement("p");
    note.textContent = "Files are ready. Preparing the model on your computer…";
    note.className = "model-progress-details";
    container.append(note);
  } else if (detail.phase === "checking") {
    status.textContent = "Checking model files…";
  } else {
    if (Number.isFinite(detail.percent)) bar.value = detail.percent;
    status.textContent = Number.isFinite(detail.percent)
      ? `Downloading · ${Math.floor(detail.percent)}%`
      : "Downloading";
    const amount = document.createElement("p");
    amount.textContent = `${formatBytes(detail.downloaded_bytes)}${detail.total_bytes ? ` / ${formatBytes(detail.total_bytes)}` : ""}`;
    const speed = document.createElement("p");
    speed.className = "model-progress-details";
    speed.textContent =
      detail.bytes_per_second > 0
        ? `${formatBytes(detail.bytes_per_second)}/s · ${Number.isFinite(detail.eta_seconds) ? formatRemaining(detail.eta_seconds) : "Estimating time…"}`
        : "Waiting for download progress…";
    container.append(amount, speed);
  }
}

function displayProgress(job) {
  showPanel("progress-panel");
  $("progress-heading").textContent =
    job.stage === "loading"
      ? "Preparing the image models"
      : "Finding your photos";
  $("progress-message").textContent = job.message;
  $("progress-message").hidden = Boolean(job.model_download);
  renderModelProgress("search-model-progress", job.model_download);
  const stages = ["searching", "downloading", "loading", "scoring"];
  const current = stages.indexOf(job.stage);
  for (const [index, element] of [
    ...document.querySelectorAll(".progress-steps li"),
  ].entries()) {
    element.classList.toggle("active", index === current);
    element.classList.toggle("complete", index < current);
    if (index === current) element.setAttribute("aria-current", "step");
    else element.removeAttribute("aria-current");
  }
}

function selectPhoto(row, group, index) {
  selected = row;
  $("selected-image").src = row.image;
  $("selected-image").alt = row.title || currentJob.query;
  $("selected-title").textContent =
    row.title || "No title provided by Pinterest.";
  $("selected-score").textContent = `Taste score ${row.score.toFixed(2)}`;
  $("selected-group").textContent =
    `${group === "top" ? "Carousel pick" : "Other photo"} · #${index + 1 + (group === "bottom" ? currentJob.top.length : 0)}`;
  $("selected-download").href = row.download;
  $("selected-source").hidden = !row.source;
  if (row.source) $("selected-source").href = row.source;
  else $("selected-source").removeAttribute("href");
  for (const button of document.querySelectorAll(".photo-card")) {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.image === row.image),
    );
  }
}

function alignGroupHeading(grid) {
  const heading = grid.parentElement.querySelector(".group-heading");
  const cards = [...grid.querySelectorAll(".photo-card")];
  const bounds = grid.getBoundingClientRect();
  if (!cards.length || !bounds.width) {
    heading.style.removeProperty("width");
    return;
  }
  // Fixed-size grid tracks can leave unused space after the last column.
  const right = Math.max(...cards.map((card) => card.getBoundingClientRect().right));
  heading.style.width = `${right - bounds.left}px`;
}

const gridResizeObserver = new ResizeObserver((entries) => {
  for (const { target } of entries) alignGroupHeading(target);
});
for (const grid of document.querySelectorAll(".photo-grid")) {
  gridResizeObserver.observe(grid);
}

const groupSortAscending = { top: false, bottom: false };

for (const group of ["top", "bottom"]) {
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "sort-order";
  toggle.textContent = "Best first ↓";
  toggle.setAttribute("aria-label", `Sort ${group === "top" ? "carousel picks" : "other photos"} by taste score`);
  toggle.addEventListener("click", () => {
    groupSortAscending[group] = !groupSortAscending[group];
    toggle.textContent = groupSortAscending[group] ? "Lowest first ↑" : "Best first ↓";
    if (currentJob) renderGrid(currentJob[group], group);
  });
  document.getElementById(`${group}-description`).after(toggle);
}

function renderGrid(rows, group) {
  const grid = $(`${group}-grid`);
  grid.replaceChildren();
  $(`${group}-count`).textContent = `${rows.length} photos`;
  if (!rows.length) {
    const note = document.createElement("p");
    note.className = "group-empty";
    note.textContent =
      group === "top"
        ? "No photos in this selection."
        : "All available photos are included in the picks.";
    grid.append(note);
  }
  const ordered = rows.map((row, index) => ({ row, index }));
  if (groupSortAscending[group]) ordered.reverse();
  ordered.forEach(({ row, index }) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "photo-card";
    button.dataset.image = row.image;
    button.setAttribute("aria-pressed", String(selected?.image === row.image));
    button.setAttribute(
      "aria-label",
      `${group === "top" ? "Carousel pick" : "Other photo"} ${index + 1 + (group === "bottom" ? currentJob.top.length : 0)}, taste score ${row.score.toFixed(2)}. ${row.title || currentJob.query}`,
    );
    const img = document.createElement("img");
    img.src = row.thumbnail;
    img.alt = row.title || currentJob.query;
    img.loading = "lazy";
    const meta = document.createElement("div");
    meta.className = "card-meta";
    const rank = document.createElement("span");
    rank.textContent = `#${index + 1 + (group === "bottom" ? currentJob.top.length : 0)}`;
    const score = document.createElement("strong");
    score.textContent = row.score.toFixed(2);
    score.title = "Taste score, from 0 to 1";
    meta.append(rank, score);
    button.append(img, meta);
    button.addEventListener("click", () => selectPhoto(row, group, index));
    grid.append(button);
  });
  alignGroupHeading(grid);
}

function displayJob(job) {
  currentJob = job;
  remember(job);
  if (job.state === "running") {
    setBusy(true);
    displayProgress(job);
    return;
  }
  setBusy(false);
  if (job.state === "error") {
    showError("The search couldn't finish", job.message);
    return;
  }
  if (!job.total) {
    showError(
      "No photos came through",
      "Pinterest returned no downloadable photos. Try a shorter description, or choose a browser where you are logged in to Pinterest.",
    );
    return;
  }
  showPanel("results");
  $("results-query").textContent = job.query;
  $("results-summary").textContent =
    `${job.total} photos shown · Sorted by taste score, highest first`;
  $("download-all").href = `/api/searches/${job.id}/download`;
  $("download-all").hidden = job.top.length === 0;
  const legacy = job.pick_count === undefined;
  $("top-heading").textContent = legacy
    ? "Previous selection"
    : "Carousel picks";
  $("top-description").textContent = legacy
    ? "Saved with the previous selection rule. Restart the app and search again to use rank selection."
    : `Top ${job.top.length} by taste score · requested ${job.pick_count}.`;
  $("bottom-description").textContent =
    "Remaining photos, ranked highest first.";
  renderGrid(job.top, "top");
  renderGrid(job.bottom, "bottom");
  selectPhoto(
    job.top[0] || job.bottom[0],
    job.top.length ? "top" : "bottom",
    0,
  );
}

async function poll(id, version) {
  try {
    const job = await api(`/api/searches/${id}`);
    if (version !== pollVersion) return;
    displayJob(job);
    if (job.state === "running")
      pollTimer = setTimeout(() => poll(id, version), 1500);
  } catch (error) {
    if (version !== pollVersion) return;
    setBusy(false);
    showError(
      "Connection interrupted",
      `${error.status ? error.message : "Make sure the local app is still running in your terminal."} Reconnect to check this search before starting another one.`,
      restore,
      "Reconnect",
    );
  }
}

async function restore() {
  clearTimeout(pollTimer);
  const version = ++pollVersion;
  try {
    const response = await api("/api/searches");
    if (version !== pollVersion) return;
    searches = response.searches;
    setBusy(false);
    if (searches.length) {
      const job =
        searches.find((item) => item.state === "running") || searches[0];
      query.value = job.query;
      updateCount();
      displayJob(job);
      if (job.state === "running")
        pollTimer = setTimeout(() => poll(job.id, version), 1000);
    } else {
      currentJob = null;
      renderHistory();
      showPanel("empty-state");
    }
  } catch {
    setBusy(false);
    showError(
      "The local app isn't responding",
      "Make sure the app is running in your terminal, then reconnect.",
      restore,
      "Reconnect",
    );
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || referenceBusy) return;
  const description = query.value.trim();
  if (!description) {
    query.setCustomValidity("Enter a description to search for.");
    query.reportValidity();
    return;
  }
  clearTimeout(pollTimer);
  const version = ++pollVersion;
  setBusy(true);
  displayProgress({ stage: "searching", message: "Starting your search" });
  try {
    const job = await api("/api/searches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: description,
        limit: Number($("limit").value),
        ...(rankSelectionSupported
          ? { top: Number($("pick-count").value) }
          : {}),
        cookies: $("cookies").value,
      }),
    });
    if (version !== pollVersion) return;
    displayJob(job);
    pollTimer = setTimeout(() => poll(job.id, version), 500);
  } catch (error) {
    if (version !== pollVersion) return;
    if (error.status === 409) return restore();
    setBusy(false);
    if (!error.status) {
      showError(
        "Connection interrupted",
        "The search may still be running. Reconnect to check its progress.",
        restore,
        "Reconnect",
      );
    } else showError("Couldn't start the search", error.message);
  }
});

function updateCount() {
  query.setCustomValidity("");
  $("char-count").textContent = `${query.value.length}/300`;
  for (const button of document.querySelectorAll(".reference-choice")) {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.query === query.value),
    );
  }
}

query.addEventListener("input", updateCount);
for (const button of document.querySelectorAll("[data-query]")) {
  button.addEventListener("click", () => {
    query.value = button.dataset.query;
    updateCount();
    query.focus();
  });
}
function updateConnectionHelp() {
  const value = $("cookies").value;
  $("connection-help").textContent =
    value === "anonymous"
      ? "No account needed. Results may be limited."
      : value === "cookies.txt"
        ? "Put cookies.txt in the folder where you started the app. Keep this login file private."
        : "Log in to Pinterest in this browser first. Your computer may ask permission to read its cookies.";
}
$("cookies").addEventListener("change", updateConnectionHelp);
$("retry-button").addEventListener("click", () => retry());
$("about-button").addEventListener("click", () =>
  $("about-dialog").showModal(),
);
$("selected-open").addEventListener("click", () => {
  if (!selected) return;
  $("dialog-photo").src = selected.image;
  $("dialog-photo").alt = selected.title || currentJob.query;
  $("dialog-score").textContent = `Taste score ${selected.score.toFixed(2)}`;
  $("dialog-download").href = selected.download;
  $("photo-dialog").showModal();
});
for (const button of document.querySelectorAll("[data-close]")) {
  button.addEventListener("click", () => $(button.dataset.close).close());
}
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom
    )
      dialog.close();
  });
}
function setReferenceBusy(value) {
  referenceBusy = value;
  updateControls();
  renderHistory();
}

function referenceStatus(message, isError = false) {
  $("reference-status").hidden = !message;
  $("reference-status").textContent = message;
  $("reference-status").classList.toggle("is-error", isError);
}

function showReferenceRetry(action, label) {
  referenceRetry = action;
  $("reference-retry").textContent = label;
  $("reference-retry").hidden = false;
}

function showReference(job) {
  $("reference-retry").hidden = true;
  renderModelProgress(
    "reference-model-progress",
    job.state === "running" ? job.model_download : null,
  );
  if (job.state === "running") {
    setReferenceBusy(true);
    referenceStatus(job.model_download ? "" : job.message);
    return;
  }
  setReferenceBusy(false);
  if (job.state === "error") {
    referenceStatus(job.message, true);
    if (referenceFile)
      showReferenceRetry(
        () => describeReference(referenceFile),
        "Try describing again",
      );
    return;
  }
  referenceStatus(
    "Choose a search phrase, edit it if needed, then find photos.",
  );
  const choices = $("reference-suggestions");
  choices.replaceChildren();
  choices.hidden = false;
  for (const suggestion of job.suggestions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "reference-choice";
    button.dataset.query = suggestion.query;
    button.setAttribute(
      "aria-pressed",
      String(query.value === suggestion.query),
    );
    const label = document.createElement("strong");
    label.textContent = suggestion.label;
    const text = document.createElement("span");
    text.textContent = suggestion.query;
    button.append(label, text);
    button.addEventListener("click", () => {
      query.value = suggestion.query;
      updateCount();
      query.focus();
    });
    choices.append(button);
  }
  updateControls();
}

async function pollReference(id, version) {
  try {
    const job = await api(`/api/references/${id}`);
    if (version !== referenceVersion) return;
    showReference(job);
    if (job.state === "running")
      referenceTimer = setTimeout(() => pollReference(id, version), 1500);
  } catch (error) {
    if (version !== referenceVersion) return;
    if (error.status === 404) setReferenceBusy(false);
    referenceStatus(
      error.status
        ? error.message
        : "Connection interrupted. Reconnect to check your photo description.",
      true,
    );
    showReferenceRetry(reconnectReference, "Reconnect");
  }
}

async function reconnectReference() {
  clearTimeout(referenceTimer);
  const version = ++referenceVersion;
  try {
    const { references } = await api("/api/references");
    if (version !== referenceVersion) return;
    const job =
      references.find((item) => item.state === "running") || references[0];
    if (job) {
      showReference(job);
      if (job.state === "running")
        referenceTimer = setTimeout(() => pollReference(job.id, version), 1000);
    } else {
      setReferenceBusy(false);
      $("reference-retry").hidden = true;
      referenceStatus("");
    }
  } catch {
    referenceStatus(
      "Couldn't check photo descriptions. Reconnect to check whether one is still running.",
      true,
    );
    showReferenceRetry(reconnectReference, "Reconnect");
  }
}

async function describeReference(file) {
  if (busy || referenceBusy || !referencesSupported) return;
  const allowed = { "image/jpeg": true, "image/png": true, "image/webp": true };
  const inferred = /\.jpe?g$/i.test(file.name)
    ? "image/jpeg"
    : /\.png$/i.test(file.name)
      ? "image/png"
      : /\.webp$/i.test(file.name)
        ? "image/webp"
        : "";
  const type = file.type || inferred;
  if (!allowed[type] || !file.size || file.size > maxUploadBytes) {
    referenceStatus("Choose one JPG, PNG or WebP photo, up to 10 MB.", true);
    return;
  }
  clearTimeout(referenceTimer);
  const version = ++referenceVersion;
  referenceFile = file;
  if (referenceURL) URL.revokeObjectURL(referenceURL);
  referenceURL = URL.createObjectURL(file);
  $("reference-image").src = referenceURL;
  $("reference-name").textContent = file.name;
  $("reference-preview").hidden = false;
  $("reference-suggestions").replaceChildren();
  $("reference-suggestions").hidden = true;
  $("reference-retry").hidden = true;
  setReferenceBusy(true);
  referenceStatus(
    "Reading your photo. First use downloads the local description model, roughly 1 GB.",
  );
  try {
    const job = await api("/api/references", {
      method: "POST",
      headers: { "Content-Type": type },
      body: file,
    });
    if (version !== referenceVersion) return;
    showReference(job);
    if (job.state === "running")
      referenceTimer = setTimeout(() => pollReference(job.id, version), 500);
  } catch (error) {
    if (version !== referenceVersion) return;
    if (error.status) setReferenceBusy(false);
    referenceStatus(
      error.status
        ? error.message
        : "Connection interrupted. The description may still be running.",
      true,
    );
    showReferenceRetry(
      !error.status || error.status === 409
        ? reconnectReference
        : () => describeReference(file),
      !error.status || error.status === 409
        ? "Reconnect"
        : "Try describing again",
    );
  }
}

$("reference-drop").addEventListener("click", () =>
  $("reference-file").click(),
);
$("reference-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) describeReference(file);
});
$("reference-retry").addEventListener("click", () => referenceRetry?.());
$("reference-remove").addEventListener("click", () => {
  if (referenceBusy) return;
  clearTimeout(referenceTimer);
  referenceVersion += 1;
  referenceFile = null;
  if (referenceURL) URL.revokeObjectURL(referenceURL);
  referenceURL = null;
  $("reference-image").removeAttribute("src");
  $("reference-preview").hidden = true;
  $("reference-suggestions").replaceChildren();
  $("reference-suggestions").hidden = true;
  $("reference-retry").hidden = true;
  referenceStatus("");
});
const dropZone = $("reference-drop");
dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!dropZone.disabled) dropZone.classList.add("dragging");
});
dropZone.addEventListener("dragleave", () =>
  dropZone.classList.remove("dragging"),
);
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  event.stopPropagation();
  dropZone.classList.remove("dragging");
  if (dropZone.disabled) return;
  const files = event.dataTransfer.files;
  if (files.length !== 1) {
    referenceStatus("Drop one reference photo at a time.", true);
    return;
  }
  describeReference(files[0]);
});
for (const name of ["dragover", "drop"]) {
  document.addEventListener(name, (event) => {
    if ([...event.dataTransfer.types].includes("Files")) event.preventDefault();
  });
}
setBusy(true);
async function initialize() {
  try {
    const config = await api("/api/config");
    $("cookies").value = config.default_cookies;
    referencesSupported = config.reference_upload === true;
    rankSelectionSupported = config.rank_selection === true;
    if (!rankSelectionSupported)
      $("selection-help").textContent =
        "Restart the app to enable selection by rank. Your saved results remain available until then.";
    maxUploadBytes = config.max_upload_bytes || maxUploadBytes;
    if (!referencesSupported)
      $("reference-help").textContent =
        "Photo references need the updated app. Let your current search finish, then restart to enable uploads.";
    updateConnectionHelp();
    await restore();
    if (referencesSupported) await reconnectReference();
  } catch {
    setBusy(false);
    showError(
      "The local app isn't responding",
      "Start the app in your terminal, then reconnect.",
      initialize,
      "Reconnect",
    );
  }
}
initialize();
