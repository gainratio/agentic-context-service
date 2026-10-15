// Offline demo page. Every answer comes from the real POST /v1/context:retrieve route,
// reached through the demo's built-in gateway at /demo/api/ask.

const ALL_CORPORA = ["pricing", "product", "support", "approved-decisions"];
const REFUSALS = {
  POLICY_DENIED: "this assistant asked for a collection its job does not allow, so nothing was searched.",
  UNAUTHENTICATED: "the request's identity or signature did not check out.",
};

const $ = (selector) => document.querySelector(selector);
const state = { scenario: null };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function assistantById(id) {
  return state.scenario.assistants.find((assistant) => assistant.id === id);
}

function companyName(tenantId) {
  const match = state.scenario.assistants.find((assistant) => assistant.tenant_id === tenantId);
  return match ? match.company : tenantId;
}

function humanAge(seconds) {
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes old`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} hours old`;
  return `${Math.round(seconds / 86400)} days old`;
}

function renderMode(mode) {
  $("[data-mode-title]").textContent = mode.title;
  $("[data-mode-summary]").textContent = mode.summary;
}

function renderAssistants(assistants) {
  const select = $("[data-assistant]");
  for (const assistant of assistants) {
    const option = element("option", "", `${assistant.label} (${assistant.company})`);
    option.value = assistant.id;
    select.append(option);
  }
  select.addEventListener("change", () => selectAssistant(select.value));
}

function renderCorpora() {
  const box = $("[data-corpora]");
  for (const corpus of ALL_CORPORA) {
    const label = element("label", "check");
    const input = element("input");
    input.type = "checkbox";
    input.name = "corpora";
    input.value = corpus;
    label.append(input, document.createTextNode(` ${corpus}`));
    box.append(label);
  }
}

function setCorpora(corpora) {
  for (const input of document.querySelectorAll('input[name="corpora"]')) {
    input.checked = corpora.includes(input.value);
  }
}

function selectAssistant(id, corpora) {
  const assistant = assistantById(id);
  $("[data-assistant]").value = id;
  $("[data-assistant-hint]").textContent =
    `Works for ${assistant.company}. Job (purpose): ${assistant.purpose}. Normally searches: ${assistant.corpora.join(", ")}.`;
  setCorpora(corpora ?? assistant.corpora);
}

function renderExamples(examples) {
  const list = $("[data-examples]");
  for (const example of examples) {
    const button = element("button", "example", example.label);
    button.type = "button";
    button.addEventListener("click", () => runExample(example));
    list.append(button);
  }
}

function runExample(example) {
  selectAssistant(example.assistant, example.corpora);
  $("#question").value = example.question;
  const expect = $("[data-expect]");
  expect.textContent = `What to look for: ${example.expect}`;
  expect.hidden = false;
  ask();
}

function chosenCorpora() {
  return [...document.querySelectorAll('input[name="corpora"]:checked')].map((input) => input.value);
}

function renderRequest(request) {
  const lines = [`${request.method} ${request.path}`];
  for (const [name, value] of Object.entries(request.headers)) lines.push(`${name}: ${value}`);
  lines.push("", JSON.stringify(request.body, null, 2));
  $("[data-request]").textContent = lines.join("\n");
}

function resultCard(result) {
  const item = element("li", "result");
  item.append(element("p", "result-text", result.text));
  const citation = result.citation;
  const meta = element("p", "result-meta");
  meta.append(
    element("span", "pill", `record ${citation.record_id}`),
    element("span", "", `${citation.source_uri} · version ${citation.source_version}`),
    element("span", "", humanAge(result.freshness.age_seconds)),
    element("span", "", `trust: ${result.trust_class}`),
  );
  item.append(meta);
  return item;
}

function renderResponse(response) {
  const results = $("[data-results]");
  results.replaceChildren();
  $("[data-response]").textContent = JSON.stringify(response.body, null, 2);
  const status = $("[data-status]");
  if (response.status !== 200) {
    status.dataset.tone = "refused";
    const why = REFUSALS[response.body.code] ?? "the service refused the request.";
    status.textContent = `${response.status} ${response.body.code}: ${why}`;
    return [];
  }
  const found = response.body.results;
  status.dataset.tone = found.length ? "ok" : "empty";
  status.textContent = found.length
    ? `200 OK: ${found.length} passage(s), checked by policy ${response.body.retrieval.policy_decision_id}.`
    : "200 OK: nothing this assistant may read matches the question.";
  results.append(...found.map(resultCard));
  return found.map((result) => result.citation.record_id);
}

function hiddenReason(record, assistant, corpora) {
  if (record.tenant_id !== assistant.tenant_id) return "Hidden: another company's record";
  if (!record.purposes.includes(assistant.purpose)) return `Hidden: not cleared for ${assistant.purpose}`;
  if (!corpora.includes(record.corpus)) return "Not searched: collection not requested";
  return "Not returned: not a match for the question";
}

function outcome(record, context) {
  if (!context) return ["", "—"];
  if (context.refused) return ["refused", "Not searched: request refused"];
  if (context.returned.includes(record.record_id)) return ["returned", "Returned"];
  return ["hidden", hiddenReason(record, context.assistant, context.corpora)];
}

function renderRecords(context) {
  const body = $("[data-records]");
  body.replaceChildren();
  for (const record of state.scenario.records) {
    const row = element("tr");
    const [tone, label] = outcome(record, context);
    const title = element("td");
    title.append(element("strong", "", record.record_id), element("span", "cell-text", record.text));
    row.append(
      title,
      element("td", "", companyName(record.tenant_id)),
      element("td", "", record.corpus),
      element("td", "", record.purposes.join(", ")),
      element("td", "", record.classification),
      element("td", `outcome ${tone}`, label),
    );
    body.append(row);
  }
}

async function ask(event) {
  event?.preventDefault();
  const assistant = assistantById($("[data-assistant]").value);
  const corpora = chosenCorpora();
  const question = $("#question").value.trim();
  if (!question || corpora.length === 0) {
    $("[data-status]").textContent = "Type a question and pick at least one collection.";
    return;
  }
  const button = $("[data-ask-button]");
  button.disabled = true;
  try {
    const reply = await fetch("api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assistant: assistant.id, question, corpora }),
    });
    const payload = await reply.json();
    renderRequest(payload.request);
    const returned = renderResponse(payload.response);
    renderRecords({ assistant, corpora, returned, refused: payload.response.status !== 200 });
  } finally {
    button.disabled = false;
  }
}

async function start() {
  const reply = await fetch("api/scenario");
  state.scenario = await reply.json();
  renderMode(state.scenario.mode);
  renderAssistants(state.scenario.assistants);
  renderCorpora();
  renderExamples(state.scenario.examples);
  selectAssistant(state.scenario.assistants[0].id);
  renderRecords(null);
  $("[data-ask-form]").addEventListener("submit", ask);
  document.body.dataset.ready = "true";
}

start();
