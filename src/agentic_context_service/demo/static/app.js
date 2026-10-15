// Offline demo page. Every answer comes from the real POST /v1/context:retrieve route,
// reached through the demo's built-in gateway at /demo/api/ask, which also explains
// what happened to each record using the service's own permission check.

const GROUPS = { pricing: "pricing rules", product: "product facts", support: "help-desk policies", "approved-decisions": "approved decisions" };
const BADGES = { returned: "Sent", set_aside: "Blocked", not_searched: "Not searched", no_match: "Allowed, but not a match" };

const $ = (selector) => document.querySelector(selector);
const state = { scenario: null, example: null };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function assistantById(id) {
  return state.scenario.assistants.find((assistant) => assistant.id === id);
}

function shopName(tenantId) {
  return state.scenario.assistants.find((assistant) => assistant.tenant_id === tenantId)?.company ?? tenantId;
}

function age(isoTime) {
  const seconds = (Date.now() - Date.parse(isoTime)) / 1000;
  if (seconds < 5400) return `updated ${Math.max(1, Math.round(seconds / 60))} minutes ago`;
  if (seconds < 172800) return `updated ${Math.round(seconds / 3600)} hours ago`;
  return `updated ${Math.round(seconds / 86400)} days ago`;
}

function sourceLine(result) {
  const citation = result.citation;
  const system = citation.source_uri.replace("postgres://", "").split("/")[0];
  return `Source: the ${system} database, record ${citation.record_id}, edit number ${citation.source_version}, ${age(result.freshness.source_updated_at)}`;
}

