"use strict";
window.MSR_ENGINE = ({ L, api, el, facts, date, isVisible, onRead }) => {
  const $ = id => document.getElementById(id);
  const actions = { start: L.m("Uruchom silnik"), stop: L.m("Zatrzymaj silnik"), restart: L.m("Uruchom ponownie silnik") };
  const states = { ready: L.m("Gotowy"), starting: L.m("Uruchamianie"), stopping: L.m("Zatrzymywanie"), stopped: L.m("Zatrzymany"), failed: L.m("Błąd"), degraded: L.m("Proces działa, gotowość niepotwierdzona"), unknown: L.m("Stan nieznany") };
  const outcomes = { queued: L.m("W kolejce"), running: L.m("W toku"), succeeded: L.m("Wykonano"), failed: L.m("Błąd"), timed_out: L.m("Upłynął czas oczekiwania"), interrupted: L.m("Przerwano sterowanie; sprawdź stan silnika") };
  const errors = {
    stale_revision: L.m("Stan silnika zmienił się. Odczytaj go ponownie i sprawdź nowe potwierdzenie."),
    job_in_progress: L.m("Inna operacja trwa. Poczekaj na jej wynik."),
    action_unavailable: L.m("Ta operacja jest niedostępna w obecnym stanie silnika."),
    state_unavailable: L.m("Nie udało się potwierdzić stanu silnika. Sterowanie jest zablokowane do świeżego odczytu."),
    storage_unavailable: L.m("Nie udało się zapisać wyniku operacji. Sprawdź historię przed ponowieniem."),
    command_failed: L.m("System odrzucił polecenie. Sprawdź usługę na serwerze."),
    readiness_timeout: L.m("Silnik nie potwierdził gotowości w wyznaczonym czasie. Nie ponowiono operacji."),
    control_restarted: L.m("Usługa sterowania uruchomiła się ponownie. Polecenia nie powtórzono."),
    state_changed_before_execution: L.m("Stan silnika zmienił się przed wykonaniem polecenia."),
  };
  let data = null, timer = null, request = 0, review = null, submitting = false, pending = null, fresh = false;
  try { pending = JSON.parse(sessionStorage.getItem("msr-engine-request") || "null"); } catch {}
  if (pending && !/^[0-9a-f-]{36}$/.test(pending.requestId || "")) pending = null;
  const terminal = job => job && ["succeeded", "failed", "timed_out", "interrupted"].includes(job.status);
  function remember(value) { pending = value; try { if (value) sessionStorage.setItem("msr-engine-request", JSON.stringify(value)); else sessionStorage.removeItem("msr-engine-request"); } catch {} }
  function message(error) { return errors[error?.code] || L.errorMessage(error); }
  function showError(error) { const box = $("engine-error"); L.text(box, message(error)); box.hidden = false; }
  function render() {
    if (!data) return;
    const service = data.service;
    L.text($("engine-state"), states[service.state] || states.unknown);
    $("engine-facts").replaceChildren(facts([
      [L.m("Usługa"), data.target], [L.m("Host"), data.host], [L.m("Odczyt"), date(data.observedAt)],
      [L.m("Wersja silnika"), service.release || "—"], [L.m("PID"), service.pid || "—"],
      [L.m("Aktywne sesje"), service.activeSessions ?? L.m("Brak potwierdzenia")],
      [L.m("Stan systemd"), [service.activeState, service.subState].filter(Boolean).join(" / ")],
    ]));
    for (const action of Object.keys(actions)) $("engine-" + action).disabled = submitting || !!pending || !!data.activeJob || !data.allowedActions.includes(action);
    const jobs = $("engine-jobs"); jobs.replaceChildren();
    const rows = [...new Map([data.activeJob, data.requestedJob, ...(data.recentJobs || [])].filter(Boolean).map(job => [job.id, job])).values()];
    for (const job of rows) {
      const article = el("article", null, "engine-job");
      article.append(el("h3", L.join(actions[job.action] || job.action, " · ", outcomes[job.status] || job.status)),
        el("p", L.join(date(job.acceptedAt), " · ", job.id), "hint"));
      if (job.error) article.append(el("p", errors[job.error] || job.error, "error"));
      if (job.after) article.append(el("p", L.join(states[job.before?.state] || "—", " → ", states[job.after.state] || "—")));
      jobs.append(article);
    }
    if (!rows.length) jobs.append(el("p", L.m("Brak operacji silnika."), "empty-state"));
    $("engine-uncertain").hidden = !pending;
    $("engine-clear-unknown").hidden = !pending || !!data.requestedJob || !!data.activeJob;
  }
  async function load() {
    clearTimeout(timer);
    const epoch = ++request;
    fresh = false; $("engine-clear-unknown").disabled = true;
    for (const action of Object.keys(actions)) $("engine-" + action).disabled = true;
    try {
      const next = await api("engine" + (pending ? "?requestId=" + encodeURIComponent(pending.requestId) : ""));
      if (epoch !== request) return;
      if (!next.service?.state || !Array.isArray(next.allowedActions) || !/^[a-f0-9]{64}$/.test(next.revision || "") || next.target !== "monster-slayer-game.service") throw new L.Error(L.m("Niepoprawna odpowiedź panelu. "));
      data = next;
      fresh = true; $("engine-clear-unknown").disabled = false;
      if (pending && terminal(next.requestedJob)) remember(null);
      $("engine-error").hidden = true;
      render();
      onRead(true); return true;
    } catch (error) {
      if (epoch !== request) return;
      fresh = false; $("engine-clear-unknown").disabled = true;
      showError(error);
      for (const action of Object.keys(actions)) $("engine-" + action).disabled = true;
      L.text($("engine-state"), L.m("Brak świeżego odczytu"));
      onRead(false); return false;
    } finally {
      if (epoch === request && isVisible()) timer = setTimeout(load, data?.activeJob || pending ? 2500 : 10000);
    }
  }
  function stop() { clearTimeout(timer); request++; }
  function open(action) {
    if (!fresh || !data || pending || submitting || data.activeJob || !data.allowedActions.includes(action)) return;
    review = { action, revision: data.revision, requestId: crypto.randomUUID(), confirm: data.target };
    L.text($("engine-dialog-title"), actions[action]);
    $("engine-review").replaceChildren(facts([
      [L.m("Host"), data.host], [L.m("Usługa"), data.target], [L.m("Stan"), states[data.service.state] || states.unknown],
      [L.m("Wersja silnika"), data.service.release || "—"], [L.m("Aktywne sesje"), data.service.activeSessions ?? L.m("Brak potwierdzenia")],
    ]));
    L.text($("engine-effect"), action === "start" ? L.m("Silnik uruchomi bieżącą wersję i istniejące zapisy. Oczekiwanie na gotowość może potrwać do 3 minut.") : L.m("Bieżące połączenia graczy zostaną przerwane. Zapisy i zatwierdzone dostępy pozostają. Panel nadal pozwoli uruchomić silnik."));
    $("engine-reviewed").checked = false;
    $("engine-dialog-error").hidden = true;
    $("engine-dialog").showModal(); $("engine-dialog-title").focus();
  }
  for (const action of Object.keys(actions)) $("engine-" + action).addEventListener("click", () => open(action));
  $("engine-check").addEventListener("click", load);
  $("engine-clear-unknown").addEventListener("click", () => {
    if (!fresh || data?.requestedJob || data?.activeJob) return;
    if (!window.confirm(String(L.m("Nie znaleziono operacji w odczytanej historii. Zamknąć oczekiwanie i wrócić do oceny bieżącego stanu? Żadne polecenie nie zostanie wysłane.")))) return;
    remember(null); void load();
  });
  $("engine-dialog-close").addEventListener("click", () => { if (!submitting) $("engine-dialog").close(); });
  $("engine-dialog").addEventListener("cancel", event => { if (submitting) event.preventDefault(); });
  $("engine-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting || !review || !$("engine-reviewed").checked || pending) return;
    submitting = true; remember(review);
    $("engine-submit").disabled = true; $("engine-dialog-close").disabled = true;
    try {
      const result = await api("engine", { method: "POST", body: JSON.stringify(review) });
      if (!result.job?.id || result.job.requestId !== review.requestId || !["queued", "running", "succeeded", "failed", "timed_out", "interrupted"].includes(result.job.status)) throw Object.assign(new L.Error(L.m("Brak potwierdzenia")), { uncertain: true });
      if (terminal(result.job)) remember(null);
      $("engine-dialog").close();
    } catch (error) {
      // No automatic retry. Reconcile the durable request ID through GET first.
      if (!error.uncertain && error.status && error.status < 500) remember(null);
      L.text($("engine-dialog-error"), message(error)); $("engine-dialog-error").hidden = false;
      $("engine-dialog-error").focus(); review = null;
    } finally {
      submitting = false; $("engine-dialog-close").disabled = false;
      await load();
    }
  });
  $("engine-dialog").addEventListener("close", () => { review = null; $("engine-submit").disabled = false; });
  return { load, stop };
};
