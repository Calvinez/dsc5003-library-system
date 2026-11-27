import { messages } from "./messages.js";

const byId = (id) => document.getElementById(id);
const ui = {
  search: byId("search"),
  searchInput: byId("search-input"),
  catalog: byId("catalog"),
  catalogResults: byId("catalog-results"),
  resultCount: byId("result-count"),
  loans: byId("loans"),
  loanResults: byId("loan-results"),
  loanCount: byId("loan-count"),
  language: byId("language"),
  readerAction: byId("reader-action"),
  dialog: byId("reader-dialog"),
  readerForm: byId("reader-form"),
  token: byId("token"),
  signInError: byId("sign-in-error"),
  signInSubmit: byId("submit-sign-in"),
  notice: byId("notice"),
  noticeCopy: byId("notice-copy"),
};

const state = {
  locale: readLanguage(),
  query: "",
  books: null,
  isbn: null,
  copies: null,
  loans: null,
  token: null,
  signInTriggerId: null,
  signInAttempt: null,
  signInError: null,
  write: null,
  notice: null,
};
const localeCodes = { zh: "zh-CN", en: "en-GB" };
const copyStatuses = {
  AVAILABLE: "chip-good",
  ON_LOAN: "chip-warm",
  MAINTENANCE: "",
  WITHDRAWN: "",
};