function list(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

// ---------- setup ----------

function renderSetup(scenario) {
  $("[data-mode-title]").textContent = scenario.mode.title;
  $("[data-mode-summary]").textContent = scenario.mode.summary;
  $("[data-mode-details]").textContent = scenario.mode.details;
  for (const assistant of scenario.assistants) {
    const option = element("option", "", `${assistant.label} (${assistant.company})`);
    option.value = assistant.id;
    $("[data-assistant]").append(option);
  }
  $("[data-assistant]").addEventListener("change", (event) => setGroups(assistantById(event.target.value).corpora));
  for (const [corpus, label] of Object.entries(GROUPS)) {
    const box = element("label", "check");
    const input = element("input");
    Object.assign(input, { type: "checkbox", name: "corpora", value: corpus });
    box.append(input, document.createTextNode(` ${label}`));
    $("[data-corpora]").append(box);
  }
  for (const example of scenario.examples) {
    const button = element("button", "example", example.label);
    button.type = "button";
    button.addEventListener("click", () => runExample(example, button));
    $("[data-examples]").append(button);
  }
  setGroups(scenario.assistants[0].corpora);
}

function setGroups(corpora) {
  for (const input of document.querySelectorAll('input[name="corpora"]')) input.checked = corpora.includes(input.value);
}

function runExample(example, button) {
  for (const other of document.querySelectorAll(".example")) other.setAttribute("aria-pressed", String(other === button));
  $("[data-assistant]").value = example.assistant;
  $("#question").value = example.question;
  setGroups(example.corpora);
  state.example = example;
  ask();
}

// ---------- the four steps ----------

function renderQuestion(assistant, question) {
  $("[data-who]").textContent = `${assistant.label} at ${assistant.company}. It works for ${assistant.job}.`;
  $("[data-question]").textContent = `“${question}”`;
}

function captions(assistant, payload, corpora) {
  const lines = [`Checked the request's signature (a tamper-proof tag the shop's systems attach), so it really comes from ${assistant.company}'s ${assistant.label.toLowerCase()}.`];
  if (payload.response.status !== 200) {
    const asked = list(corpora.map((corpus) => GROUPS[corpus]));
    lines.push(`Refused: it asked to open ${asked}, which ${assistant.job} may not read. Nothing was searched and nothing was sent.`);
    return lines;
  }
  const setAside = payload.outcomes.filter((outcome) => outcome.status === "set_aside").length;
  const sent = payload.response.body.results.length;
  lines.push(`Looked up what ${assistant.job} is allowed to read: ${list(payload.allowed_groups)}.`);
  lines.push(`Blocked ${setAside} of the 7 records that this assistant may not see.`);
  lines.push(sent ? `Searched the rest for the question's words and sent back the ${sent} closest match${sent === 1 ? "" : "es"}.` : "Searched the rest for the question's words. Nothing allowed matched.");
  return lines;
}

function renderCaptions(lines) {
  const box = $("[data-captions]");
  box.replaceChildren(...lines.map((line, index) => {
    const item = element("li", "caption", line);
    item.style.setProperty("--delay", `${index * 250}ms`);
    return item;
  }));
}

function resultCard(result) {
  const item = element("li", "result");
  item.append(element("p", "result-text", result.text), element("p", "result-source", sourceLine(result)));
  return item;
}

function renderAnswer(response) {
  const status = $("[data-status]");
  const results = response.status === 200 ? response.body.results : [];
  $("[data-results]").replaceChildren(...results.map(resultCard));
  if (response.status !== 200) {
    status.dataset.tone = "refused";
    status.textContent = "Nothing. The service said no.";
  } else {
    status.dataset.tone = results.length ? "ok" : "empty";
    status.textContent = results.length
      ? (results.length === 1 ? "1 fact, with where it came from:" : `${results.length} facts, each with where it came from:`)
      : "Nothing: no record this assistant may see matches the question.";
  }
}

function renderSummary(payload) {
  const count = (status) => payload.outcomes.filter((outcome) => outcome.status === status).length;
  $("[data-why]").textContent = state.example?.why ?? "Every record was checked against this assistant's job before anything was searched.";
  const parts = Object.entries(BADGES).map(([status, label]) => [label, count(status)]).filter(([, n]) => n > 0);
  $("[data-tally]").textContent = `Of the 7 records: ${parts.map(([label, n]) => `${n} ${label.toLowerCase()}`).join(" · ")}.`;
}

function recordCard(record, outcome) {
  const item = element("li", `record ${outcome.status}`);
  const head = element("div", "record-head");
  head.append(element("strong", "", record.title), element("span", `badge ${outcome.status}`, BADGES[outcome.status]));
  const meta = `${shopName(record.tenant_id)}, ${record.group}. Who may read it: ${list(record.readers)}.`;
  item.append(head, element("p", "record-reason", outcome.reason), element("p", "record-meta", meta));
  return item;
}

function renderRecords(outcomes) {
  const byId = Object.fromEntries(outcomes.map((outcome) => [outcome.record_id, outcome]));
  $("[data-records]").replaceChildren(...state.scenario.records.map((record) => recordCard(record, byId[record.record_id])));
}

function renderDeveloper(request, response) {
  const lines = [`${request.method} ${request.path}`, ...Object.entries(request.headers).map(([name, value]) => `${name}: ${value}`)];
  lines.push("", JSON.stringify(request.body, null, 2));
  $("[data-request]").textContent = lines.join("\n");
  $("[data-response]").textContent = JSON.stringify(response.body, null, 2);
}

function render(assistant, question, corpora, payload) {
  renderQuestion(assistant, question);
  renderCaptions(captions(assistant, payload, corpora));
  renderAnswer(payload.response);
  renderSummary(payload);
  renderRecords(payload.outcomes);
  renderDeveloper(payload.request, payload.response);
  const run = $("[data-run]");
  run.hidden = false;
  run.classList.remove("play");
  void run.offsetWidth; // restart the reveal animation
  run.classList.add("play");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  run.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
}

// ---------- talking to the service ----------

async function getJson(url, options) {
  const reply = await fetch(url, options);
  if (!reply.ok) throw new Error(`${reply.status} ${reply.statusText}`);
  return reply.json();
}

function showProblem(text) {
  const run = $("[data-run]");
  run.hidden = false;
  const status = $("[data-status]");
  status.dataset.tone = "refused";
  status.textContent = text;
}

async function ask(event) {
  if (event) {
    event.preventDefault();
    state.example = null;
  }
  const assistant = assistantById($("[data-assistant]").value);
  const corpora = [...document.querySelectorAll('input[name="corpora"]:checked')].map((input) => input.value);
  const question = $("#question").value.trim();
  if (!question || corpora.length === 0) return showProblem("Type a question and pick at least one record group.");
  const button = $("[data-ask-button]");
  button.disabled = true;
  try {
    const payload = await getJson("api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assistant: assistant.id, question, corpora }),
    });
    render(assistant, question, corpora, payload);
  } catch (error) {
    showProblem(`Could not reach the demo service (${error.message}). Is make demo still running?`);
  } finally {
    button.disabled = false;
  }
}

async function start() {
  try {
    state.scenario = await getJson("api/scenario");
  } catch (error) {
    return showProblem(`Could not load the demo (${error.message}). Restart it with make demo.`);
  }
  renderSetup(state.scenario);
  $("[data-ask-form]").addEventListener("submit", ask);
  document.body.dataset.ready = "true";
}

start();