function readLanguage() {
  try {
    return localStorage.getItem("library-language") === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}

function t(key, values = {}) {
  const dictionary = messages[state.locale];
  const template = Object.hasOwn(dictionary, key) ? dictionary[key] : dictionary.unexpected;
  return template.replace(/\{(\w+)\}/g, (match, field) => values[field] ?? match);
}

function node(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (typeof content === "string") element.textContent = content;
  else if (content) element.append(...content);
  return element;
}

function action(label, variant, onClick, { id, disabled = false } = {}) {
  const button = node("button", "button button-" + variant, t(label));
  button.type = "button";
  if (id) button.id = id;
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}

function replaceResults(container, content, fallbackId) {
  const active = document.activeElement;
  const focusedId = container.contains(active) ? active.id : null;
  container.replaceChildren(...content);
  if (focusedId) {
    const replacement = byId(focusedId);
    const fallback = byId(fallbackId);
    (replacement && !replacement.disabled ? replacement : fallback)?.focus({ preventScroll: true });
  }
}

function formatDate(value) {
  if (!value || Number.isNaN(Date.parse(value))) return t("noDate");
  return new Intl.DateTimeFormat(localeCodes[state.locale], {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

function dateField(label, value) {
  const time = node("time", "", formatDate(value));
  if (value) time.dateTime = value;
  const content = value ? [time] : t("noDate");
  return node("div", "", [node("dt", "", t(label)), node("dd", "", content)]);
}

function recordMeta(...values) {
  return node("p", "record-meta", values.map((value) => node("span", "", value)));
}

function statusPanel(key, button, isError = false) {
  const message = node("p", "", t(key));
  if (isError) message.setAttribute("role", "alert");
  return node("div", isError ? "state-panel state-error" : "state-panel", button ? [message, button] : [message]);
}

function renderResource(resource, { loading, empty, retry, retryId, renderItems }) {
  if (!resource || resource.loading) {
    const panel = statusPanel(loading);
    panel.setAttribute("role", "status");
    return panel;
  }
  if (resource.error) {
    return statusPanel(resource.error, action("retry", "outline", retry, { id: retryId }), true);
  }
  return resource.items.length ? renderItems(resource.items) : statusPanel(empty);
}

function renderCopy(copy) {
  const availability = Object.hasOwn(copyStatuses, copy.availability) ? copy.availability : "UNKNOWN";
  const status = node("span", "chip " + (copyStatuses[availability] || ""), t(availability));
  const actions = [status];
  if (availability === "AVAILABLE") {
    const pending = state.write?.type === "borrow" && state.write.barcode === copy.barcode;
    const label = state.token ? (pending ? "borrowing" : "borrow") : "signInToBorrow";
    const button = action(label, "primary", (event) => {
      if (state.token) void changeLoan("borrow", copy);
      else openSignIn(event.currentTarget);
    }, { id: "borrow-" + copy.copy_id, disabled: Boolean(state.write) });
    button.setAttribute("aria-label", t(label) + " · " + copy.barcode);
    actions.push(button);
  }
  return node("li", "copy-row", [
    node("div", "record-main", [
      node("strong", "isbn", copy.barcode),
      recordMeta(t("shelf", { shelf: copy.shelf_code })),
    ]),
    node("div", "copy-action", actions),
  ]);
}

function renderBook(book) {
  const expanded = state.isbn === book.isbn;
  const copiesId = "copies-" + book.isbn;
  const button = action(expanded ? "hideCopies" : "viewCopies", "outline", () => {
    if (state.isbn === book.isbn) {
      state.isbn = null;
      state.copies = null;
      renderCatalog();
    } else {
      void loadCopies(book.isbn);
    }
  }, { id: "book-" + book.isbn });
  button.setAttribute("aria-expanded", String(expanded));
  button.setAttribute("aria-controls", copiesId);
  button.setAttribute("aria-label", button.textContent + " · " + book.title);

  const mark = node("span", "book-mark", [node("span", "book-icon")]);
  mark.setAttribute("aria-hidden", "true");
  const summary = node("div", "book-summary", [
    mark,
    node("div", "record-main", [
      node("h3", "record-title", book.title),
      recordMeta(book.category, book.publisher, t("isbn", { isbn: book.isbn })),
    ]),
    button,
  ]);

  const details = node("div", "copies");
  details.id = copiesId;
  details.hidden = !expanded;
  if (expanded) {
    const title = node("h4", "", t("copies"));
    const refresh = action("refresh", "quiet", () => void loadCopies(book.isbn), {
      id: "refresh-" + book.isbn,
      disabled: Boolean(state.write || state.copies?.loading),
    });
    const headings = node("div", "section-actions", [title, refresh]);
    details.append(headings, renderResource(state.copies, {
      loading: "loadingCopies",
      empty: "emptyCopies",
      retry: () => void loadCopies(book.isbn),
      retryId: "retry-copies",
      renderItems: (copies) => node("ul", "copy-list", copies.map(renderCopy)),
    }));
  }

  const bookCard = node("li", "record", [summary, details]);
  if (expanded) bookCard.classList.add("record-expanded");
  return bookCard;
}

function renderCatalog() {
  const items = state.books?.items;
  ui.resultCount.textContent = items ? t(items.length === 20 ? "bookLimit" : "bookCount", { count: items.length }) : "";
  const content = renderResource(state.books, {
    loading: "loadingBooks",
    empty: "emptyBooks",
    retry: () => void loadBooks(state.query),
    retryId: "retry-books",
    renderItems: (books) => node("ul", "records", books.map(renderBook)),
  });
  replaceResults(ui.catalogResults, [content], state.isbn ? "book-" + state.isbn : "search-input");
}

function renderLoan(loan) {
  const returned = loan.returned_at !== null;
  const status = node("span", returned ? "chip chip-good" : "chip chip-warm", t(returned ? "returned" : "active"));
  const actions = [status];
  if (!returned) {
    const pending = state.write?.type === "return" && state.write.id === loan.loan_id;
    const label = pending ? "returning" : "returnBook";
    const button = action(label, "primary", () => void changeLoan("return", loan), {
      id: "return-" + loan.loan_id,
      disabled: Boolean(state.write),
    });
    button.setAttribute("aria-label", t(label) + " · " + loan.title + " · " + loan.barcode);
    actions.push(button);
  }
  return node("li", "record", [node("div", "loan-summary", [
    node("div", "record-main", [
      node("h3", "record-title", loan.title),
      recordMeta(t("barcode", { barcode: loan.barcode })),
      node("dl", "loan-dates", [
        dateField("borrowedOn", loan.borrowed_at),
        dateField("dueOn", loan.due_at),
        dateField("returnedOn", loan.returned_at),
      ]),
    ]),
    node("div", "loan-action", actions),
  ])]);
}

function renderLoans() {
  if (!state.token) {
    ui.loanCount.textContent = "";
    const signIn = action("signIn", "primary", (event) => openSignIn(event.currentTarget), { id: "loans-sign-in" });
    replaceResults(ui.loanResults, [statusPanel("signInForLoans", signIn)], "reader-action");
    return;
  }

  const items = state.loans?.items;
  ui.loanCount.textContent = items ? t("loanCount", { count: items.length }) : "";
  const content = renderResource(state.loans, {
    loading: "loadingLoans",
    empty: "emptyLoans",
    retry: () => void loadLoans(),
    retryId: "retry-loans",
    renderItems: (loans) => node("ul", "records", loans.map(renderLoan)),
  });
  const refresh = action("refresh", "outline", () => void loadLoans(), {
    id: "refresh-loans",
    disabled: Boolean(state.write || state.loans?.loading),
  });
  replaceResults(ui.loanResults, [node("div", "loans-toolbar", [refresh]), content], "loans-title");
}

function renderReader() {
  ui.readerAction.textContent = t(state.token ? "signOut" : "signIn");
  ui.readerAction.disabled = Boolean(state.write);
  ui.token.readOnly = Boolean(state.signInAttempt);
  ui.signInSubmit.disabled = Boolean(state.signInAttempt);
  ui.signInSubmit.textContent = t(state.signInAttempt ? "connecting" : "connect");
  ui.signInError.hidden = !state.signInError;
  ui.signInError.textContent = state.signInError ? t(state.signInError) : "";
}

function setNotice(key, data = {}) {
  state.notice = { key, ...data };
  renderNotice();
}

function renderNotice() {
  ui.notice.hidden = state.notice === null;
  if (!state.notice) {
    ui.noticeCopy.replaceChildren();
    return;
  }
  const { key, values = {}, tone = "success", failedRefreshes = [] } = state.notice;
  ui.notice.dataset.tone = tone;
  const messages = [node("p", "", t(key, { ...values, due: formatDate(values.due) }))];
  if (failedRefreshes.length) messages.push(node("p", "", t("refreshFailed")));
  ui.noticeCopy.replaceChildren(...messages);
}

function renderLanguage() {
  document.documentElement.lang = localeCodes[state.locale];
  document.title = t("brand");
  for (const element of document.querySelectorAll("[data-text], [data-label], [data-placeholder]")) {
    if (element.dataset.text) element.textContent = t(element.dataset.text);
    if (element.dataset.label) element.setAttribute("aria-label", t(element.dataset.label));
    if (element.dataset.placeholder) element.placeholder = t(element.dataset.placeholder);
  }
  ui.language.textContent = state.locale === "zh" ? "English" : "简体中文";
  ui.language.lang = state.locale === "zh" ? "en" : "zh-CN";
  renderCatalog();
  renderLoans();
  renderReader();
  renderNotice();
}

class RequestError extends Error {
  constructor(code, status = 0) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function api(path, { token, body, method = "GET" } = {}) {
  const headers = new Headers({ Accept: "application/json" });
  if (token) {
    try {
      headers.set("Authorization", "Bearer " + token);
    } catch {
      throw new RequestError("unauthorized", 401);
    }
  }
  if (body !== undefined) headers.set("Content-Type", "application/json");
  let response;
  try {
    response = await fetch("/api" + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new RequestError("network");
  }
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new RequestError(result?.error?.code ?? "unexpected", response.status);
  if (!result || typeof result !== "object") throw new RequestError("unexpected");
  return result;
}

async function getItems(path, token) {
  const result = await api(path, { token });
  if (!Array.isArray(result.items)) throw new RequestError("unexpected");
  return result.items;
}

// A newer search, copy selection, or session replaces the pending resource.
async function loadResource(name, render, path, token) {
  const pending = { loading: true };
  state[name] = pending;
  render();
  let result;
  try {
    result = { items: await getItems(path, token) };
  } catch (error) {
    result = { error: error.code ?? "unexpected", status: error.status };
  }
  if (state[name] !== pending) return true;
  if (name === "loans" && result.status === 401) {
    endSession("sessionExpired", "error");
    return false;
  }
  state[name] = result;
  render();
  if (!result.error && state.notice?.failedRefreshes?.includes(name)) {
    state.notice.failedRefreshes = state.notice.failedRefreshes.filter((resource) => resource !== name);
    renderNotice();
  }
  return !result.error;
}

function loadBooks(query) {
  state.query = query;
  state.isbn = null;
  state.copies = null;
  return loadResource("books", renderCatalog, "/books?" + new URLSearchParams({ q: query }));
}

function loadCopies(isbn) {
  state.isbn = isbn;
  return loadResource("copies", renderCatalog, "/books/" + encodeURIComponent(isbn) + "/copies");
}

function loadLoans() {
  return state.token ? loadResource("loans", renderLoans, "/loans", state.token) : Promise.resolve(true);
}

function refreshLoansAndCopies() {
  return Promise.all([loadLoans(), state.isbn ? loadCopies(state.isbn) : true]);
}

function openSignIn(trigger) {
  if (state.token || ui.dialog.open) return;
  state.signInTriggerId = trigger.id;
  state.signInError = null;
  ui.token.value = "";
  renderReader();
  ui.dialog.showModal();
  ui.token.focus();
}

function closeSignIn() {
  const trigger = byId(state.signInTriggerId) ?? ui.readerAction;
  state.signInTriggerId = null;
  state.signInAttempt = null;
  state.signInError = null;
  ui.token.value = "";
  ui.dialog.close();
  renderReader();
  trigger.focus({ preventScroll: true });
}

async function signIn(event) {
  event.preventDefault();
  if (state.signInAttempt) return;
  const token = ui.token.value.trim();
  if (!token) {
    state.signInError = "missingToken";
    renderReader();
    return;
  }

  const attempt = {};
  state.signInAttempt = attempt;
  state.signInError = null;
  renderReader();
  try {
    const items = await getItems("/loans", token);
    if (state.signInAttempt !== attempt || !ui.dialog.open) return;
    state.token = token;
    state.loans = { items };
    closeSignIn();
    renderCatalog();
    renderLoans();
    setNotice("signedIn");
  } catch (error) {
    if (state.signInAttempt === attempt) state.signInError = error.status === 401 ? "unauthorized" : error.code;
  } finally {
    if (state.signInAttempt === attempt) {
      state.signInAttempt = null;
      renderReader();
    }
  }
}

function endSession(key, tone = "success") {
  state.token = null;
  state.loans = null;
  renderCatalog();
  renderLoans();
  renderReader();
  setNotice(key, { tone });
}

async function changeLoan(type, record) {
  if (!state.token || state.write) return;
  const isBorrow = type === "borrow";
  const barcode = record.barcode;
  const path = isBorrow ? "/loans" : "/loans/" + encodeURIComponent(record.loan_id) + "/return";
  state.write = { type, barcode, id: record.loan_id };
  state.notice = null;
  renderNotice();
  renderCatalog();
  renderLoans();
  renderReader();

  try {
    const result = await api(path, {
      method: "POST",
      body: isBorrow ? { barcode } : undefined,
      token: state.token,
    });
    if (isBorrow ? !result.due_at : !result.returned_at) throw new RequestError("unexpected");
    const refreshed = await refreshLoansAndCopies();
    const failedRefreshes = ["loans", "copies"].filter((_, index) => !refreshed[index]);
    const key = isBorrow ? "borrowSuccess" : result.already_returned ? "alreadyReturned" : "returnSuccess";
    setNotice(key, { values: { barcode, due: result.due_at }, failedRefreshes });
  } catch (error) {
    if (error.status === 401) {
      endSession("sessionExpired", "error");
    } else {
      const uncertain = !error.status || error.status === 408 || (error.status >= 500 && error.code !== "busy");
      if (uncertain || error.status === 409 || error.status === 404) await refreshLoansAndCopies();
      if (state.token) setNotice(uncertain ? "writeUncertain" : error.code, { tone: "error" });
    }
  } finally {
    state.write = null;
    renderCatalog();
    renderLoans();
    renderReader();
  }
}

function showPage(moveFocus = false) {
  if (location.hash === "#main") return;
  const page = location.hash === "#loans" ? "loans" : "catalog";
  for (const name of ["catalog", "loans"]) ui[name].hidden = page !== name;
  for (const link of document.querySelectorAll("[data-page]")) {
    if (link.dataset.page === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (moveFocus) byId(page + "-title").focus();
}

ui.search.addEventListener("submit", (event) => {
  event.preventDefault();
  void loadBooks(ui.searchInput.value.trim());
});
ui.readerAction.addEventListener("click", () => {
  if (state.token) endSession("signedOut");
  else openSignIn(ui.readerAction);
});
ui.readerForm.addEventListener("submit", (event) => void signIn(event));
byId("cancel-sign-in").addEventListener("click", closeSignIn);
ui.dialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeSignIn();
});
ui.language.addEventListener("click", () => {
  state.locale = state.locale === "zh" ? "en" : "zh";
  try {
    localStorage.setItem("library-language", state.locale);
  } catch {
    // Language switching still works when browser storage is unavailable.
  }
  renderLanguage();
});
byId("notice-dismiss").addEventListener("click", () => {
  state.notice = null;
  renderNotice();
});
window.addEventListener("hashchange", () => showPage(true));

showPage();
renderLanguage();
void loadBooks("");
