(async () => {
  "use strict";
  const L = window.MSR_ADMIN_I18N;
  await L.init();

  const $ = (id) => document.getElementById(id);
  const views = {
    engine: [L.m("Silnik"), L.m("STEROWANIE USŁUGĄ"), L.m("Uruchamianie, zatrzymywanie i wyniki operacji silnika gry.")],
    tuning: [L.m("Tuning"), L.m("YOUR OWN EXPERIENCE"), L.m("Simple values you can change to suit how you play. They are saved on this phone.")],
    testers: [L.m("Testerzy"), L.m("DOSTĘP DO LAB"), L.m("Kody instalacji, terminy dostępu i przypisania profili.")],
    overview: [
      L.m("Pulpit operatora"),
      L.m("CENTRUM DOWODZENIA"),
      L.m("Świat gry, gracze i publikacje w jednym miejscu."),
    ],
    world: [
      L.m("Mapa i spawny"),
      L.m("ATLAS ŚWIATA"),
      L.m("Edytuj częstotliwość potworów i sprawdź spotkania dostarczone klientowi."),
    ],
    weather: [
      L.m("Pogoda"),
      L.m("WARUNKI W ŚWIECIE"),
      L.m("Źródło danych i czasowe sterowanie pogodą na serwerze."),
    ],
    news: [
      L.m("Komunikaty"),
      L.m("WIADOMOŚCI DLA GRACZY"),
      L.m("Redaguj i publikuj zawartość zakładki „Co nowego”."),
    ],
    tasks: [
      L.m("Zadania i wydarzenia"),
      L.m("RYTM ROZGRYWKI"),
      L.m("Rotacja dzienna, wydarzenia czasowe, stemple i bibeloty."),
    ],
    profiles: [
      L.m("Gracze"),
      L.m("ZAPISY I POSTĘP"),
      L.m("Znajdź profil, sprawdź jego stan i wykonaj świadomą zmianę."),
    ],
    catalogue: [
      L.m("Katalog gry"),
      L.m("DANE UŻYWANE PRZEZ SERWER"),
      L.m("Potwory, przedmioty, receptury i umiejętności."),
    ],
    help: [L.m("Pomoc"), L.m("PRZEWODNIK OPERATORA"), L.m("Co można edytować, kiedy działa zmiana i jak wrócić do poprzedniej wersji.")],
    audit: [
      L.m("Historia operacji"),
      L.m("DZIENNIK OPERATORA"),
      L.m("Wyniki zapisów, przygotowane wersje i dostępne kopie."),
    ],
  };
  const rarityNames = {
    1: L.m("Pospolity"),
    2: L.m("Rzadki"),
    3: L.m("Legendarny"),
  };
  const familyNames = {
    1: L.m("Trupojady"),
    2: L.m("Drakonidy"),
    3: L.m("Ogroidy"),
    4: L.m("Hybrydy"),
    5: L.m("Istoty magiczne"),
    6: L.m("Relikty"),
    7: L.m("Upiory"),
    8: L.m("Insektoidy"),
    9: L.m("Zwierzęta"),
    10: L.m("Wampiry"),
    11: L.m("Przeklęte"),
  };
  const labels = {
    applied: L.m("Zapisano"),
    accepted: L.m("Rozpoczęto"),
    staged: L.m("Przygotowano"),
    refused: L.m("Odmowa"),
    failed: L.m("Błąd zapisu"),
  };
  const actionLabels = {
    "transport-open": L.m("Otwórz rejestrację"),
    "transport-close": L.m("Zamknij rejestrację"),
    "transport-approve": L.m("Zatwierdź kod"),
    "transport-renew": L.m("Ustaw czas dostępu"),
    "transport-rebind": L.m("Zmień przypisanie"),
    "transport-revoke": L.m("Cofnij dostęp"),
    news: L.m("Publikacja komunikatów"),
    image: L.m("Dodanie okładki"),
    world: L.m("Gęstość spotkań"),
    "spawn-balance": L.m("Częstotliwość potworów"),
    "placement-policy": L.m("Rozmieszczenie miejsc"),
    weather: L.m("Polityka pogody"),
    "daily-rotation": L.m("Rotacja dzienna"),
    "hunt-policy": L.m("Zasada stempli"),
    "task-catalogue": L.m("Nowy katalog zadań"),
    "distance-policy": L.m("Ochrona naliczania dystansu"),
    "profile-label": L.m("Etykieta operatora"),
    tuning: L.m("Tuning"),
    "profile-reset": L.m("Reset postępu"),
    "profile-copy": L.m("Kopiowanie postępu"),
    "profile-clock": L.m("Zegar fabuły"),
    "profile-restore": L.m("Przywrócenie zapisu"),
  };
  const effects = {
    "transport-open": L.m("Okno służy tylko do otrzymania kodu. Termin ważności kodu jest widoczny na liście. Zamknięcie rejestracji nie odbiera dostępu zatwierdzonym testerom."),
    "transport-close": L.m("Okno służy tylko do otrzymania kodu. Termin ważności kodu jest widoczny na liście. Zamknięcie rejestracji nie odbiera dostępu zatwierdzonym testerom."),
    "transport-approve": L.m("Czas dostępu od teraz"),
    "transport-renew": L.m("Czas dostępu od teraz"),
    "transport-rebind": L.m("Telefon zostanie rozłączony. Uruchom LAB ponownie. Zapisy obu profili i termin dostępu pozostają."),
    "transport-revoke": L.m("Telefon utraci dostęp i zostanie rozłączony. Zapis gracza pozostanie. Cofniętego dostępu nie można odnowić."),
    "placement-policy": L.m("Ustawienia całego serwera. Zapis działa od następnej północy UTC. Dotychczasowe dni i spotkania zachowują swoje miejsca."),
    "distance-policy": L.m("Tryb dotyczy nowych sesji klientów GPS. Uruchom LAB ponownie. Profile z aktywną ochroną pozostają chronione także po wybraniu obserwacji."),
    "spawn-balance": L.m("Zmiany dotyczą nowych generacji zwykłych potworów na całym serwerze. Dotychczasowe spotkania wygasają naturalnie w ciągu 30 minut. Restart nie jest potrzebny."),
    news: L.m("Gracze otrzymają listę przy kolejnym otwarciu „Co nowego”."),
    image: L.m(
      "Okładka jest dostępna. Przypisz ją do komunikatu i opublikuj wiadomości.",
    ),
    world: L.m(
      "Kolejne żądania mapy użyją nowego limitu po odczycie konfiguracji (do sekundy). Pobraną komórkę musi odświeżyć klient.",
    ),
    weather: L.m(
      "Polityka dotyczy kolejnych odczytów na całym serwerze. Zachowane generacje spotkań pozostają bez zmian.",
    ),
    "daily-rotation": L.m(
      "Nowe losowania użyją zapisanych wag i poziomów. Przydzielone zadania pozostają.",
    ),
    "hunt-policy": L.m(
      "Zasada działa przy kolejnym sprawdzeniu serii stempli.",
    ),
    "task-catalogue": L.m(
      "Wersja czeka na zastosowanie w oknie serwisowym. Wymaga restartu serwera i LAB.",
    ),
    "profile-label": L.m("Etykieta zmienia opis w panelu; nazwa w grze i postęp pozostają."),
    tuning: L.m("The settings are saved and apply as each one says; no restart is needed."),
    "profile-restore": L.m("Przywrócono zapis. Uruchom LAB ponownie."),
    "profile-reset": L.m("Postęp zresetowano. Uruchom LAB ponownie."),
    "profile-copy": L.m(
      "Zapisano kopię postępu; źródło i przypisania urządzeń pozostają. Uruchom LAB ponownie.",
    ),
    "profile-clock": L.m(
      "Przesunięto zegar fabuły. Doba stempli pozostaje bez zmian. Uruchom LAB ponownie.",
    ),
  };
  const knownErrors = {
    "Use a short PNG or JPEG filename.": L.m("Zmień nazwę pliku przed wysłaniem: 1–64 litery A–Z, cyfry, _ lub -, potem .png, .jpg lub .jpeg. Przykład: aktualizacja.png. Bez spacji i polskich liter."),
    "Upload a PNG or JPEG image, at most 4096 × 4096 pixels and 2 MiB.": L.m("PNG lub JPEG, do 2 MiB i 4096 × 4096 px. Nowa nazwa nie zastępuje istniejącej okładki."),
    "The game backend is unavailable. Engine controls remain available.": L.m("Silnik gry jest niedostępny. Otwórz sekcję Silnik, aby sprawdzić stan i go uruchomić."),
    "Local placement service is unavailable. Retry after checking its status.": L.m("Podkład jest niedostępny. Pozycje z ostatniej odpowiedzi pozostają widoczne."),
    "Placement policy is unavailable. The last valid configuration remains in use.": L.m("Ustawienia rozmieszczenia są niedostępne. Ostatnia poprawna wersja pozostaje aktywna."),
    "No retained map area. Open the LAB map and refresh this view first.": L.m("Wybierz i pobierz obszar."),
    "Check placement limits and preferred points. Every preferred point must be on mapped walkable ground, inside coverage, outside exclusions and clear of roads, buildings and water.": L.m("Punkty preferowane muszą leżeć na dostępnej ścieżce lub w parku albo lesie. Odstępy od dróg, budynków i wody pozostają obowiązkowe. Miejsce nie gwarantuje potwora."),
    "This resource changed since it was opened. Refresh and review your changes before retrying.":
      L.m(
        "Zapis na serwerze zmienił się. Twoja wersja robocza pozostała w edytorze. Porównaj ją z aktualnym zapisem.",
      ),
    "The proposed data does not match the game schema. No change was accepted.":
      L.m(
        "Dane nie pasują do schematu gry. Żadna zmiana nie została zaakceptowana. Popraw pola; wersja robocza pozostała.",
      ),
    "Type the exact target profile ID to confirm the operation.": L.m(
      "Wpisz dokładny identyfikator profilu docelowego.",
    ),
    "Close LAB on both affected devices before changing progress.": L.m(
      "Zamknij LAB na obu objętych zmianą urządzeniach.",
    ),
    "Profile changed; refresh before retrying.": L.m(
      "Profil zmienił się. Zamknij okno i odczytaj go ponownie przed zmianą.",
    ),
    "Operator access is required.": L.m(
      "Brak dostępu operatora. Otwórz panel przez chronioną bramę.",
    ),
  };
  let view = "overview",
    loading = false,
    saving = false,
    loadEpoch = 0,
    profileDetailsRequest = 0,
    profiles = [],
    news = null,
    newsIndex = 0,
    newsLanguage = "pl",
    newsSavedIds = [],
    taskData = null,
    worldData = null,
    balanceData = null,
    balanceDraft = null,
    speciesPage = 0,
    weatherData = null,
    tuningData = null,
    catalogueData = null,
    mapData = null,
    mapContext = null, placementData = null, placementDraft = null, placementPreview = null,
    gpsData = null,
    gpsPolicy = null,
    gpsRequest = 0,
    gpsTimer = null,
    gpsController = null,
    gpsBusy = false,
    gpsPage = 0,
    receipts = [],
    profileAction = null,
    activeTaskTab = "daily",
    selectedPoint = null,
    mapPage = 0,
    cataloguePage = 0,
    mapZoom = 1,
    mapMetresPerUnit = 0,
    mapCamera = null,
    mapClusters = new Map(),
    mapRequest = 0,
    mapDrag = null,
    mapSuppressClick = false,
    activeWorldTab = "map",
    helpReturnView = "overview",
    labelRequest = 0,
    labelData = null,
    labelProfile = null,
    serverMetrics = null,
    serverMetricsError = null,
    serverMetricsController = null,
    serverMetricsTimer = null,
    serverMetricsQueued = false;
  const dirtyForms = new Set();
  const numbers = {
    format: (value) => L.number(value),
  };
  function el(tag, text, className) {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) {
      // Labels may acquire input children. Translate only the authored text node.
      const content = document.createTextNode("");
      L.text(content, text);
      n.append(content);
    }
    if (className) n.className = className;
    return n;
  }
  function button(text, fn, style = "secondary") {
    const b = el("button", text, style);
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  }
  function date(value) {
    return L.date(value);
  }
  function pretty(value) {
    if (L.isMessage(value)) return value;
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? L.m("Tak") : L.m("Nie");
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
  }
  function markDirty(id) {
    dirtyForms.add(id);
    syncDraft();
  }
  function viewDrafts(name = view) {
    return [...dirtyForms].filter((id) => $(id)?.closest("section.view")?.id === "view-" + name);
  }
  function syncDraft() {
    $("draft-state").hidden = !dirtyForms.size;
  }
  function notice(message, error = false, pending = false) {
    const n = $("notice");
    n.hidden = false;
    n.className = "notice" + (error ? " error" : pending ? " pending" : "");
    n.replaceChildren(el("span", message));
  }
  function fresh(at = null) {
    L.text(
      $("freshness"),
      L.join(
        L.join(L.m("Odczyt: "), date(at || Date.now())),
        view === "engine" ? L.m(" · odświeżanie co 10 sekund w tym widoku") : L.m(" · odświeżanie na żądanie"),
      ),
    );
    L.text($("connection-state"), L.m("Panel połączony"));
    $("connection-state").className = "connection connected";
    if (view === "overview" && (serverMetrics || serverMetricsError)) renderServerMetrics();
  }
  function failed() {
    L.text(
      $("freshness"),
      L.m("Odczyt nieudany · wcześniej pokazane dane mogą być nieaktualne."),
    );
    L.text($("connection-state"), L.m("Brak świeżego odczytu"));
    $("connection-state").className = "connection failed";
    $("server-mark").className = "status-mark";
  }
  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch("api/" + path, {
        ...options,
        signal: options.signal || AbortSignal.timeout(15000),
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "MonsterSlayerAdmin",
          ...options.headers,
        },
      });
    } catch (e) {
      const uncertain = options.method && options.method !== "GET";
      throw Object.assign(
        new L.Error(
          e.name === "TimeoutError"
            ? L.join(
                L.m("Serwer nie odpowiedział w ciągu 15 sekund. "),
                uncertain
                  ? L.m(
                      "Sprawdź historię przed ponowieniem: zapis mógł zostać wykonany.",
                    )
                  : L.m("Spróbuj odświeżyć za chwilę."),
              )
            : L.join(
                L.m("Nie można połączyć się z panelem. "),
                uncertain
                  ? L.m(
                      "Sprawdź historię i stan zasobu przed ponowieniem zapisu.",
                    )
                  : L.m("Sprawdź połączenie i chronioną bramę."),
              ),
        ),
        {
          uncertain,
        },
      );
    }
    let body;
    try {
      body = await response.json();
    } catch {
      throw Object.assign(
        new L.Error(
          L.join(
            L.m("Niepoprawna odpowiedź panelu. "),
            options.method && options.method !== "GET"
              ? L.m("Sprawdź historię i stan zasobu przed ponowieniem zapisu.")
              : L.m("Sprawdź dostęp przez chronioną bramę."),
          ),
        ),
        {
          uncertain: !!options.method && options.method !== "GET",
        },
      );
    }
    if (!response.ok)
      throw Object.assign(
        new L.Error(
          knownErrors[typeof body.error === "string" ? body.error : body.error?.message] ||
            (typeof body.error === "string" ? body.error : body.error?.message) ||
            L.m("Serwer odrzucił żądanie."),
        ),
        {
          status: response.status,
          uncertain: response.status >= 500 && !!options.method && options.method !== "GET",
          fields: body.fields,
          code: typeof body.error === "string" ? body.error : body.error?.code,
        },
      );
    return body;
  }
  function reportError(e, path) {
    if (e.code === "news_validation") {
      showNewsErrors(e.fields || []);
      return;
    }
    notice(L.errorMessage(e), true);
    if (e.status === 409 && path && !path.startsWith("profiles/"))
      $("notice").append(
        button(L.m("Porównaj aktualny zapis"), () => showConflict(path)),
      );
    if (e.uncertain)
      $("notice").append(
        button(L.m("Otwórz historię operacji"), () => {
          if (
            window.confirm(
              L.m(
                "Przejść do historii? Wersja robocza tego widoku nie zostanie zapisana.",
              ),
            )
          )
            navigate("audit", true);
        }),
      );
  }
  async function showConflict(path) {
    try {
      const current = await api(path);
      L.text($("conflict-content"), JSON.stringify(current, null, 2));
      $("conflict-actions").replaceChildren();
      if (path === "world/balance" && balanceDraft) {
        $("conflict-actions").append(
          el("p", L.m("Po porównaniu możesz zachować swoją wersję roboczą i oprzeć następny zapis na odczytanej rewizji."), "hint"),
          button(L.m("Zachowaj moją wersję na nowej rewizji"), () => {
            balanceData = current;
            renderBalanceState();
            renderSpecies();
            $("conflict-dialog").close();
            $("balance-save").focus();
          }),
        );
      }
      $("conflict-dialog").showModal();
      $("conflict-close").focus();
    } catch (e) {
      notice(L.errorMessage(e), true);
    }
  }
  async function busy(form, action, path = null) {
    if (saving) return;
    saving = true;
    L.busy(true);
    const controls = [
      ...document.querySelectorAll("button,input,select,textarea"),
    ]
      .filter((n) => n.id !== "ui-language")
      .map((n) => [n, n.disabled]);
    controls.forEach(([n]) => (n.disabled = true));
    form.setAttribute("aria-busy", "true");
    try {
      await action();
    } catch (e) {
      reportError(e, path);
    } finally {
      controls.forEach(([n, d]) => {
        if (n.isConnected) n.disabled = d;
      });
      form.removeAttribute("aria-busy");
      saving = false;
      L.busy(false);
      syncDraft();
    }
  }
  async function finish(result, formId, path, readback) {
    const r = result.receipt;
    dirtyForms.delete(formId);
    syncDraft();
    let verified = false;
    if (path) {
      try {
        const current = readback === undefined ? await api(path) : readback;
        const revision =
          r.action === "daily-rotation"
            ? current.daily?.revision
            : r.action === "hunt-policy"
              ? current.hunt?.revision
              : (current.revision ?? current.saved?.revision);
        verified = !result.revision || revision === result.revision;
      } catch {}
    }
    notice(
      L.join(
        labels[r.outcome] || r.outcome,
        " · ",
        actionLabels[r.action] || r.action,
        ". ",
        effects[r.action] || r.effect || "",
        L.m(" Potwierdzenie: "),
        r.id,
        ". ",
        path
          ? verified
            ? L.m("Potwierdzono ponownym odczytem.")
            : L.m("Odczyt po zapisie nie potwierdził stanu — sprawdź historię.")
          : "",
      ),
      false,
      r.outcome === "staged" || (!!path && !verified),
    );
    return verified;
  }
  async function load() {
    const currentView = view,
      epoch = ++loadEpoch;
    if (currentView === "help") {
      $("refresh").hidden = true;
      L.text($("freshness"), L.m("Instrukcje panelu · bez odczytu stanu serwera"));
      return;
    }
    $("refresh").hidden = false;
    loading = true;
    if (currentView === "overview") void refreshServerMetrics();
    $("refresh").disabled = true;
    $("view-" + view).setAttribute("aria-busy", "true");
    L.text($("freshness"), L.m("Pobieranie aktualnych danych…"));
    try {
      const success = await loaders[currentView]();
      if (epoch !== loadEpoch) return;
      if (success === false) { failed(); return; }
      fresh();
    } catch (e) {
      if (epoch !== loadEpoch) return;
      reportError(e);
      failed();
      if (currentView === "overview") {
        L.text($("server-status"), L.m("Stan serwera niepotwierdzony"));
        L.text(
          $("server-detail"),
          L.m("Sprawdź dostęp do bramy i odśwież dane."),
        );
      }
    } finally {
      if (epoch === loadEpoch) {
        loading = false;
        $("refresh").disabled = false;
        $("view-" + currentView).removeAttribute("aria-busy");
        if (currentView === "news") $("news-language").value = newsLanguage;
      }
    }
  }
  async function navigate(next, force = false, fromHistory = false) {
    if (!views[next] || saving) return false;
    if (next !== view) { labelRequest++; profileDetailsRequest++; }
    if (next === "help" && view !== "help") helpReturnView = view;
    const changed = next !== view;
    view = next;
    if (next !== "engine") engine.stop();
    if (next !== "overview") stopServerMetrics();
    if (next !== "world") stopGps();
    if (!fromHistory) {
      if (changed) history.pushState(null, "", "#" + next);
      else history.replaceState(null, "", "#" + next);
    }
    for (const section of document.querySelectorAll("section.view"))
      section.hidden = section.id !== "view-" + next;
    for (const a of document.querySelectorAll("[data-view]")) {
      if (a.dataset.view === next) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    L.text($("page-title"), views[next][0]);
    L.text($("page-kicker"), views[next][1]);
    L.text($("page-description"), views[next][2]);
    L.title(L.join(views[next][0], L.m(" · Monster Slayer")));
    $("notice").hidden = true;
    $("refresh").hidden = next === "help";
    if (viewDrafts(next).length) {
      L.text($("freshness"), L.m("Zachowana wersja robocza · odśwież, aby odczytać serwer"));
      $("refresh").disabled = false;
    } else await load();
    if (next === "world" && mapData) drawMap();
    if (gpsVisible() && $("gps-profile").value) void loadGps();
    return true;
  }
  function facts(rows) {
    const dl = el("dl", null, "facts");
    for (const [k, v] of rows) {
      const row = el("div");
      row.append(el("dt", k), el("dd", pretty(v)));
      dl.append(row);
    }
    return dl;
  }
  function table(headers) {
    const t = el("table"),
      thead = el("thead"),
      tr = el("tr"),
      body = el("tbody");
    headers.forEach((x) => tr.append(el("th", x)));
    thead.append(tr);
    t.append(thead, body);
    return {
      table: t,
      body,
    };
  }
  function empty(target, text) {
    target.replaceChildren(el("p", text, "empty-state"));
  }
  function receiptItem(r, compact = false) {
    const article = el("article");
    article.append(
      el(
        "span",
        labels[r.outcome] || r.outcome,
        "receipt-state" +
          (["refused", "failed"].includes(r.outcome)
            ? " error"
            : r.outcome !== "applied"
              ? " pending"
              : ""),
      ),
    );
    const content = el("div", null, "receipt-body");
    content.append(
      el("h3", actionLabels[r.action] || r.action),
      el("p", L.join(r.target || "", compact ? "" : L.join(" · ", date(r.at)))),
    );
    article.append(content);
    if (compact) {
      const t = el("time", date(r.at));
      t.dateTime = r.at;
      article.append(t);
    } else {
      content.append(
        el("p", r.action.startsWith("transport-") && r.outcome !== "applied" ? "" : effects[r.action] || r.effect || ""),
        el("code", r.id),
      );
      if (r.action.startsWith("transport-")) content.append(testers.receiptDetails(r));
      if (r.outcome === "applied" && r.action.startsWith("profile-") && r.action !== "profile-label")
        content.append(
          button(L.m("Przywróć zapis sprzed operacji"), async () => {
            try {
              profiles = await api("profiles");
              const p = profiles.find((x) => x.id === r.target);
              if (!p) throw new L.Error(L.m("Profil nie istnieje."));
              if (p.activeSessions)
                throw new L.Error(
                  L.m("Zamknij LAB przed przywróceniem zapisu."),
                );
              openProfile(p, "restore", r.id);
            } catch (e) {
              reportError(e);
            }
          }),
        );
      if (
        r.outcome === "applied" &&
        (r.before !== "missing" || ["spawn-balance", "profile-label", "distance-policy", "placement-policy"].includes(r.action)) &&
        ["news", "world", "spawn-balance", "weather", "daily-rotation", "hunt-policy", "profile-label", "distance-policy", "placement-policy"].includes(
          r.action,
        )
      )
        content.append(
          button(L.m("Przejrzyj kopię sprzed zmiany"), () =>
            reviewDocumentBackup(r),
          ),
        );
    }
    return article;
  }
  async function reviewDocumentBackup(r) {
    try {
      const backup = await api(
          "receipts/" + encodeURIComponent(r.id) + "/backup",
        ),
        path =
          r.action === "placement-policy" ? "placement-policy" : r.action === "distance-policy"
            ? "distance-policy"
            : r.action === "profile-label"
            ? "profiles/" + encodeURIComponent(r.target) + "/label"
            : r.action === "news"
            ? "news/" + encodeURIComponent(r.target)
            : r.action === "spawn-balance"
              ? "world/balance"
              : r.action === "world"
              ? "world"
              : r.action === "weather"
                ? "weather"
                : "tasks",
        current = await api(path),
        selected =
          path === "tasks"
            ? r.action === "daily-rotation"
              ? current.daily
              : current.hunt
            : current.saved || current,
        writePath =
          r.action === "daily-rotation"
            ? "tasks/daily"
            : r.action === "hunt-policy"
              ? "tasks/hunt"
              : path;
      const target = $("detail-content");
      L.text(
        $("detail-title"),
        L.join(L.m("Kopia: "), actionLabels[r.action] || r.action),
      );
      target.replaceChildren(
        el(
          "p",
          L.join(
            L.join(L.join(L.m("Cel: "), r.target), L.m(" · LAB · operacja ")),
            r.id,
          ),
          "target",
        ),
        el(
          "p",
          L.join(
            ["spawn-balance", "placement-policy"].includes(r.action)
              ? L.m("Przywrócenie zapisze wcześniejsze ustawienia dla przyszłych generacji. Historia generacji i istniejące spotkania pozostaną zachowane. ")
              : L.m("Przywrócenie zastąpi bieżący dokument kopią sprzed tej operacji. Powstanie nowa kopia i osobne potwierdzenie. "),
            effects[r.action] || "",
          ),
          "hint",
        ),
      );
      for (const [title, doc] of [
        [L.m("Obecnie na serwerze"), selected.document],
        [L.m("Kopia do przywrócenia"), backup.previous.document],
      ]) {
        const details = el("details");
        details.append(
          el("summary", title),
          el("pre", JSON.stringify(doc, null, 2), "code"),
        );
        target.append(details);
      }
      const form = el("form");
      form.id = "document-restore-form";
      const check = el("label", L.m("Przejrzałem kopię i cel zmiany"), "check"),
        input = el("input");
      input.type = "checkbox";
      input.required = true;
      check.prepend(input);
      const send = el("button", L.m("Przywróć ten dokument"));
      send.type = "submit";
      const errorBox = el("div", null, "notice error restore-error");
      errorBox.id = "restore-error";
      errorBox.hidden = true;
      errorBox.tabIndex = -1;
      errorBox.setAttribute("role", "alert");
      form.append(check, errorBox, send);
      function restoreError(error) {
        errorBox.hidden = false;
        errorBox.replaceChildren(el("p", L.errorMessage(error)));
        if (error.status === 409) {
          errorBox.append(
            el(
              "p",
              L.m(
                "Kopia i potwierdzenie pozostają w oknie. Porównaj aktualny zapis. Aby ponownie przygotować zmianę na świeżej rewizji, zamknij okno i otwórz kopię jeszcze raz.",
              ),
            ),
          );
          const compare = button(L.m("Porównaj aktualny zapis"), async () => {
            compare.disabled = true;
            try {
              const fresh = await api(path);
              const document =
                path === "tasks"
                  ? r.action === "daily-rotation"
                    ? fresh.daily
                    : fresh.hunt
                  : fresh.saved || fresh;
              let comparison = $("restore-current-comparison");
              if (!comparison) {
                comparison = el("details");
                comparison.id = "restore-current-comparison";
                form.append(comparison);
              }
              comparison.replaceChildren(
                el(
                  "summary",
                  L.join(L.m("Aktualny zapis serwera · "), date(Date.now())),
                ),
                el("pre", JSON.stringify(document, null, 2), "code"),
              );
              comparison.open = true;
              comparison.querySelector("summary").focus();
            } catch (readError) {
              errorBox.append(
                el(
                  "p",
                  L.join(
                    L.m("Odczyt porównania nie powiódł się. "),
                    L.errorMessage(readError),
                  ),
                ),
              );
            } finally {
              compare.disabled = false;
            }
          });
          errorBox.append(compare);
        }
        errorBox.focus();
      }
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        busy(
          form,
          async () => {
            errorBox.hidden = true;
            try {
              const result = await api(writePath, {
                method: "PUT",
                body: JSON.stringify({
                  revision: selected.revision,
                  document: backup.previous.document,
                }),
              });
              $("detail-dialog").close();
              await finish(result, form.id, path);
              receipts = await api("receipts");
              renderReceipts();
            } catch (error) {
              if (!$("detail-dialog").open) throw error;
              restoreError(error);
            }
          },
          path,
        );
      });
      target.append(form);
      $("detail-dialog").showModal();
      $("detail-close").focus();
    } catch (e) {
      reportError(e);
    }
  }
  function metricsVisible() {
    return view === "overview" && !document.hidden;
  }
  function stopServerMetrics() {
    clearTimeout(serverMetricsTimer);
    serverMetricsTimer = null;
    serverMetricsQueued = false;
    serverMetricsController?.abort();
  }
  function metricNumber(value, decimals = 1) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0
      ? L.number(Math.round(value * 10 ** decimals) / 10 ** decimals) : L.m("Brak pomiaru");
  }
  function metricBytes(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return L.m("Brak pomiaru");
    const unit = value >= 1024 ** 3 ? "GiB" : "MiB";
    return L.join(metricNumber(value / (unit === "GiB" ? 1024 ** 3 : 1024 ** 2)), " ", unit);
  }
  function metricUptime(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return L.m("Brak pomiaru");
    const seconds = Math.floor(value), days = Math.floor(seconds / 86400), hours = Math.floor(seconds / 3600) % 24, minutes = Math.floor(seconds / 60) % 60;
    if (days) return L.join(L.number(days), L.m(" d"), " ", L.number(hours), L.m(" godz."));
    if (hours) return L.join(L.number(hours), L.m(" godz."), " ", L.number(minutes), L.m(" min"));
    return L.join(L.number(minutes), L.m(" min"), " ", L.number(seconds % 60), L.m(" s"));
  }
  function metricAvailability(source) {
    if (source?.status === "warming-up") return L.m("Trwa pomiar…");
    if (source?.status === "partial") return L.m("Część pomiarów niedostępna");
    return source?.available ? L.m("Pomiar dostępny") : L.m("Brak pomiaru");
  }
  function metricCpu(source) {
    return source?.available && typeof source.percent === "number" && Number.isFinite(source.percent) && source.percent >= 0
      ? L.join(metricNumber(source.percent), "%") : metricAvailability(source);
  }
  function renderServerMetrics() {
    const section = document.querySelector(".server-metrics"), stamp = serverMetrics ? new Date(serverMetrics.sampledAt).getTime() : NaN,
      stale = Number.isFinite(stamp) && Date.now() - stamp > 15000,
      partial = serverMetrics && (serverMetrics.process?.status !== "available" || serverMetrics.host?.status !== "available"),
      status = serverMetricsError
        ? L.m("Odczyt metryk nie powiódł się. Pokazane wartości mogą być nieaktualne.")
        : stale ? L.m("Dane nieaktualne — oczekiwanie na nowy pomiar.")
        : !serverMetrics ? L.m("Pobieranie danych…")
        : partial ? L.m("Część pomiarów niedostępna") : L.m("Metryki aktualne");
    section.classList.toggle("metrics-stale", stale || !!serverMetricsError);
    section.classList.toggle("metrics-failed", !!serverMetricsError);
    if (String(status) !== $("server-metrics-state").textContent) L.text($("server-metrics-state"), status);
    L.text($("server-metrics-time"), Number.isFinite(stamp)
      ? L.join(L.m("Pomiar: "), L.date(stamp, { dateStyle: "medium", timeStyle: "medium" })) : L.m("Brak pomiaru"));
    if (metricsVisible() && (serverMetrics || serverMetricsError)) {
      const responding = !serverMetricsError && !stale;
      L.text($("connection-state"), responding ? L.m("Panel połączony") : L.m("Brak świeżego odczytu"));
      $("connection-state").className = responding ? "connection connected" : "connection failed";
      $("server-mark").className = responding ? "status-mark ready" : "status-mark";
      L.text($("server-status"), responding ? L.m("Panel odpowiada") : L.m("Stan serwera niepotwierdzony"));
      L.text($("server-detail"), responding
        ? L.m("API panelu odpowiada. Rozgrywka i usługi zewnętrzne nie zostały sprawdzone.")
        : status);
    }
    if (!serverMetrics) return;
    const process = serverMetrics.process, host = serverMetrics.host;
    L.text($("server-process-state"), metricAvailability(process));
    L.text($("server-host-state"), metricAvailability(host));
    L.text($("server-process-cpu"), metricCpu(process?.cpu));
    L.text($("server-process-memory"), metricBytes(process?.residentMemoryBytes));
    L.text($("server-process-uptime"), metricUptime(process?.uptimeSeconds));
    L.text($("server-host-cpu"), metricCpu(host?.cpu));
    for (const [name, cpu] of [["process", process?.cpu], ["host", host?.cpu]]) {
      const window = $("server-" + name + "-cpu-window");
      window.hidden = !(cpu?.available && typeof cpu.windowSeconds === "number" && Number.isFinite(cpu.windowSeconds) && cpu.windowSeconds > 0);
      if (!window.hidden) L.text(window, L.join(L.m("Średnia z "), metricNumber(cpu.windowSeconds), L.m(" s")));
    }
    L.text($("server-host-memory"), host?.memory?.available
      ? L.join(metricBytes(host.memory.usedBytes), " / ", metricBytes(host.memory.totalBytes)) : L.m("Brak pomiaru"));
    const memoryPercent = host?.memory?.usedPercent, meter = $("server-host-memory-meter");
    meter.hidden = !(host?.memory?.available && typeof memoryPercent === "number" && Number.isFinite(memoryPercent) && memoryPercent >= 0 && memoryPercent <= 100);
    if (!meter.hidden) {
      meter.value = memoryPercent;
      L.attr(meter, "aria-valuetext", L.join(metricNumber(memoryPercent), "%"));
    }
    L.text($("server-host-load"), host?.load?.available
      ? L.join(metricNumber(host.load.one, 2), " / ", metricNumber(host.load.five, 2), " / ", metricNumber(host.load.fifteen, 2)) : L.m("Brak pomiaru"));
    L.text($("server-host-cores"), metricNumber(host?.logicalCpuCount, 0));
    L.text($("server-host-uptime"), metricUptime(host?.uptimeSeconds));
  }
  async function refreshServerMetrics() {
    clearTimeout(serverMetricsTimer);
    serverMetricsTimer = null;
    if (!metricsVisible()) return;
    if (serverMetricsController) {
      serverMetricsQueued = true;
      return;
    }
    const controller = new AbortController();
    serverMetricsController = controller;
    $("server-metrics-refresh").setAttribute("aria-disabled", "true");
    renderServerMetrics();
    try {
      const data = await api("server/status", {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
      });
      if (controller.signal.aborted || !metricsVisible()) return;
      if (!data || !Number.isFinite(Date.parse(data.sampledAt)) || !data.process || !data.host)
        throw new Error("Invalid metrics response");
      serverMetrics = data;
      serverMetricsError = null;
    } catch (error) {
      if (controller.signal.aborted || !metricsVisible()) return;
      serverMetricsError = error;
    } finally {
      if (serverMetricsController === controller) serverMetricsController = null;
      $("server-metrics-refresh").setAttribute("aria-disabled", "false");
      if (metricsVisible()) {
        renderServerMetrics();
        serverMetricsTimer = setTimeout(refreshServerMetrics, serverMetricsQueued ? 0 : 5000);
        serverMetricsQueued = false;
      }
    }
  }
  const balanceNames = ["common", "rare", "legendary"];
  function validWeight(value, max) {
    return String(value).trim() !== "" && Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= max;
  }
  function normalizedBalance(document) {
    return {
      ...Object.fromEntries(balanceNames.map((name) => [name, Number(document[name])])),
      speciesWeights: Object.fromEntries(Object.entries(document.speciesWeights || {})
        .filter(([, value]) => Number(value) !== 1)
        .map(([id, value]) => [id, Number(value)])),
    };
  }
  function balanceValidation() {
    if (!balanceDraft) return null;
    if (balanceNames.some((name) => !validWeight(balanceDraft[name], 10000)) ||
        balanceNames.reduce((sum, name) => sum + Number(balanceDraft[name]), 0) <= 0)
      return L.m("Podaj całkowite wagi 0–10000. Co najmniej jedna kategoria musi mieć dodatnią wagę.");
    if (Object.values(balanceDraft.speciesWeights || {}).some((value) => !validWeight(value, 1000)))
      return L.m("Popraw mnożniki gatunków: liczby całkowite 0–1000. Sprawdź także gatunki ukryte przez filtr.");
    if (!balanceData.species.some((species) => Number(balanceDraft.speciesWeights?.[species.monsterId] ?? 1) > 0))
      return L.m("Pozostaw co najmniej jeden włączony gatunek.");
    return null;
  }
  function balanceDescription(rules) {
    return L.join(
      L.list(balanceNames.map((name, index) => L.join(rarityNames[index + 1], ": ", rules[name])), " · "),
      " · ", L.m("Wyjątki gatunków: "), Object.keys(rules.speciesWeights || {}).length,
    );
  }
  function renderBalanceState() {
    if (!balanceData || !balanceDraft) return;
    const error = balanceValidation(),
      total = balanceNames.reduce((sum, name) => sum + Number(balanceDraft[name]), 0),
      validCategories = total > 0 && balanceNames.every((name) => validWeight(balanceDraft[name], 10000));
    for (const name of balanceNames) {
      L.text($("balance-" + name + "-percent"), validCategories
        ? L.join(L.number(Math.round(Number(balanceDraft[name]) / total * 10000) / 100), "%") : "—");
    }
    $("balance-error").hidden = !error;
    L.text($("balance-error"), error || "");
    const overrides = Object.keys(normalizedBalance(balanceDraft).speciesWeights).length;
    L.text($("balance-draft-state"), L.join(
      dirtyForms.has("balance-form") ? L.m("Niezapisana wersja robocza") : L.m("Zapisane ustawienia"),
      " · ", L.m("Wyjątki gatunków: "), overrides,
    ));
    L.text($("world-rarity-weights"), balanceDescription(balanceData.saved.document));
    L.text($("balance-effective"), balanceDescription(balanceData.effective));
    L.text($("world-balance-from"), balanceData.fromUnixSeconds === 0 ? L.m("Od początku") : date(balanceData.fromUnixSeconds * 1000));
    L.text($("world-balance-until"), balanceData.allNewByUnixSeconds === 0 ? L.m("Od początku") : date(balanceData.allNewByUnixSeconds * 1000));
    L.text($("balance-transition"), balanceData.fromUnixSeconds > Date.now() / 1000
      ? L.join(L.m("Nowe generacje od"), ": ", date(balanceData.fromUnixSeconds * 1000))
      : balanceData.allNewByUnixSeconds > Date.now() / 1000
      ? L.m("Trwa naturalna wymiana spotkań. Starsze generacje mogą nadal używać poprzednich ustawień.")
      : L.m("Okres przejścia zakończony według czasu odczytu. Widok klienta zależy od odświeżenia mapy."));
  }
  function renderBalance() {
    if (!balanceData || !balanceDraft) return;
    for (const name of balanceNames) $("balance-" + name).value = balanceDraft[name];
    renderBalanceState();
    renderSpecies();
  }
  function renderSpecies() {
    if (!balanceData || !balanceDraft) return;
    const query = $("species-search").value.trim().toLowerCase(),
      rarity = $("species-rarity").value,
      species = balanceData.species.filter((row) =>
        (!rarity || String(row.rarity) === rarity) &&
        (row.name + " " + row.slug + " " + row.monsterId).toLowerCase().includes(query));
    const target = $("species-table");
    if (!species.length) {
      empty(target, L.m("Brak gatunków pasujących do filtrów. Wersja robocza pozostała zachowana."));
      return;
    }
    speciesPage = Math.min(speciesPage, Math.max(0, Math.ceil(species.length / 8) - 1));
    const rows = table([L.m("Gatunek"), L.m("Zapisane"), L.m("Mnożnik w edytorze"), L.m("Działania")]);
    for (const speciesRow of species.slice(speciesPage * 8, speciesPage * 8 + 8)) {
      const row = el("tr"), identity = el("td"), saved = el("td"), field = el("td"), actions = el("td"),
        id = String(speciesRow.monsterId), input = el("input"),
        savedValue = balanceData.saved.document.speciesWeights?.[id] ?? 1;
      identity.append(el("strong", speciesRow.name), el("small", L.join("#", id, " · ", rarityNames[speciesRow.rarity] || speciesRow.rarity)));
      L.text(saved, savedValue === 0 ? L.m("Wyłączony") : L.join("×", L.number(savedValue)));
      input.id = "species-weight-" + id;
      input.type = "number";
      input.min = "0";
      input.max = "1000";
      input.step = "1";
      input.required = true;
      input.value = balanceDraft.speciesWeights?.[id] ?? 1;
      input.setAttribute("aria-describedby", "species-help");
      L.attr(input, "aria-label", L.join(speciesRow.name, " · ", L.m("Mnożnik w edytorze")));
      field.append(input);
      const toggle = button("", () => {
        changeSpecies(Number(balanceDraft.speciesWeights?.[id] ?? 1) === 0 ? 1 : 0);
      });
      const reset = button(L.m("Domyślnie ×1"), () => changeSpecies(1), "secondary text-button");
      L.attr(reset, "aria-label", L.join(speciesRow.name, " · ", L.m("Domyślnie ×1")));
      function updateRow() {
        const value = balanceDraft.speciesWeights?.[id] ?? 1, disabled = Number(value) === 0 && String(value).trim() !== "";
        row.classList.toggle("species-disabled", disabled);
        row.classList.toggle("species-changed", String(value) !== String(savedValue));
        L.text(toggle, disabled ? L.m("Włącz") : L.m("Wyłącz"));
        L.attr(toggle, "aria-label", L.join(speciesRow.name, " · ", disabled ? L.m("Włącz") : L.m("Wyłącz")));
        input.setAttribute("aria-invalid", String(!validWeight(value, 1000)));
      }
      function changeSpecies(value) {
        balanceDraft.speciesWeights ||= {};
        if (String(value) === "1") delete balanceDraft.speciesWeights[id];
        else balanceDraft.speciesWeights[id] = value;
        input.value = value;
        markDirty("balance-form");
        updateRow();
        renderBalanceState();
      }
      input.addEventListener("input", () => changeSpecies(input.value));
      updateRow();
      actions.className = "species-actions";
      actions.append(toggle, reset);
      [identity, saved, field, actions].forEach((cell, index) => {
        L.attr(cell, "data-label", [L.m("Gatunek"), L.m("Zapisane"), L.m("Mnożnik w edytorze"), L.m("Działania")][index]);
        row.append(cell);
      });
      rows.body.append(row);
    }
    target.replaceChildren(rows.table, pager(species.length, speciesPage, (next) => {
      speciesPage = next;
      renderSpecies();
    }, 8));
  }
  const testers = window.MSR_TESTERS({ L, api, notice, busy,
    clearDraft: id => { dirtyForms.delete(id); syncDraft(); } });
  const engine = window.MSR_ENGINE({ L, api, el, facts, date, isVisible: () => view === "engine" && !document.hidden,
    onRead: ok => { if (view === "engine") ok ? fresh() : failed(); } });
  const loaders = {
    engine: () => engine.load(),
    testers: () => testers.load(),
    overview: async () => {
      const d = await api("overview");
      L.text($("server-status"), L.m("Panel odpowiada"));
      L.text(
        $("server-detail"),
        L.join(
          L.join(L.m("Odczyt bieżącego procesu · "), d.scope),
          L.m(" · nie jest to test wszystkich usług"),
        ),
      );
      $("server-mark").className = "status-mark ready";
      L.text($("profile-count"), numbers.format(d.profiles));
      L.text($("session-count"), numbers.format(d.activeSessions));
      L.text($("density-value"), d.density);
      L.text(
        $("reset-clock"),
        L.date(d.nextReset, {
          hour: "2-digit",
          minute: "2-digit",
        }),
      );
      L.text(
        $("utc-now"),
        L.join(
          new Date(d.observedAt).toISOString().replace("T", " ").slice(0, 19),
          L.m(" UTC"),
        ),
      );
      L.text($("local-reset"), date(d.nextReset));
      L.text($("local-zone"), Intl.DateTimeFormat().resolvedOptions().timeZone);
      try {
        const rs = await api("receipts");
        $("overview-receipts").replaceChildren(
          ...rs.slice(0, 3).map((r) => receiptItem(r, true)),
        );
        if (!rs.length)
          empty(
            $("overview-receipts"),
            L.m("Nie zapisano jeszcze żadnej operacji w panelu."),
          );
      } catch {
        empty(
          $("overview-receipts"),
          L.m(
            "Historia jest chwilowo niedostępna. Otwórz „Historia operacji”, aby spróbować ponownie.",
          ),
        );
      }
    },
    profiles: async () => {
      profiles = await api("profiles");
      renderProfiles();
    },
    news: async () => {
      const nextLanguage = $("news-language").value, epoch = loadEpoch;
      $("news-form").inert = true; $("news-list").inert = true;
      $("news-add").disabled = true; $("news-save-empty").disabled = true;
      let next;
      try { next = await api("news/" + nextLanguage); }
      finally { if (epoch === loadEpoch) {
        $("news-form").inert = false; $("news-list").inert = false;
        $("news-add").disabled = false; $("news-save-empty").disabled = false;
      } }
      if (epoch !== loadEpoch || view !== "news") return;
      news = next;
      newsLanguage = nextLanguage;
      newsSavedIds = news.document.news_list.map(item => item.id);
      $("news-errors").hidden = true;
      newsIndex = Math.min(
        newsIndex,
        Math.max(0, news.document.news_list.length - 1),
      );
      renderNewsList();
      renderNews();
      try {
        const images = await api("images");
        if (epoch !== loadEpoch || view !== "news") return;
        L.text(
          $("image-list"),
          images.length
            ? L.join(L.m("Dostępne okładki: "), images.join(", "))
            : L.m("Brak dodatkowych okładek. Dostępny jest obraz domyślny."),
        );
        $("cover-options").replaceChildren(
          ...images.map((name) => {
            const o = el("option");
            o.value = name;
            return o;
          }),
        );
      } catch {
        if (epoch !== loadEpoch || view !== "news") return;
        L.text(
          $("image-list"),
          L.m(
            "Nie udało się odczytać biblioteki okładek. Treść komunikatów jest dostępna.",
          ),
        );
      }
    },
    tasks: async () => {
      taskData = await api("tasks");
      renderTasks();
    },
    world: async () => {
      await loadPlacementPolicy();
      const result = await Promise.allSettled([api("world"), api("profiles"), api("world/balance"), api("distance-policy")]);
      if (result[0].status === "fulfilled") {
        worldData = result[0].value;
        $("world-density").value = worldData.saved.document.monsterSlotsPerCell;
        L.text($("world-effective"), worldData.effective.monsterSlotsPerCell);
        L.text($("world-lifetime"), L.join(worldData.lifetimeSeconds / 60, L.m(" min")));
      }
      if (result[2].status === "fulfilled") {
        balanceData = result[2].value;
        balanceDraft = structuredClone(balanceData.saved.document);
        $("balance-fields").disabled = false;
        renderBalance();
      } else {
        $("balance-fields").disabled = true;
      }
      if (result[3].status === "fulfilled" && validGpsPolicy(result[3].value)) {
        gpsPolicy = result[3].value;
        $("gps-policy-fields").disabled = false;
        renderGpsPolicy();
      } else {
        $("gps-policy-fields").disabled = true;
        L.text($("gps-policy-status"), L.m("Nie udało się odczytać polityki dystansu."));
      }
      if (result[1].status === "fulfilled") {
        profiles = result[1].value;
        const oldGps = $("gps-profile").value;
        $("gps-profile").replaceChildren(L.option(L.m("Wybierz profil…"), ""),
          ...profiles.map(p => L.option(L.join(profileDisplayName(p), " · ", p.id), p.id)));
        if (profiles.some(p => p.id === oldGps)) $("gps-profile").value = oldGps;
        else if (oldGps) clearGps();
        const old = $("map-profile").value;
        $("map-profile").replaceChildren(
          L.option(L.m("Wybierz profil…"), ""),
          ...profiles.map((p) =>
            L.option(
              L.join(profileDisplayName(p), " · ", p.id),
              p.id,
            ),
          ),
        );
        if (profiles.some((p) => p.id === old)) $("map-profile").value = old;
        if (old && $("map-profile").value) await loadMap();
      } else {
        $("map-message").hidden = false;
        L.text(
          $("map-message"),
          L.m(
            "Lista profili jest niedostępna. Ustawienia świata zostały odczytane.",
          ),
        );
      }
      if (result[0].status === "rejected") throw result[0].reason;
      if (result[2].status === "rejected") throw result[2].reason;
    },
    weather: async () => {
      weatherData = await api("weather");
      renderWeather();
    },
    tuning: async () => {
      [tuningData, worldData] = await Promise.all([api("tuning"), api("world")]);
      renderTuning();
    },
    catalogue: async () => {
      catalogueData = await api("catalogue");
      renderCatalogueOptions();
      renderCatalogue();
    },
    audit: async () => {
      receipts = await api("receipts");
      renderReceipts();
    },
  };
  function renderProfiles() {
    const q = $("profile-search").value.trim().toLowerCase(),
      matching = profiles.filter((p) =>
        ((p.name || "") + " " + (p.label || "") + " " + p.id).toLowerCase().includes(q),
      );
    $("players").replaceChildren();
    $("profiles-empty").hidden = matching.length > 0;
    L.text(
      $("profiles-empty"),
      profiles.length
        ? L.m("Brak profili pasujących do wyszukiwania.")
        : L.m(
            "Brak zapisanych profili. Pierwszy zapis gry pojawi się tutaj automatycznie.",
          ),
    );
    for (const p of matching) {
      const tr = el("tr"),
        identity = el("td");
      tr.className = "player-row";
      L.attr(identity, "data-label", L.m("Gracz / profil"));
      const name = button(
        profileDisplayName(p),
        () => showProfile(p),
        "plain-button",
      );
      identity.append(name, el("small", p.id), el("small", profileIdentity(p)));
      if (p.label && p.name) identity.append(el("small", p.name));
      const progress = el("td");
      L.attr(progress, "data-label", L.m("Postęp"));
      progress.append(
        el(
          "strong",
          L.join(
            L.m("Poziom "),
            p.level,
            " · ",
            numbers.format(p.gold ?? 0),
            L.m(" orenów"),
          ),
        ),
        el(
          "small",
          L.join(
            p.skillPoints ?? "—",
            L.m(" pkt umiejętności · rewizja "),
            p.revision,
          ),
        ),
      );
      const state = el(
        "td",
        p.activeSessions
          ? L.join(L.m("W grze · "), p.activeSessions)
          : L.m("Offline"),
        p.activeSessions ? "online" : "",
      );
      L.attr(state, "data-label", L.m("Połączenie"));
      const actions = el("td");
      L.attr(actions, "data-label", L.m("Działania"));
      actions.append(button(L.m("Szczegóły"), () => showProfile(p)), button(L.m("Etykieta"), () => openProfileLabel(p)));
      for (const [action, label] of [
        ["clock", L.m("Zegar")],
        ["copy", L.m("Kopiuj")],
        ["reset", L.m("Reset")],
      ]) {
        const b = button(
          label,
          () => openProfile(p, action),
          action === "reset" ? "text-danger" : "secondary",
        );
        b.disabled = p.activeSessions > 0 || p.schema !== 2;
        if (b.disabled)
          L.attr(
            b,
            "title",
            p.activeSessions
              ? L.m("Zamknij LAB przed zmianą zapisu.")
              : L.m("Ten schemat zapisu nie obsługuje edycji."),
          );
        actions.append(b);
      }
      tr.append(identity, progress, state, actions);
      $("players").append(tr);
    }
  }
  function profileDisplayName(p) {
    return p.label || p.name || L.m("Bez nazwy");
  }
  function profileIdentity(p) {
    return L.join({guest:L.m("Gość"),account:L.m("Konto"),unbound:L.m("Bez powiązania")}[p.identityKind] || L.m("Nie podano"),
      " · ", p.deviceCount ?? "—", L.m(" powiązanych urządzeń"));
  }
  async function openProfileLabel(p) {
    const request = ++labelRequest;
    try {
      const data = await api("profiles/" + encodeURIComponent(p.id) + "/label");
      if (request !== labelRequest || view !== "profiles") return;
      labelData = data;
      labelProfile = p;
      $("profile-label").value = labelData.document.label;
      L.text($("label-target"), L.join(profileDisplayName(p), " · ", p.id));
      $("label-result").hidden = true;
      dirtyForms.delete("label-form"); syncDraft();
      $("label-dialog").showModal(); $("profile-label").focus();
    } catch (e) { if (request === labelRequest && view === "profiles") reportError(e); }
  }
  function closeProfileLabel() {
    if (saving) return false;
    if (dirtyForms.has("label-form") && !window.confirm(L.m("Opuścić widok i porzucić niezapisane zmiany?"))) return false;
    labelRequest++;
    dirtyForms.delete("label-form"); syncDraft();
    $("label-dialog").close();
    return true;
  }
  async function showProfile(p) {
    const epoch = ++profileDetailsRequest;
    try {
      const [record, progress] = await Promise.allSettled([api("profiles/" + encodeURIComponent(p.id)), api("profiles/" + encodeURIComponent(p.id) + "/progress")]);
      if (epoch !== profileDetailsRequest) return;
      if (record.status !== "fulfilled") throw record.reason;
      const d = record.value;
      L.text($("detail-title"), profileDisplayName(d.summary));
      const target = $("detail-content");
      target.replaceChildren(
        el(
          "p",
          L.join(
            L.join(
              L.join(L.m("Zapis na serwerze · "), date(d.observedAt)),
              L.m(" · rewizja "),
            ),
            d.summary.revision,
          ),
          "hint",
        ),
      );
      target.append(
        facts([
          [L.m("Profil"), d.summary.id],
          [L.m("Etykieta operatora"), d.summary.label || "—"],
          [L.m("Powiązania"), profileIdentity(d.summary)],
          [L.m("Poziom"), d.summary.level],
          [L.m("Oreny"), d.summary.gold],
          [L.m("Punkty umiejętności"), d.summary.skillPoints],
          [L.m("Etap fabuły"), d.questStage],
          [L.m("Aktywne sesje"), d.summary.activeSessions],
        ]),
      );
      const refreshProgress = button(L.m("Odśwież postęp gracza"), () => showProfile(p), "secondary");
      target.append(refreshProgress);
      if (progress.status === "fulfilled") renderPlayerProgress(progress.value, target);
      else target.append(el("p", L.m("Postęp jest chwilowo niedostępny. Odśwież odczyt; brak danych nie oznacza zerowego postępu."), "error"));
      const section = (title, content) => {
        const a = el("section", null, "profile-detail-section");
        a.append(el("h3", title), content);
        target.append(a);
      };
      const items = table([
        L.m("Rodzaj"),
        L.m("Przedmiot / ID"),
        L.m("Liczba"),
      ]);
      const kindNames = {
        ingredients: L.m("Składniki"),
        potions: L.m("Eliksiry"),
        bombs: L.m("Petardy"),
        oils: L.m("Oleje"),
        swords: L.m("Miecze"),
        armors: L.m("Zbroje"),
        lures: L.m("Przynęty"),
        friend_packs: L.m("Pakiety przyjacielskie"),
      };
      for (const [kind, values] of Object.entries(d.inventory || {}))
        for (const [id, count] of Object.entries(values)) {
          const tr = el("tr");
          tr.append(
            el("td", kindNames[kind] || kind),
            el("td", itemDisplayName(id, kind)),
            el("td", count),
          );
          items.body.append(tr);
        }
      const wrap = el("div", null, "table-wrap");
      wrap.append(items.table);
      if (!items.body.children.length)
        empty(wrap, L.m("Ekwipunek jest pusty."));
      section(L.m("Ekwipunek"), wrap);
      section(
        L.m("Wyposażenie"),
        facts(
          Object.entries(d.equipment || {}).map(([k, v]) => [
            {
              sword: L.m("Wybrany miecz"),
              armor: L.m("Wybrana zbroja"),
              swords: L.m("Miecze"),
              armors: L.m("Zbroje"),
            }[k] || k,
            Array.isArray(v) ? v.join(", ") : v,
          ]),
        ),
      );
      const skills = el(
        "p",
        (d.skills || []).length
          ? d.skills.map((id) => itemDisplayName(id, "skills")).join(" · ")
          : L.m("Brak nauczonych umiejętności."),
      );
      section(L.m("Umiejętności"), skills);
      const bt = table([L.m("Gatunek"), L.m("Pokonane"), L.m("Odebrany próg")]);
      for (const r of d.bestiary || []) {
        const tr = el("tr");
        tr.append(
          el("td", r.name || L.join(L.m("ID "), r.monsterId)),
          el("td", r.kills),
          el("td", r.claimedTier),
        );
        bt.body.append(tr);
      }
      const bw = el("div", null, "table-wrap");
      bw.append(bt.table);
      if (!bt.body.children.length) empty(bw, L.m("Brak zapisanych pokonań."));
      section(L.m("Bestiariusz"), bw);
      const crafting = el("div");
      for (const c of d.crafting || [])
        crafting.append(
          facts([
            [L.m("Rodzaj stanowiska"), c.type],
            [L.m("Pozostałe użycia"), c.usesLeft],
            [L.m("Receptura"), c.workingRecipe],
            [
              L.m("Koniec"),
              c.finishTime ? date(c.finishTime * 1000) : L.m("Nie pracuje"),
            ],
            [L.m("Liczba produktów"), c.outputCount],
          ]),
        );
      if (!(d.crafting || []).length)
        crafting.append(el("p", L.m("Brak aktywnych stanowisk alchemii.")));
      section(L.m("Alchemia"), crafting);
      section(
        L.m("Znajomi i prezenty"),
        facts(
          Object.entries(d.social || {}).map(([k, v]) => [
            {
              status: L.m("Dostępność"),
              registered: L.m("Rejestracja"),
              friends: L.m("Znajomi"),
              invitationsReceived: L.m("Zaproszenia otrzymane"),
              invitationsSent: L.m("Zaproszenia wysłane"),
              unopenedGifts: L.m("Nieotwarte prezenty"),
              sentUnopenedGifts: L.m("Wysłane, nieotwarte"),
              recoveryPending: L.m("Oczekuje na odzyskanie"),
              friendLimit: L.m("Limit znajomych"),
            }[k] || k,
            v,
          ]),
        ),
      );
      section(
        L.m("Zakupy"),
        facts(
          Object.entries(d.purchases || {}).map(([k, v]) => [
            {
              transactions: L.m("Transakcje"),
              accepted: L.m("Zaakceptowane"),
              refused: L.m("Odrzucone"),
            }[k] || k,
            v,
          ]),
        ),
      );
      $("detail-dialog").showModal();
      $("detail-close").focus();
    } catch (e) {
      if (epoch === profileDetailsRequest) reportError(e);
    }
  }
  $("detail-dialog").addEventListener("close", () => { profileDetailsRequest++; });
  function renderPlayerProgress(p, target) {
    const states = {
      claimed: L.m("Odebrano"), unlocked: L.m("Zdobyty"), "ready-to-claim": L.m("Nagroda do odbioru"),
      incomplete: L.m("W toku"), unavailable: L.m("Brak danych"), "not-recorded": L.m("Brak w zapisie"),
      "blocked-tracking": L.m("Śledzenie zadań jeszcze niedostępne"), upcoming: L.m("Jeszcze nieaktywne"),
      expired: L.m("Wygasło"), "tasks-unclaimed": L.m("Najpierw odbierz nagrody zadań"),
      "expired-streak": L.m("Seria wygasła"), "awaiting-gameplay-refresh": L.m("Warunek osiągnięty; czeka na sprawdzenie w grze"),
      started: L.m("Rozpoczęte"), finished: L.m("Zakończone"), active: L.m("Aktywne"),
    };
    const state = value => states[value] || value || "—";
    const amount = value => value == null ? L.m("Brak danych") : numbers.format(value);
    const km = value => value == null ? L.m("Brak danych") : L.join(numbers.format(value / 1000), L.m(" km"));
    const section = (title, open = false) => {
      const box = el("details", null, "progress-section"); box.open = open;
      box.append(el("summary", title)); target.append(box); return box;
    };
    target.append(el("p", L.join(L.m("Postęp z zapisu · "), date(p.observedAt), L.m(" · rewizja "), p.profile.revision), "hint"),
      el("p", L.m("Odczyt nie odświeża rotacji, nie przyznaje bibelotów i nie odbiera nagród. Brak danych nie oznacza zera."), "hint"));
    if (p.clock.requiresGameplayRefresh) target.append(el("p", L.m("Zapis wymaga sprawdzenia upływu czasu w grze. Widoczne liczniki pochodzą z ostatniego zapisu."), "operation-warning"));
    const distance = section(L.m("Dystans naliczony w grze"), true), d = p.distance;
    distance.append(facts([
      [L.m("Łącznie"), km(d.metres)], [L.m("Historyczny stan przed ochroną"), km(d.legacyBaselineMetres)],
      [L.m("Zaakceptowane od ochrony lub ostatniego przywrócenia zapisu"), km(d.acceptedMetresSinceProtection)],
      [L.m("Ochrona tego profilu"), d.protectedProfile ? L.m("Włączona") : L.m("Niewłączona")],
      [L.m("Ostatnie ustalenie stanu początkowego"), d.rebasedAtMs ? date(d.rebasedAtMs) : "—"],
    ]), el("p", L.m("To naliczony dystans gry, a nie potwierdzona piesza trasa. Historia może zawierać stare teleporty. Reset, kopia lub przywrócenie profilu mogą zmienić stan początkowy licznika."), "hint"));
    const story = section(L.m("Fabuła i wprowadzenie"));
    story.append(facts([
      [L.m("Etap wprowadzający"), p.story.introductory.questStage],
      [L.m("Bieżący cel"), p.story.introductory.objective ?? "—"],
      [L.m("Zakończone zadania sezonu"), amount(p.story.recordedFinishedCount)],
    ]));
    const st = table([L.m("Zadanie"), L.m("Stan"), L.m("Śledzone"), L.m("Zapisane rozstrzygnięcia")]);
    for (const row of p.story.rows) { const tr = el("tr"); tr.append(el("td", L.join(row.name || row.code || "ID", " · ", row.id)), el("td", state(row.status)), el("td", row.tracked ? "✓" : "—"), el("td", amount(row.rewardedOutputCount))); st.body.append(tr); }
    const sw = el("div", null, "table-wrap"); sw.append(st.table); story.append(sw,
      el("p", L.m("Wprowadzenie jest osobnym etapem. Nazwy fabuły pochodzą z katalogu angielskiego; liczba rozstrzygnięć nie jest procentem ukończenia."), "hint"));
    const renderTasks = (box, rows, trinkets = false) => {
      if (!rows.length) { box.append(el("p", L.m("Brak wpisów."), "muted")); return; }
      const label = el("label", L.m("Szukaj po nazwie, warunku lub ID")), input = el("input"); input.type = "search"; label.append(input); box.append(label);
      const wrap = el("div", null, "table-wrap"); box.append(wrap);
      const draw = () => {
        const query = input.value.trim().toLocaleLowerCase(), filtered = rows.filter(r => [r.id, r.name, r.definition ? taskCondition(r.definition) : ""].join(" ").toLocaleLowerCase().includes(query));
        const t = table([trinkets ? L.m("Bibelot / warunek") : L.m("Zadanie / warunek"), L.m("Postęp"), L.m("Stan nagrody")]);
        for (const r of filtered) {
          const tr = el("tr"), name = el("td"), progress = el("td"), reward = el("td", state(r.rewardState));
          name.append(el("strong", r.definition ? taskCondition(r.definition) : L.m("Definicja niedostępna")), el("small", L.join(r.name || "ID", " · ", r.id), "muted"));
          for (const [key, label] of [["monsters", L.m("Gatunki: ")], ["items", L.m("Przedmioty: ")], ["quests", L.m("Zadania fabularne: ")], ["outputs", L.m("Rozstrzygnięcia: ")]]) {
            const ids = r.definition?.[key];
            if (ids?.length) name.append(el("small", L.join(label, ids.join(", ")), "muted"));
          }
          if (r.definition?.type === 11 && !r.definition.fights) name.append(el("small", L.m("Bez limitu liczby walk."), "muted"));
          progress.append(el("span", L.join(amount(r.progress), " / ", amount(r.target))));
          if (Number.isFinite(r.progress) && r.target > 0) { const bar = el("progress"); bar.max = r.target; bar.value = Math.max(0, Math.min(r.progress, r.target)); L.attr(bar, "aria-label", L.join(L.m("Postęp"), " · ", r.name || r.id)); progress.append(bar); }
          if (r.requiresGameplayRefresh) reward.append(el("small", L.m("Do sprawdzenia w grze"), "muted"));
          if (r.unlockedAt) reward.append(el("small", date(r.unlockedAt * 1000), "muted"));
          tr.append(name, progress, reward); t.body.append(tr);
        }
        wrap.replaceChildren(t.table); if (!filtered.length) wrap.append(el("p", L.m("Brak wyników.")));
      };
      input.addEventListener("input", draw); draw();
    };
    const daily = section(L.m("Zadania dzienne"));
    daily.append(el("p", L.m("Odebrane zadania dzienne znikają z listy. Zapis nie zawiera pełnej historii ich ukończenia."), "hint")); renderTasks(daily, p.daily.rows);
    const timed = section(L.m("Zadania czasowe"));
    if (!p.timed.rows.length) timed.append(el("p", L.m("Brak wpisów.")));
    for (const event of p.timed.rows) {
      const box = el("details"); box.append(el("summary", L.join(event.name || "ID", " · ", event.id, " · ", state(event.window))));
      box.append(facts([[L.m("Od"), event.start ? date(event.start * 1000) : "—"], [L.m("Do"), event.end ? date(event.end * 1000) : "—"], [L.m("Nagroda końcowa"), state(event.finalRewardState)]]));
      renderTasks(box, event.tasks); timed.append(box);
    }
    const trinkets = section(L.join(L.m("Bibeloty"), " · ", amount(p.trinkets.unlockedCount)));
    trinkets.append(el("p", L.m("Bibeloty są przyznawane automatycznie podczas sprawdzania warunków w grze. Nie mają przycisku odbioru nagrody. Identyfikatory katalogu pokazano pod opisem warunku."), "hint")); renderTasks(trinkets, p.trinkets.rows, true);
    const hunt = section(L.m("Stemple")); hunt.append(facts([
      [L.m("Postęp serii"), L.join(amount(p.hunt.stamps?.length), " / ", amount(p.hunt.target))],
      [L.m("Odebrane serie"), amount(p.hunt.claims)], [L.m("Stan nagrody"), state(p.hunt.rewardState)],
      [L.m("Granica doby"), "00:00 UTC"],
    ]));
  }
  function itemDisplayName(id, kind) {
    const table = (catalogueData?.tables || []).find((t) => t.name === kind),
      row = table?.rows.find((r) => String(r.id) === String(id));
    return row
      ? L.join(
          L.join(row.name || row.slug || L.join(L.m("ID "), id), " · "),
          id,
        )
      : L.join(L.m("ID "), id);
  }
  function readableRecords(value) {
    const block = el("div");
    const rows = Array.isArray(value)
      ? value
      : Object.entries(value).map(([id, v]) =>
          typeof v === "object" && v
            ? {
                id,
                ...v,
              }
            : {
                id,
                value: v,
              },
        );
    if (!rows.length) {
      block.append(el("p", L.m("Brak wpisów."), "muted"));
      return block;
    }
    if (rows.every((x) => typeof x !== "object" || x === null)) {
      block.append(el("p", rows.join(", ")));
      return block;
    }
    const keys = [...new Set(rows.flatMap((r) => Object.keys(r || {})))];
    const t = table(
      keys.map(
        (k) =>
          ({
            id: "ID",
            taskId: L.m("Zadanie"),
            progress: L.m("Postęp"),
            value: L.m("Wartość"),
            claimed: L.m("Odebrano"),
            completed: L.m("Ukończono"),
            target: L.m("Cel"),
            eventId: L.m("Wydarzenie"),
          })[k] || k,
      ),
    );
    for (const r of rows) {
      const tr = el("tr");
      keys.forEach((k) => tr.append(el("td", pretty(r?.[k]))));
      t.body.append(tr);
    }
    const wrap = el("div", null, "table-wrap");
    wrap.append(t.table);
    block.append(wrap);
    return block;
  }
  function captureNews() {
    const item = news?.document.news_list[newsIndex];
    if (!item) return;
    const oldId = item.id;
    item.id = Number($("news-id").value);
    item.group_id = $("news-group").value;
    item.title = $("news-title").value;
    item.short_description = $("news-short").value;
    item.content = $("news-content").value;
    item.date = $("news-date").value.split("-").reverse().join("/");
    item.image_url = $("news-image").value.trim();
    if ($("news-featured").checked) news.document.featured = item.id;
    else if (news.document.featured === oldId) news.document.featured = 0;
  }
  function renderNewsList() {
    L.text(
      $("news-total"),
      L.join(news.document.news_list.length, L.m(" komunikatów")),
    );
    const list = $("news-list");
    list.replaceChildren();
    news.document.news_list.forEach((item, i) => {
      const b = button(
        "",
        () => {
          captureNews();
          newsIndex = i;
          renderNewsList();
          renderNews();
        },
        "",
      );
      b.append(
        el("strong", item.title || L.m("Nowy komunikat")),
        el(
          "small",
          L.join(
            news.document.featured === item.id ? L.m("★ Wyróżniona · ") : "",
            item.date,
          ),
        ),
      );
      b.setAttribute("aria-pressed", String(i === newsIndex));
      list.append(b);
    });
    if (!news.document.news_list.length)
      empty(list, L.m("Nie ma komunikatów. Dodaj pierwszy."));
  }
  function renderNews() {
    const item = news.document.news_list[newsIndex];
    $("news-form").hidden = !item;
    $("news-save-empty").hidden = !!item;
    $("news-preview").hidden = !item;
    if (!item) return;
    $("news-id").value = item.id;
    $("news-group").value = item.group_id;
    $("news-title").value = item.title;
    $("news-short").value = item.short_description;
    $("news-content").value = item.content;
    $("news-date").value = item.date.split("/").reverse().join("-");
    $("news-image").value = item.image_url;
    $("news-featured").checked = news.document.featured === item.id;
    renderNewsPreview();
  }
  const newsErrorMessages = {
    feed_size: L.m("Cała lista wraz z formatowaniem JSON może zajmować najwyżej 1 MiB. Skróć treść lub zmniejsz liczbę wpisów."),
    required_text: L.m("Wpisz tekst; same spacje nie wystarczą."),
    text_required: L.m("Pole musi być tekstem. Krótki opis i okładka mogą być puste."),
    calendar_date: L.m("Wybierz prawidłową datę. Format JSON: DD/MM/RRRR, np. 04/10/2026."),
    image_format: L.m("Użyj nazwy okładki, np. aktualizacja.png, albo pełnego adresu http:// lub https://. Nazwa: 1–64 litery A–Z, cyfry, _ lub -, a potem .png, .jpg lub .jpeg. Puste pole wybiera okładkę domyślną."),
    image_missing: L.m("Nie ma takiej okładki na serwerze. Najpierw prześlij obraz w bibliotece albo pozostaw pole puste."),
    unique_positive_id: L.m("ID musi być dodatnią liczbą całkowitą i nie może powtarzać się na liście."),
    group_format: L.m("Grupa wymaga 1–128 znaków, bez średnika. Przykład: news-1."),
    featured_missing: L.m("Wyróżniony wpis musi istnieć na liście; 0 oznacza brak wyróżnienia."),
    list_limit: L.m("Lista może zawierać od 0 do 100 komunikatów."),
    integer_required: L.m("Wpisz liczbę całkowitą."),
    unexpected_field: L.m("Dokument zawiera nieznane lub powtórzone pole. Sprawdź format w pomocy."),
    object_required: L.m("Wymagany jest obiekt komunikatu. Sprawdź format w pomocy."),
    item_required: L.m("Wymagany jest obiekt komunikatu. Sprawdź format w pomocy."),
    write_schema: L.m("Zapis wymaga rewizji i dokumentu wiadomości. Odśwież panel; zachowaj wcześniej treść roboczą."),
  };
  const newsFieldIds = { id: "news-id", group_id: "news-group", title: "news-title", short_description: "news-short", content: "news-content", date: "news-date", image_url: "news-image", featured: "news-featured" };
  function showNewsErrors(fields) {
    const box = $("news-errors");
    box.replaceChildren(el("strong", L.m("Nie opublikowano wiadomości. Popraw wskazane pola; wersja robocza pozostała.")));
    const list = el("ul");
    for (const issue of fields) {
      const match = /^news_list\[(\d+)\](?:\.(\w+))?$/.exec(issue.field || "");
      const text = L.join(match ? L.join(L.m("Wpis "), Number(match[1]) + 1, " · ") : "", issue.field, ": ", newsErrorMessages[issue.code] || L.m("Sprawdź format w pomocy."));
      const li = el("li");
      if (match && news?.document.news_list[Number(match[1])]) li.append(button(text, () => {
        captureNews(); newsIndex = Number(match[1]); renderNewsList(); renderNews();
        const input = $(newsFieldIds[match[2]] || "news-title");
        const details = input.closest("details"); if (details) details.open = true;
        input.focus();
      }, "secondary"));
      else li.append(el("span", text));
      list.append(li);
    }
    box.append(list); box.hidden = false; box.focus();
    notice(L.m("Nie opublikowano wiadomości. Popraw wskazane pola; wersja robocza pozostała."), true);
  }
  function reviewNews() {
    const ids = new Set(news.document.news_list.map(item => item.id));
    const removed = newsSavedIds.filter(id => !ids.has(id)).length;
    return window.confirm(String(L.join(L.m("Publikacja całej listy"), " · ", newsLanguage.toUpperCase(), "\n", L.m("Liczba wpisów: "), ids.size, "\n", L.m("Usunięte wpisy: "), removed, "\n", L.m("Gracze otrzymają listę przy kolejnym otwarciu „Co nowego”."))));
  }
  function renderNewsPreview() {
    L.text($("preview-title"), $("news-title").value || L.m("Bez tytułu"));
    L.text($("preview-short"), $("news-short").value);
    L.text($("preview-content"), $("news-content").value);
    L.text($("preview-date"), $("news-date").value.split("-").reverse().join("/"));
  }
  const actionNames = {
    1: L.m("atak"),
    2: L.m("perfekcyjne parowanie"),
    4: L.m("znak Aard"),
    5: L.m("znak Igni"),
    6: L.m("znak Quen"),
    7: L.m("silny atak"),
    8: L.m("szybki atak"),
    9: L.m("trafienie krytyczne"),
  };
  const typeNames = {
    1: L.m("Pokonaj potwory"),
    2: L.m("Ukończ nemeton"),
    3: L.m("Przejdź dystans"),
    4: L.m("Użyj petard"),
    6: L.m("Wytwórz przedmioty"),
    7: L.m("Poziom postaci"),
    8: L.m("Nauczone umiejętności"),
    9: L.m("Ukończ zadania fabularne"),
    10: L.m("Użyj przedmiotu przed walką"),
    11: L.m("Wykonaj akcje w walce"),
    12: L.m("Zbierz składniki"),
    13: L.m("Uzyskaj rozstrzygnięcia fabularne"),
  };
  function taskTitle(t) {
    if (t.type === 11)
      return (
        L.list(
          (t.actions || []).map(
            (x) => actionNames[x] || L.join(L.m("akcja "), x),
          ),
          " / ",
        ) || typeNames[t.type]
      );
    if (t.type === 6)
      return L.join(
        L.m("Wytwórz "),
        {
          2: L.m("petardy"),
          3: L.m("eliksiry"),
          4: L.m("oleje"),
        }[t.item_type ?? t.itemType] || L.m("przedmioty"),
      );
    if (t.type === 10)
      return L.join(
        L.m("Użyj "),
        {
          3: L.m("eliksiru"),
          4: L.m("oleju"),
        }[t.item_type ?? t.itemType] || L.m("przedmiotu"),
      );
    return typeNames[t.type] || L.join(L.m("Warunek "), t.type);
  }
  function taskCondition(t) {
    let s = L.join(
      L.join(L.join(taskTitle(t), ": "), numbers.format(t.target)),
      t.type === 3 ? L.m(" m") : "",
    );
    if (t.monsters?.length)
      s = L.join(
        s,
        L.join(" · " + t.monsters.length, L.m(" wskazanych gatunków")),
      );
    if (t.fights)
      s = L.join(s, L.join(L.join(L.m(" · w "), t.fights), L.m(" walkach")));
    if (t.window_seconds ?? t.windowSeconds)
      s = L.join(s, L.join(L.join(L.m(" · w "), t.window_seconds ?? t.windowSeconds), L.m(" s")));
    return s;
  }
  function rewardLabel(t) {
    const a = [];
    if (t.gold) a.push(L.join(numbers.format(t.gold), L.m(" orenów")));
    for (const r of t.rewards || [])
      a.push(
        L.join(
          L.join(
            L.join(
              L.join(L.join(r.amount, L.m(" × przedmiot ")), r.item),
              L.m(" (typ "),
            ),
            r.type,
          ),
          ")",
        ),
      );
    return L.list(a, " · ") || L.m("Brak nagrody");
  }
  function renderTasks() {
    const d = taskData;
    L.text($("daily-count"), d.daily.document.tasks.length);
    L.text($("timed-count"), d.timed.document.events.length);
    L.text($("trinket-count"), d.trinkets.document.trinkets.length);
    renderRotation();
    $("hunt-streak").checked = d.hunt.document.streak;
    $("hunt-summary").replaceChildren(
      facts([
        [L.m("Długość serii"), L.join(d.hunt.document.size, L.m(" stempli"))],
        [
          L.m("Nagroda"),
          L.join(
            L.join(d.hunt.document.reward.amount, L.m(" × przedmiot ")),
            d.hunt.document.reward.item,
          ),
        ],
        [L.m("Identyfikator nagrody"), d.hunt.document.reward_id],
      ]),
    );
    $("events").replaceChildren();
    for (const e of d.timed.document.events) {
      const a = el("article"),
        now = Date.now() / 1000;
      a.append(
        el(
          "p",
          now < e.start
            ? L.m("ZAPLANOWANE")
            : now <= e.end
              ? L.m("W TRAKCIE")
              : L.m("ZAKOŃCZONE"),
          "eyebrow",
        ),
        el("h3", e.name),
        el(
          "div",
          L.join(L.join(date(e.start * 1000), " — "), date(e.end * 1000)),
          "event-meta",
        ),
        el("p", L.join(L.m("Nagroda wydarzenia: "), rewardLabel(e)), "hint"),
      );
      const list = el("ul");
      for (const t of e.tasks)
        list.append(
          el("li", L.join(L.join(taskCondition(t), " · "), rewardLabel(t))),
        );
      a.append(list);
      $("events").append(a);
    }
    if (!d.timed.document.events.length)
      empty(
        $("events"),
        L.m(
          "Brak zaplanowanych wydarzeń. Przygotuj pierwsze w sekcji „Nowe definicje”.",
        ),
      );
    const tr = table([L.m("Osiągnięcie"), L.m("Cel"), L.m("Nagroda")]);
    for (const t of d.trinkets.document.trinkets) {
      const row = el("tr"),
        name = el("td");
      name.append(
        el("strong", taskTitle(t)),
        el("small", L.join(L.join(t.slug, L.m(" · ID ")), t.id)),
      );
      row.append(name, el("td", taskCondition(t)), el("td", rewardLabel(t)));
      tr.body.append(row);
    }
    $("trinket-list").replaceChildren(tr.table);
    $("task-catalogue").value = JSON.stringify(d.catalogue.document, null, 2);
    L.text(
      $("staged-list"),
      d.staged.length
        ? L.join(L.m("Przygotowane wersje: "), d.staged.join(", "))
        : L.m("Brak wersji oczekujących."),
    );
    buildEventComposer();
  }
  function renderRotation() {
    const body = $("rotation-rows");
    body.replaceChildren();
    const q = $("task-search").value.toLowerCase();
    for (const t of taskData.daily.document.tasks) {
      if (
        !L.join(L.join(L.join(t.slug + " ", taskTitle(t)), " "), t.id)
          .toLowerCase()
          .includes(q)
      )
        continue;
      const tr = el("tr"),
        name = el("td");
      name.append(
        el("strong", taskTitle(t)),
        el("small", L.join(L.join(t.slug, L.m(" · ID ")), t.id)),
      );
      tr.append(name, el("td", taskCondition(t)), el("td", rewardLabel(t)));
      for (const [key, min, max] of [
        ["weight", 0, 10000],
        ["min_level", 1, 40],
      ]) {
        const td = el("td"),
          i = el("input");
        i.type = "number";
        i.min = min;
        i.max = max;
        i.value = t[key] ?? 1;
        i.required = true;
        L.attr(
          i,
          "aria-label",
          L.join(
            L.join(
              key === "weight" ? L.m("Waga") : L.m("Minimalny poziom"),
              " ",
            ),
            t.slug,
          ),
        );
        i.addEventListener("input", () => {
          t[key] = Number(i.value);
          markDirty("rotation-form");
        });
        td.append(i);
        tr.append(td);
      }
      body.append(tr);
    }
  }
  function buildEventComposer() {
    let form = $("event-composer");
    if (form) return;
    form = el("form");
    form.id = "event-composer";
    form.className = "section-block";
    form.append(el("h3", L.m("Nowe wydarzenie — formularz")));
    const fields = [
      ["event-name", L.m("Nazwa wydarzenia"), "text"],
      ["event-start", L.m("Początek (Twój czas lokalny)"), "datetime-local"],
      ["event-end", L.m("Koniec (Twój czas lokalny)"), "datetime-local"],
      ["event-target", L.m("Wymagana liczba / dystans w metrach"), "number"],
      ["event-gold", L.m("Nagroda za wydarzenie (oreny)"), "number"],
    ];
    for (const [id, label, type] of fields) {
      const l = el("label", label),
        i = el("input");
      i.id = id;
      i.type = type;
      i.required = true;
      if (type === "number") {
        i.min = id === "event-gold" ? 0 : 1;
        i.max = id === "event-gold" ? 100000 : 2000000;
        i.value = id === "event-gold" ? 100 : 10;
      }
      if (type === "text") i.maxLength = 96;
      l.append(i);
      form.append(l);
    }
    const label = el("label", L.m("Cel zadania — użyj sprawdzonego typu")),
      select = el("select");
    select.id = "event-template";
    for (const t of taskData.daily.document.tasks)
      select.append(
        L.option(L.join(L.join(taskTitle(t), " · "), t.slug), t.id),
      );
    label.append(select);
    form.insertBefore(label, form.children[4]);
    form.append(
      el(
        "p",
        L.m(
          "Formularz dodaje wydarzenie z jednym zadaniem bez osobnej nagrody. Zachowuje filtry gatunków, akcji i liczby walk wybranego wzorca. Pełna treść pojawi się w zaawansowanej wersji katalogu do sprawdzenia.",
        ),
        "hint",
      ),
    );
    const submit = el(
      "button",
      L.m("Dodaj do wersji roboczej katalogu"),
      "secondary",
    );
    submit.type = "submit";
    form.append(submit);
    form.addEventListener("input", () => markDirty("event-composer"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      try {
        let draft = JSON.parse($("task-catalogue").value);
        const start = Math.floor(
            new Date($("event-start").value).getTime() / 1000,
          ),
          end = Math.floor(new Date($("event-end").value).getTime() / 1000);
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start)
          throw new L.Error(
            L.m("Koniec wydarzenia musi być późniejszy niż początek."),
          );
        if (draft.timed.events.some((e) => start <= e.end && end >= e.start))
          throw new L.Error(
            L.m(
              "Termin nakłada się na istniejące wydarzenie. Wybierz inny przedział.",
            ),
          );
        const all = [
            ...draft.daily.tasks,
            ...draft.trinkets.trinkets,
            ...draft.timed.events.flatMap((e) => e.tasks),
          ],
          id = Math.max(12000, ...all.map((x) => x.id)) + 1,
          template = taskData.daily.document.tasks.find(
            (t) => t.id === Number($("event-template").value),
          ),
          task = {
            ...structuredClone(template),
            id,
            slug: "event_task_" + id,
            target: Number($("event-target").value),
            gold: 0,
            rewards: [],
          };
        const e = {
          id: Math.max(30000, ...draft.timed.events.map((x) => x.id)) + 1,
          name: $("event-name").value.trim(),
          start,
          end,
          gold: Number($("event-gold").value),
          tasks: [task],
          rewards: [],
        };
        draft.timed.events.push(e);
        $("task-catalogue").value = JSON.stringify(draft, null, 2);
        dirtyForms.delete("event-composer");
        markDirty("stage-form");
        notice(
          L.join(
            L.join(L.m("Dodano wydarzenie „"), e.name),
            L.m(
              "” do wersji roboczej. Sprawdź katalog i wybierz „Sprawdź i przygotuj katalog”. Gra nie została zmieniona.",
            ),
          ),
        );
      } catch (e) {
        reportError(e);
      }
    });
    const advanced = el("details"),
      summary = el("summary", L.m("Zaawansowane: pełna wersja katalogu JSON"));
    advanced.append(summary);
    const stage = $("stage-form");
    stage.before(form, advanced);
    advanced.append(stage);
  }
  const weatherNames = {
    1: L.m("Burza"),
    2: L.m("Mżawka"),
    3: L.m("Deszcz"),
    4: L.m("Śnieg"),
    5: L.m("Mgła"),
    6: L.m("Bezchmurnie"),
    7: L.m("Zachmurzenie"),
  };
  function renderTuning() {
    const d = tuningData, box = $("tuning-fields"), groups = new Map();
    for (const s of d.definitions) groups.set(s.group, [...(groups.get(s.group) || []), s]);
    box.replaceChildren();
    // Monsters per map cell lives in world.json (the World page too) and is saved through that page's endpoint.
    const density = el("input"), densityLabel = el("label", L.m("Monsters per map cell"));
    Object.assign(density, { type: "number", id: "tuning-world-density", min: 6, max: 36, step: 1, required: true,
      value: worldData.saved.document.monsterSlotsPerCell });
    densityLabel.append(density);
    box.append(el("h3", L.m("Monsters")), densityLabel, el("p", L.m("How many monsters stand in a map cell at once (the " +
      "same setting as on the World page). Each needs a free place, and herbs and a nest take some, so keep places per cell " +
      "(below) well above it. Default: 18. Range: 6–36. Takes effect: about a second after saving; monsters already out " +
      "stay for up to 30 minutes."), "hint"));
    for (const [group, settings] of groups) {
      box.append(el("h3", L.m(group)));
      for (const s of settings) {
        const label = el("label", L.m(s.label)), input = el("input");
        input.type = "number";
        input.id = "tuning-" + s.key;
        input.dataset.key = s.key;
        input.min = s.min;
        input.max = s.max;
        input.step = s.step;
        input.required = true;
        input.value = d.values[s.key];
        label.append(input);
        box.append(label, el("p", L.join(L.m(s.help), " ", L.m("Default: "), s.default, " ", L.m(s.unit), L.m(". Range: "), s.min,
          "–", s.max, L.m(". Takes effect: "), L.m(s.applies)), "hint"));
      }
    }
    $("tuning-content").hidden = true;
    $("tuning-form").hidden = false;
  }
  function renderWeather() {
    const d = weatherData,
      e = d.effective,
      s = d.saved.document,
      code = d.codes.find((x) => x.code === e.code);
    const box = el("div", null, "weather-banner"),
      glyph = el("div", "☁", "weather-glyph");
    glyph.setAttribute("aria-hidden", "true");
    const content = el("div");
    content.append(
      el(
        "p",
        e.overrideActive
          ? L.m("WYMUSZENIE GLOBALNE")
          : e.providerConfigured
            ? L.m("TRYB AUTOMATYCZNY")
            : L.m("TRYB ZASTĘPCZY"),
        "eyebrow",
      ),
      el(
        "h2",
        e.overrideActive
          ? weatherNames[e.code] || code?.name || L.join(L.m("Kod "), e.code)
          : e.providerConfigured
            ? L.m("Warunki zależne od lokalizacji")
            : L.m("Dostawca nie jest skonfigurowany"),
      ),
      el(
        "p",
        e.overrideActive
          ? L.join(L.m("Obowiązuje do "), date(e.expiresAt))
          : L.m(
              "Status dotyczy polityki następnego odczytu, nie jednej pogody dla całego świata.",
            ),
      ),
    );
    box.append(glyph, content);
    const stats = el("div", null, "weather-state");
    const last = e.lastAnswered;
    for (const [k, v] of [
      [
        L.m("Źródło polityki"),
        {
          "open-meteo": "Open-Meteo",
          manual: L.m("Wymuszenie operatora"),
          fallback: L.m("Warunki zastępcze"),
        }[e.source] || e.source,
      ],
      [L.m("Komórki w pamięci"), e.cachedCells ?? 0],
      [L.m("Generacje spotkań"), e.generations ?? 0],
      [
        L.m("Ostatnie pobranie od dostawcy"),
        e.lastFetchAt ? date(e.lastFetchAt) : L.m("Brak odczytu"),
      ],
      [
        L.m("Wynik pobrania"),
        {
          success: L.m("Udane"),
          failed: L.m("Nieudane"),
          error: L.m("Błąd"),
        }[e.lastFetchOutcome] ||
          e.lastFetchOutcome ||
          L.m("Nie wykonano"),
      ],
      [
        L.m("Ostatni odczyt serwera"),
        last
          ? L.join(
              L.join(
                L.join(L.join(date(last.at), L.m(" · kod ")), last.code),
                " · ",
              ),
              {
                override: L.m("wymuszenie"),
                observed: L.m("od dostawcy"),
                cached: L.m("pamięć podręczna"),
                "stale-cache": L.m("nieświeża pamięć"),
                fallback: L.m("warunki zastępcze"),
              }[last.valueStatus] || last.valueStatus,
            )
          : L.m("Brak zachowanej obserwacji"),
      ],
    ]) {
      const dl = el("dl");
      dl.append(el("dt", k), el("dd", v));
      stats.append(dl);
    }
    $("weather-content").replaceChildren(box, stats);
    $("weather-mode").value = s.mode;
    $("weather-code").replaceChildren(
      ...d.codes.map((c) =>
        L.option(L.join(weatherNames[c.code] || c.name, " · ", c.code), c.code),
      ),
    );
    $("weather-code").value = s.code ?? d.codes[0]?.code ?? 1;
    const exp = s.expiresAt
      ? new Date(s.expiresAt)
      : new Date(Date.now() + 3600000);
    $("weather-expiry").value = localDateInput(exp);
    setWeatherMode();
    if (s.mode === "manual" && !e.overrideActive)
      $("weather-content").append(
        el(
          "p",
          L.m(
            "Zapisane wymuszenie wygasło. Serwer wrócił do polityki automatycznej. Formularz pokazuje ostatni zapis; wybierz nowy termin albo tryb automatyczny.",
          ),
          "callout",
        ),
      );
  }
  function localDateInput(d) {
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
  }
  function setWeatherMode() {
    $("weather-manual").hidden = $("weather-mode").value !== "manual";
    $("weather-expiry").required = $("weather-mode").value === "manual";
  }
  async function loadMap() {
    const id = $("map-profile").value, request = ++mapRequest;
    if (!id) return;
    $("map-message").hidden = false;
    L.text($("map-message"), L.m("Pobieranie ostatniej odpowiedzi mapy…"));
    try {
      const d = await api("map?profile=" + encodeURIComponent(id));
      if (!d || d.profile !== id || !["empty", "ready", "stale"].includes(d.status)
          || !Array.isArray(d.points) || !Array.isArray(d.cells)
          || (d.status !== "empty" && !Number.isFinite(new Date(d.observedAt).getTime())))
        throw new L.Error(L.m("Niepoprawna odpowiedź panelu. "));
      if (request !== mapRequest || $("map-profile").value !== id) return;
      const previous = selectedPoint;
      mapData = d;
      selectedPoint = d.points?.some(p => p.id === previous) ? previous : null;
      renderMap();
      await loadMapContext(id, request);
    } catch (e) {
      if (request !== mapRequest || $("map-profile").value !== id) return;
      if (mapData) mapData.status = "stale";
      L.text($("map-message"), L.join(L.errorMessage(e), L.m(" Poprzedni obraz, jeśli widoczny, jest nieaktualny.")));
      throw e;
    }
  }
  async function loadPlacementPolicy() {
    try {
      const d = await api("placement-policy");
      if (!d || !d.document || !Number.isInteger(d.nextEpoch)) throw new Error("Invalid placement policy");
      if (!dirtyForms.has("placement-form")) {
        placementData = d;
        placementDraft = structuredClone(d.document);
        renderPlacement();
      }
      $("placement-fields").disabled = !d.enabled || d.status !== "ready";
      L.text($("placement-status"), d.status !== "ready" || !d.enabled
        ? L.m("Ustawienia rozmieszczenia są niedostępne. Ostatnia poprawna wersja pozostaje aktywna.")
        : L.join(L.m("Zapisane ustawienia"), " · ", d.scheduledEpoch ? date(d.scheduledEpoch * 86400000) : L.m("Aktywne"),
          " · ", L.m("Następna zmiana: "), date(d.nextEpoch * 86400000)));
    } catch {
      $("placement-fields").disabled = true;
      L.text($("placement-status"), L.m("Ustawienia rozmieszczenia są niedostępne. Ostatnia poprawna wersja pozostaje aktywna."));
    }
  }
  async function loadMapContext(id, request) {
    mapContext = null; placementPreview = null;
    $("placement-diagnostics").replaceChildren(); drawMap();
    L.text($("map-context-status"), L.m("Pobieranie lokalnej mapy…"));
    try {
      const d = await api("map/context?profile=" + encodeURIComponent(id));
      if (request !== mapRequest || $("map-profile").value !== id) return;
      if (!Array.isArray(d.features) || !Array.isArray(d.cells)) throw new Error("Invalid map context");
      mapContext = d;
      L.text($("map-context-status"), L.join("© OpenStreetMap contributors · ",
        L.m("Lokalny indeks OSM"), " · ", d.sourceTimestamp ? date(d.sourceTimestamp) : L.m("Brak daty"),
        d.truncated ? L.m(" Lista została ograniczona przez serwer.") : ""));
      renderPlacementDiagnostics(); drawMap();
    } catch {
      if (request !== mapRequest || $("map-profile").value !== id) return;
      L.text($("map-context-status"), L.m("Podkład jest niedostępny. Pozycje z ostatniej odpowiedzi pozostają widoczne."));
      $("placement-diagnostics").replaceChildren(); drawMap();
    }
  }
  function capturePlacement() {
    if (!placementDraft) return;
    placementDraft.maxPoints = Number($("placement-cap").value);
    placementDraft.spacingMeters = Number($("placement-spacing").value);
    for (const kind of ["exclusions", "preferred"])
      for (const row of $("placement-" + kind).querySelectorAll("[data-control]")) {
        const value = placementDraft[kind].find(p => p.id === row.dataset.control);
        for (const input of row.querySelectorAll("input")) value[input.dataset.field] = Number(input.value);
      }
  }
  function placementChanged() {
    capturePlacement(); placementPreview = null;
    $("placement-diagnostics").replaceChildren();
    markDirty("placement-form");
    L.text($("placement-preview-status"), L.m("Sprawdź podgląd przed zapisem. Niebieskie okręgi pokazują przyszłe miejsca."));
    drawMap();
  }
  function renderPlacement() {
    if (!placementDraft) return;
    $("placement-cap").value = placementDraft.maxPoints;
    $("placement-spacing").value = placementDraft.spacingMeters;
    for (const kind of ["exclusions", "preferred"]) {
      const container = $("placement-" + kind); container.replaceChildren();
      for (const row of placementDraft[kind]) {
        const group = el("div", null, "placement-control"); group.dataset.control = row.id;
        group.append(el("code", row.id));
        for (const [field, label, min, max, step] of [["lat", "Szerokość geograficzna", -85, 85, "any"],
          ["lng", "Długość geograficzna", -180, 180, "any"],
          ...(kind === "exclusions" ? [["radiusMeters", "Promień (m)", 10, 1000, 1]] : [])]) {
          const wrapper = el("label", L.m(label)), input = el("input");
          Object.assign(input, {type:"number", min, max, step, required:true, value:row[field]});
          input.dataset.field = field; wrapper.append(input); group.append(wrapper);
        }
        group.append(button(L.m("Usuń z wersji roboczej"), () => {
          capturePlacement(); placementDraft[kind] = placementDraft[kind].filter(p => p.id !== row.id);
          renderPlacement(); placementChanged();
          $(kind === "exclusions" ? "placement-add-area" : "placement-add-point").focus();
        }, "secondary"));
        container.append(group);
      }
      if (!placementDraft[kind].length) container.append(el("p", L.m("Brak"), "muted"));
    }
  }
  function addPlacement(kind) {
    if (!placementDraft) return;
    capturePlacement();
    if (placementDraft[kind].length >= (kind === "exclusions" ? 32 : 64)) return;
    const point = mapData?.points?.find(p => p.id === selectedPoint) || mapCamera;
    if (!point) { notice(L.m("Wybierz i pobierz obszar."), true); return; }
    placementDraft[kind].push({id:kind + "-" + Date.now(), lat:Number(point.lat.toFixed(6)), lng:Number(point.lng.toFixed(6)),
      ...(kind === "exclusions" ? {radiusMeters:50} : {})});
    renderPlacement(); placementChanged();
    $("placement-" + kind).querySelector(".placement-control:last-child input").focus();
  }
  function renderPlacementDiagnostics() {
    if (!mapContext) return;
    const t = table([L.m("Komórka"), L.m("Bezpieczne miejsca"), L.m("Wybrane miejsca"), L.m("Odrzucone"), L.m("Odstęp / limit")]);
    const reasons = {road:L.m("Drogi"), "major-road":L.m("Drogi"), building:L.m("Budynki"), water:L.m("Woda"),
      excluded:L.m("Wykluczone obszary"), duplicate:L.m("Powtórzenia"), "outside-cell":L.m("Poza komórką"),
      "unmapped-preferred":L.m("Brak pokrycia OSM")};
    for (const c of mapContext.cells) {
      const tr = el("tr"), rejected = Object.entries(c.rejected || {}).map(([key,n]) => L.join(reasons[key] || key, ": ", n));
      tr.append(el("td", c.id), el("td", c.covered ? c.safe || 0 : L.m("Brak pokrycia OSM")),
        el("td", c.selected), el("td", L.list(rejected, " · ") || "—"),
        el("td", (c.spacingRejected || 0) + " / " + (c.capacityRejected || 0)));
      t.body.append(tr);
    }
    $("placement-diagnostics").replaceChildren(t.table);
  }
  function drawMapContext(svg, project, scale, layers) {
    if (!mapContext) return;
    if (layers.has("context")) {
      for (const f of [...mapContext.features].sort((a,b) => ["road","path","waterway"].includes(a.kind) - ["road","path","waterway"].includes(b.kind))) {
        const line = ["road", "path", "waterway"].includes(f.kind);
        const d = f.rings.map(r => r.map(([lat,lng], i) => (i ? "L " : "M ") + project({lat,lng}).join(" ")).join(" ") + (line ? "" : " Z")).join(" ");
        const shape = svgNode("path", {d, class:"map-context map-context-" + f.kind, "fill-rule":"evenodd"});
        if (f.name) { const title=svgNode("title"); title.textContent=f.name; shape.append(title); }
        svg.append(shape);
      }
      const labels = mapContext.features.filter(f=>f.kind==="road" && f.name).slice(0,30);
      for (const f of labels) {
        const middle=f.rings[0][Math.floor(f.rings[0].length/2)], [x,y]=project({lat:middle[0],lng:middle[1]});
        const text=svgNode("text",{x,y:y-6,class:"map-context-label","text-anchor":"middle"});
        text.textContent=f.name; svg.append(text);
      }
      for (const c of mapContext.cells) {
        const d = c.corners.map(([lat,lng],i)=>(i?"L ":"M ")+project({lat,lng}).join(" ")).join(" ")+" Z";
        svg.append(svgNode("path",{d,class:"map-cell-boundary"}));
      }
    }
    if (mapContext.preview && placementPreview) for (const c of mapContext.cells) for (const p of c.points) {
      const [cx,cy]=project(p); svg.append(svgNode("circle",{cx,cy,r:5,class:"map-placement-preview"}));
    }
    if ($("placement-editor").open && placementDraft) {
      for (const p of placementDraft.exclusions) {
        const [cx,cy]=project(p); svg.append(svgNode("circle",{cx,cy,r:p.radiusMeters*scale/111320,class:"map-placement-exclusion"}));
      }
      for (const p of placementDraft.preferred) {
        const [cx,cy]=project(p); svg.append(svgNode("path",{d:`M ${cx-7} ${cy} h 14 M ${cx} ${cy-7} v 14`,class:"map-placement-preferred"}));
      }
    }
  }
  function gpsVisible() {
    return view === "world" && activeWorldTab === "gps" && !document.hidden;
  }
  function stopGps() {
    gpsController?.abort(); gpsController = null;
    clearTimeout(gpsTimer); gpsTimer = null; gpsRequest++; gpsBusy = false;
    $("gps-refresh").removeAttribute("aria-disabled");
  }
  function clearGps() {
    stopGps(); gpsData = null; gpsPage = 0;
    $("gps-content").hidden = true;
    $("gps-message").hidden = false; $("gps-message").classList.remove("error");
    L.text($("gps-message"), L.m("Wybierz profil, aby sprawdzić GPS i dystans."));
  }
  async function loadGps() {
    const id = $("gps-profile").value;
    if (!id || gpsBusy || !gpsVisible()) return;
    const selection = window.getSelection();
    if (saving || $("gps-events").contains(document.activeElement)
        || (selection && !selection.isCollapsed && $("gps-content").contains(selection.anchorNode))) {
      clearTimeout(gpsTimer); gpsTimer = setTimeout(() => void loadGps(),10000); return;
    }
    clearTimeout(gpsTimer); gpsBusy = true;
    const epoch = ++gpsRequest, controller = new AbortController();
    gpsController = controller;
    const timeout = setTimeout(() => controller.abort(new DOMException("GPS read timeout", "TimeoutError")), 15000);
    $("gps-refresh").setAttribute("aria-disabled", "true");
    if (!gpsData) {
      $("gps-message").hidden = false;
      L.text($("gps-message"), L.m("Pobieranie danych GPS…"));
    }
    try {
      const d = await api("profiles/" + encodeURIComponent(id) + "/distance", {signal:controller.signal});
      if (epoch !== gpsRequest || $("gps-profile").value !== id || !gpsVisible()) return;
      if (!d || d.profileId !== id || !["legacy","shadow","protected"].includes(d.mode)
          || !Number.isFinite(Date.parse(d.observedAt)) || !Number.isFinite(d.totals?.metres)
          || d.totals.metres < 0 || !Array.isArray(d.lastEvents) || !d.policy || !d.quality)
        throw new L.Error(L.m("Niepoprawna odpowiedź panelu. "));
      gpsData = d;
      $("gps-content").dataset.stale = "false";
      $("gps-message").hidden = true; $("gps-message").classList.remove("error");
      renderGps();
    } catch (e) {
      if (epoch !== gpsRequest || $("gps-profile").value !== id) return;
      $("gps-content").dataset.stale = "true";
      $("gps-message").hidden = false; $("gps-message").classList.add("error");
      L.text($("gps-message"), L.join(L.errorMessage(e), " ", L.m("Poprzednie dane GPS, jeśli widoczne, są nieaktualne.")));
    } finally {
      clearTimeout(timeout);
      if (epoch === gpsRequest) {
        gpsController = null;
        gpsBusy = false; $("gps-refresh").removeAttribute("aria-disabled");
        if (gpsVisible()) gpsTimer = setTimeout(() => void loadGps(), 10000);
      }
    }
  }
  function gpsMode(mode) {
    return {legacy:L.m("Ochrona wyłączona"),shadow:L.m("Tryb obserwacji"),protected:L.m("Ochrona aktywna")}[mode] || mode;
  }
  function gpsReason(reason) {
    return gpsReasonLabels[reason] || reason || "—";
  }
  function gpsMetres(n) {
    return Number.isFinite(n) ? L.join(numbers.format(Math.round(n * 10) / 10), " m") : "—";
  }
  function validGpsPolicy(d) {
    return d && typeof d.revision === "string" && ["shadow","protected"].includes(d.document?.mode);
  }
  function renderGpsPolicy() {
    if (!gpsPolicy) return;
    if (!dirtyForms.has("gps-policy-form")) $("gps-policy-mode").value = gpsPolicy.document.mode;
    L.text($("gps-policy-status"), L.join(L.m("Zapisane ustawienia"), ": ", gpsMode(gpsPolicy.document.mode)));
  }
  function renderGps() {
    const d = gpsData; if (!d) return;
    $("gps-content").hidden = false;
    const status = $("gps-status"); status.dataset.mode = d.mode;
    const explanation = {
      legacy:L.m("Klient przesyła sam przyrost dystansu. Teleporty nie są sprawdzane."),
      shadow:L.m("Ocena GPS jest próbna. Licznik nadal przyjmuje dystans starego klienta."),
      protected:L.m("Serwer nalicza zaakceptowane odcinki GPS. Dawny licznik klienta nie dodaje metrów.")
    }[d.mode];
    status.replaceChildren(el("h3", gpsMode(d.mode)), el("p", explanation));
    L.text($("gps-observed"), L.join(L.m("Odczyt: "), date(d.observedAt), L.m(" · odświeżanie co 10 sekund w tym widoku")));
    const counter = (label, value) => {
      const box=el("div",null,"gps-counter");box.append(el("span",label),el("strong",value));return box;
    };
    $("gps-counters").replaceChildren(
      counter(L.m("Zapisany dystans"), gpsMetres(d.totals.metres)),
      counter(d.totals.rebasedAt ? L.m("Zaliczone od punktu odniesienia") : L.m("Zaliczone od włączenia ochrony"), gpsMetres(d.totals.acceptedMetresSinceProtection)),
      d.mode === "protected"
        ? counter(d.totals.rebasedAt ? L.m("Dystans punktu odniesienia") : L.m("Dystans sprzed ochrony"), gpsMetres(d.totals.legacyBaselineMetres))
        : counter(L.m("Dystans próbny — bez naliczenia"), gpsMetres(d.totals.shadowAcceptedMetres)));
    const quality={"not-observed":L.m("Brak danych GPS"),acquiring:L.m("Oczekiwanie na kolejny pomiar"),tracking:L.m("Pomiar przyjęty"),rejected:L.m("Pomiar odrzucony"),stale:L.m("Pomiar nieaktualny")}[d.quality.status] || d.quality.status;
    const fixRows=[[L.m("Stan"),quality],[L.m("Powód"),gpsReason(d.quality.reason)]];
    if (d.totals.rebasedAt) fixRows.push([L.m("Punkt odniesienia od"), date(d.totals.rebasedAt)]);
    if (d.lastFix) {
      const f=d.lastFix;
      fixRows.push([L.m("Współrzędne"), L.join(L.number(f.lat,{maximumFractionDigits:5}), ", ",L.number(f.lng,{maximumFractionDigits:5}))],
        [L.m("Dokładność GPS"),gpsMetres(f.accuracyMetres)],
        [L.m("Czas pomiaru"),date(f.capturedAt)], [L.m("Odebrano na serwerze"),date(f.receivedAt)]);
    }
    $("gps-fix").replaceChildren(facts(fixRows));
    if (!d.lastFix) $("gps-fix").append(el("p",L.m("Brak świeżej pozycji. Panel nie odtwarza trasy gracza."),"hint"));
    const reasons=Object.entries(d.rejectedReasons || {}).filter(([,n])=>n>0);
    $("gps-rejections").replaceChildren(reasons.length ? facts(reasons.map(([code,n])=>[gpsReason(code),numbers.format(n)])) : el("p",L.m("Brak zarejestrowanych odrzuceń."),"muted"));
    renderGpsEvents();
    const policy=d.policy;
    $("gps-policy").replaceChildren(facts([
      [L.m("Maksymalna niedokładność"),gpsMetres(policy.maxAccuracyMetres)],
      [L.m("Maksymalna przerwa między pomiarami"),L.join(policy.maxGapSeconds," s")],
      [L.m("Maksymalny wiek pomiaru"),L.join(policy.maxFixAgeSeconds," s")],
      [L.m("Maksymalna prędkość"),L.join(policy.maxSpeedMetresPerSecond," m/s")],
      [L.m("Limit zdarzeń"),policy.maxEvents]
    ]),el("p",L.m("Pomiary pochodzą z klienta. Walidacja odrzuca skoki i błędne odcinki, ale nie potwierdza fizycznej lokalizacji urządzenia."),"hint"));
  }
  function renderGpsEvents() {
    const events=gpsData?.lastEvents || [], size=8;
    if (!events.length) { empty($("gps-events"),L.m("Brak zarejestrowanych decyzji.")); return; }
    gpsPage=Math.min(gpsPage,Math.ceil(events.length/size)-1);
    const shadow = gpsData.mode === "shadow" || events.some(e=>e.shadowAcceptedMetres>0);
    const headers=[L.m("Czas"),L.m("Decyzja"),L.m("Powód"),L.m("Zaliczone metry")];
    if (shadow) headers.push(L.m("Próbne metry"));
    headers.push(L.m("Pomiary"));
    const t=table(headers);
    for (const e of events.slice(gpsPage*size,(gpsPage+1)*size)) {
      const row=el("tr");
      row.append(el("td",date(e.at)),el("td",gpsReason(e.decision)),el("td",gpsReason(e.reason)),el("td",gpsMetres(e.acceptedMetres)));
      if (shadow) row.append(el("td",gpsMetres(e.shadowAcceptedMetres)));
      row.append(el("td",numbers.format(e.fixCount)));
      t.body.append(row);
    }
    $("gps-events").replaceChildren(t.table,pager(events.length,gpsPage,n=>{gpsPage=n;renderGpsEvents();},size));
  }
  const gpsReasonLabels = {
    "baseline":L.m("Punkt odniesienia"),
    "acquiring":L.m("Ustalanie pozycji"),
    "walking":L.m("Prawidłowy ruch"),
    "stationary":L.m("Postój lub szum GPS"),
    "confirming":L.m("Potwierdzanie przemieszczenia"),
    "invalid-fix":L.m("Nieprawidłowy pomiar"),
    "missing-accuracy":L.m("Brak dokładności pomiaru"),
    "inaccurate":L.m("Pomiar zbyt niedokładny"),
    "mock-location":L.m("Pozorowana lokalizacja"),
    "non-monotonic":L.m("Nieprawidłowa kolejność pomiarów"),
    "clock-discontinuity":L.m("Skok zegara urządzenia"),
    "stale-fix":L.m("Pomiar zbyt stary"),
    "future-fix":L.m("Pomiar z przyszłości"),
    "long-gap":L.m("Zbyt długa przerwa"),
    "speed-jump":L.m("Skok pozycji lub nadmierna prędkość"),
    "return-jump":L.m("Powrót po skoku pozycji"),
    "resynchronized":L.m("Nowy punkt odniesienia"),
    "session-reset":L.m("Nowa sesja"),
    "capture-overlap":L.m("Powtórzony czas pomiaru"),
    "legacy-blocked":L.m("Dawny raport dystansu odrzucony"),
    "accepted":L.m("Przyjęto"),
    "rejected":L.m("Odrzucono"),
    "ignored":L.m("Bez naliczenia"),
  };
  function setWorldTab(next) {
    activeWorldTab = ["settings", "gps"].includes(next) ? next : "map";
    $("world-settings").hidden = activeWorldTab !== "settings";
    $("world-observation").hidden = activeWorldTab !== "map";
    $("world-gps").hidden = activeWorldTab !== "gps";
    if (gpsVisible() && $("gps-profile").value) void loadGps();
    else stopGps();
    for (const b of document.querySelectorAll("[data-world-tab]"))
      b.setAttribute("aria-pressed", String(b.dataset.worldTab === activeWorldTab));
    if (activeWorldTab === "map" && mapData) drawMap();
  }
  function mapLayers() {
    return new Set([...document.querySelectorAll("#map-layers input:checked")].map(n => n.value));
  }
  function filteredMapPoints() {
    const layers = mapLayers(), rarity = $("map-rarity").value,
      query = $("map-search").value.trim().toLocaleLowerCase();
    return (mapData?.points || []).filter(p => layers.has(p.kind)
      && (!rarity || p.kind !== "monster" || String(p.rarity) === rarity)
      && String(L.join(mapPointName(p), " ", p.id)).toLocaleLowerCase().includes(query));
  }
  function updateMapFilters() {
    mapPage = 0;
    if (selectedPoint && !filteredMapPoints().some(p => p.id === selectedPoint)) {
      selectedPoint = null;
      renderMapSelection();
    }
    if (mapData) drawMap();
    renderMapTable();
  }
  function fitMap() {
    mapCamera = null;
    mapZoom = 1;
    if (mapData) drawMap();
  }
  function svgNode(tag, attrs = {}) {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    return n;
  }
  function mapPointName(p) {
    return (
      p.name ||
      {
        herb: L.m("Zioło"),
        nest: L.m("Nemeton"),
        quest: L.m("Zadanie"),
        monster: L.m("Potwór"),
      }[p.kind] ||
      L.m("Obiekt")
    );
  }
  function renderMap() {
    if (!mapData) return;
    const d = mapData,
      ready = d.status !== "empty" && (d.points?.length > 0 || d.cells?.some(c => Number.isFinite(c.lat) && Number.isFinite(c.lng)));
    $("map-message").hidden = false;
    L.text(
      $("map-message"),
      d.status === "empty"
        ? L.join(
            L.join(
              L.m("Brak zachowanej obserwacji"),
              d.emptyReason === "expired" ? L.m(" — poprzednia wygasła.") : ".",
            ),
            L.m(
              " Otwórz mapę w LAB, a potem odśwież ten widok. To nie oznacza braku potworów.",
            ),
          )
        : L.join(
            L.join(
              L.join(
                L.join(
                  L.join(
                    d.status === "stale"
                      ? L.m("Nieaktualna obserwacja. ")
                      : L.m("Ostatnia zarejestrowana odpowiedź. "),
                    date(d.observedAt),
                  ),
                  " · ",
                ),
                Math.round(d.ageSeconds || 0),
              ),
              L.m(" s temu. Obiekty mogły już wygasnąć lub zostać pokonane."),
            ),
            d.truncated ? L.m(" Lista została ograniczona przez serwer.") : "",
          ),
    );
    $("map-empty").hidden = ready;
    $("world-map").toggleAttribute("hidden", !ready);
    $("map-scale").hidden = !ready;
    L.text(
      $("map-area-label"),
      d.status === "empty"
        ? L.m("Brak danych mapy")
        : L.join(
            L.join(
              L.join(d.cells?.length || 0, L.m(" komórek · ")),
              d.points?.length || 0,
            ),
            L.m(" obiektów"),
          ),
    );
    for (const kind of ["monster", "herb", "nest", "quest"])
      L.text(
        $("layer-" + kind),
        (d.points || []).filter((x) => x.kind === kind).length,
      );
    $("map-metadata").replaceChildren(
      ...facts([
        [L.m("Źródło"), L.m("Ostatnia niepusta odpowiedź RPC 40")],
        [L.m("Zakres"), L.m("Obszar wysłany wybranemu klientowi")],
        [L.m("Odczyt"), d.observedAt ? date(d.observedAt) : L.m("Brak")],
        [
          L.m("Retencja"),
          L.join((d.retentionSeconds || 3600) / 60, L.m(" min")),
        ],
      ]).children,
    );
    renderMapSelection();
    if (ready) {
      drawMap();
      const c = d.cells?.[0] || d.points[0];
      const link = el("a", L.m("Otwórz obszar w OpenStreetMap ↗"), "map-link");
      link.href =
        "https://www.openstreetmap.org/#map=15/" + c.lat + "/" + c.lng;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      $("map-metadata").append(link);
    }
    renderMapTable();
  }
  function drawMap() {
    if (!mapData || $("world-observation").hidden || view !== "world") return;
    const svg = $("world-map"), width = svg.clientWidth, height = svg.clientHeight;
    if (!width || !height) return;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    while (svg.children.length > 2) svg.lastChild.remove();
    const points = filteredMapPoints(), layers = mapLayers(),
      coords = [...points, ...(layers.has("cells") ? mapData.cells || [] : [])]
        .filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng));
    $("map-filter-empty").hidden = points.length > 0 || mapData.status === "empty";
    if (!coords.length) { $("map-scale").hidden = true; return; }
    if (!mapCamera) {
      const minLat = Math.min(...coords.map(p => p.lat)), maxLat = Math.max(...coords.map(p => p.lat)),
        minLng = Math.min(...coords.map(p => p.lng)), maxLng = Math.max(...coords.map(p => p.lng));
      mapCamera = { lat: (minLat + maxLat) / 2, lng: (minLng + maxLng) / 2,
        latSpan: Math.max(maxLat - minLat, .001), lngSpan: Math.max(maxLng - minLng, .001) };
    }
    const cosine = Math.max(.001, Math.cos(mapCamera.lat * Math.PI / 180)),
      scale = Math.min((width - 76) / (mapCamera.lngSpan * cosine), (height - 120) / mapCamera.latSpan) * mapZoom,
      project = p => [width / 2 + (p.lng - mapCamera.lng) * cosine * scale,
        height / 2 - (p.lat - mapCamera.lat) * scale];
    mapCamera.scale = scale;
    mapCamera.cosine = cosine;
    drawMapContext(svg, project, scale, layers);
    if (layers.has("cells")) for (const c of mapData.cells || []) {
      if (!Number.isFinite(c.lat) || !Number.isFinite(c.lng)) continue;
      const [x, y] = project(c);
      svg.append(svgNode("path", { d: `M ${x-7} ${y} h 14 M ${x} ${y-7} v 14`, class: "map-cell" }));
    }
    const buckets = new Map(), singles = [], grid = width < 500 ? 38 : 28;
    mapClusters.clear();
    for (const p of points) {
      if (!Number.isFinite(p.lat) || !Number.isFinite(p.lng)) continue;
      const [x,y] = project(p), key = Math.floor(x / grid) + ":" + Math.floor(y / grid);
      if (p.id === selectedPoint) { singles.push(p); continue; }
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(p);
    }
    for (const [key, group] of buckets) {
      if (group.length === 1) { singles.push(group[0]); continue; }
      const point = { lat:group.reduce((n,p)=>n+p.lat,0)/group.length, lng:group.reduce((n,p)=>n+p.lng,0)/group.length },
        [x,y] = project(point);
      if (x < -30 || y < -30 || x > width+30 || y > height+30) continue;
      mapClusters.set(key, point);
      const cluster = svgNode("g", {class:"map-cluster",transform:`translate(${x} ${y})`,"data-cluster":key,"aria-hidden":"true"});
      cluster.append(svgNode("circle",{r:18,class:"map-hit"}),svgNode("circle",{r:14}));
      const count = svgNode("text",{"text-anchor":"middle",dy:".35em"}); count.textContent=group.length; cluster.append(count);
      const title=svgNode("title");L.text(title,L.m("Grupa punktów — kliknij liczbę, aby przybliżyć. Wszystkie obiekty są na liście."));cluster.append(title);
      svg.append(cluster);
    }
    for (const p of [...singles.filter(p=>p.id!==selectedPoint), ...singles.filter(p=>p.id===selectedPoint)]) {
      if (!Number.isFinite(p.lat) || !Number.isFinite(p.lng)) continue;
      const [x, y] = project(p);
      if (x < -30 || y < -30 || x > width + 30 || y > height + 30) continue;
      const marker = svgNode("g", { class: "map-marker" + (selectedPoint === p.id ? " selected" : ""),
        transform: `translate(${x} ${y})`, "data-point": p.id, "aria-hidden": "true" });
      marker.append(svgNode("circle", { r: 22, class: "map-hit" }));
      const shape = p.kind === "monster" ? svgNode("path", {d:"M 0 -9 L 8 0 0 9 -8 0 Z"})
        : p.kind === "nest" ? svgNode("rect", {x:-7,y:-7,width:14,height:14,rx:2})
        : p.kind === "quest" ? svgNode("path", {d:"M 0 -9 L 8 7 -8 7 Z"})
        : svgNode("circle", {r:6});
      shape.setAttribute("class", "map-symbol " + p.kind);
      shape.setAttribute("fill", {monster:"#e3bc73",herb:"#add694",nest:"#d6b7ea",quest:"#a9d9ee"}[p.kind] || "#fff");
      if (p.kind === "monster" && Number(p.rarity) > 1)
        marker.append(svgNode("circle", {r:13, class:"map-rarity-ring rarity-"+p.rarity}));
      marker.append(shape);
      const title = svgNode("title"); L.text(title, L.join(mapPointName(p), " · ", rarityNames[p.rarity] || p.kind)); marker.append(title);
      marker.addEventListener("click", () => { if (!mapSuppressClick) selectMapPoint(p); });
      svg.append(marker);
    }
    mapMetresPerUnit = 111320 / scale;
    $("map-scale").hidden = false;
    updateMapScale();
    L.text($("map-zoom-label"), Math.round(mapZoom * 100) + "%");
  }
  function updateMapScale() {
    if (mapMetresPerUnit) L.text($("map-scale"), L.join("≈ " + Math.round($("map-scale").clientWidth * mapMetresPerUnit), L.m(" m")));
  }
  function zoomMap(factor) {
    mapZoom = Math.min(24, Math.max(.5, mapZoom * factor));
    drawMap();
  }
  function panMap(dx, dy) {
    if (!mapCamera?.scale) return;
    mapCamera.lng -= dx / (mapCamera.scale * mapCamera.cosine);
    mapCamera.lat += dy / mapCamera.scale;
    drawMap();
  }
  function renderMapSelection() {
    const p = mapData?.points?.find(p => p.id === selectedPoint);
    if (!p) {
      $("map-selection").replaceChildren(el("p", L.m("Wybierz znacznik lub obiekt z listy."), "muted"));
      return;
    }
    $("map-selection").replaceChildren(el("h3", mapPointName(p)), el("code", p.id), facts([
      [L.m("Rodzaj"), {monster:L.m("Potwór"),herb:L.m("Zioło"),nest:L.m("Nemeton"),quest:L.m("Zadanie")}[p.kind] || p.kind],
      [L.m("Rzadkość"), rarityNames[p.rarity] || p.rarity || "—"],
      [L.m("Czas wygaśnięcia"), p.expiresAt ? date(p.expiresAt) : L.m("Nie podano")],
      [L.m("Pozycja"), Number.isFinite(p.lat) && Number.isFinite(p.lng) ? p.lat.toFixed(5) + ", " + p.lng.toFixed(5) : "—"],
    ]));
    if (p.kind === "monster" && balanceData?.species?.some(s => String(s.monsterId) === String(p.monsterId)))
      $("map-selection").append(button(L.m("Edytuj częstotliwość gatunku"), () => {
        setWorldTab("settings");
        document.querySelector(".species-editor").open = true;
        $("species-search").value = String(p.monsterId);
        $("species-rarity").value = "";
        speciesPage = 0; renderSpecies();
        $("species-search").focus();
        $("species-search").scrollIntoView({block:"center"});
      }));
  }
  function selectMapPoint(p, center = false) {
    selectedPoint = p.id;
    if (center && mapCamera) { mapCamera.lat = p.lat; mapCamera.lng = p.lng; }
    renderMapSelection();
    drawMap();
    for (const row of document.querySelectorAll("#map-objects tr[data-point]"))
      row.classList.toggle("row-selected", row.dataset.point === p.id);
    if (center) $("map-selection").scrollIntoView({block:"nearest"});
  }
  function renderMapTable() {
    const points = filteredMapPoints();
    L.text($("map-count"), points.length);
    if (!points.length) {
      empty(
        $("map-objects"),
        mapData?.status === "empty"
          ? L.m("Brak zachowanej obserwacji.")
          : L.m("Brak obiektów pasujących do aktywnych filtrów."),
      );
      return;
    }
    const t = table([
      L.m("Obiekt"),
      L.m("Rodzaj"),
      L.m("Rzadkość"),
      L.m("Wygasa"),
    ]);
    mapPage = Math.min(mapPage, Math.max(0, Math.ceil(points.length / 10) - 1));
    for (const p of points.slice(mapPage * 10, mapPage * 10 + 10)) {
      const row = el("tr");
      row.dataset.point = p.id;
      row.classList.toggle("row-selected", selectedPoint === p.id);
      const name = el("td");
      name.append(
        button(mapPointName(p), () => selectMapPoint(p, true), "plain-button"),
        el("small", p.id),
      );
      row.append(
        name,
        el(
          "td",
          {
            monster: L.m("Potwór"),
            herb: L.m("Zioło"),
            nest: L.m("Nemeton"),
            quest: L.m("Zadanie"),
          }[p.kind] || p.kind,
        ),
        el("td", rarityNames[p.rarity] || p.rarity || "—"),
        el("td", p.expiresAt ? date(p.expiresAt) : "—"),
      );
      t.body.append(row);
    }
    $("map-objects").replaceChildren(
      t.table,
      pager(points.length, mapPage, (n) => {
        mapPage = n;
        renderMapTable();
      }, 10),
    );
  }
  function renderCatalogueOptions() {
    const old = catalogueData?.uiSelection || "bestiary",
      select = $("catalogue-kind");
    select.replaceChildren(L.option(L.m("Bestiariusz"), "bestiary"));
    const main = el("optgroup"),
      advanced = el("optgroup");
    L.attr(main, "label", L.m("Dane rozgrywki"));
    L.attr(advanced, "label", L.m("Zaawansowane tabele kontraktu"));
    const names = new Set([
      "monsters",
      "monster_families",
      "skills",
      "swords",
      "armors",
      "potions",
      "oils",
      "bombs",
      "ingredients",
      "recipes",
      "shop_bundles",
      "shop_items",
      "brewers",
      "lures",
      "levels",
      "achievements",
      "events",
      "daily_quests",
    ]);
    for (const t of catalogueData.tables || [])
      (names.has(t.name) ? main : advanced).append(
        L.option(
          L.join(L.join(catalogueLabel(t.name), " · "), t.count),
          t.name,
        ),
      );
    select.append(main, advanced);
    if ([...select.options].some((o) => o.value === old)) select.value = old;
  }
  function catalogueLabel(name) {
    return (
      {
        shop_bundles: L.m("Pakiety w sklepie"),
        shop_items: L.m("Oferta sklepu"),
        lures: L.m("Przynęty"),
        monsters: L.m("Potwory — tabela klienta"),
        monster_families: L.m("Rodziny potworów"),
        items: L.m("Przedmioty"),
        recipes: L.m("Receptury"),
        skills: L.m("Umiejętności"),
        potions: L.m("Eliksiry"),
        bombs: L.m("Petardy"),
        oils: L.m("Oleje"),
        swords: L.m("Miecze"),
        armors: L.m("Zbroje"),
        ingredients: L.m("Składniki"),
        achievements: L.m("Bibeloty"),
        brewers: L.m("Stanowiska alchemii"),
        contracts: L.m("Warunki zadań"),
        events: L.m("Wydarzenia"),
        daily_quests: L.m("Zadania dzienne"),
        levels: L.m("Poziomy postaci"),
        Monster: L.m("Potwory"),
        Monsters: L.m("Potwory"),
        Item: L.m("Przedmioty"),
        Items: L.m("Przedmioty"),
        Recipe: L.m("Receptury"),
        Recipes: L.m("Receptury"),
        Skill: L.m("Umiejętności"),
        Skills: L.m("Umiejętności"),
        Potion: L.m("Eliksiry"),
        Bomb: L.m("Petardy"),
        Oil: L.m("Oleje"),
        Sword: L.m("Miecze"),
        Armor: L.m("Zbroje"),
      }[name] || name
    );
  }
  function renderCatalogue() {
    const kind = $("catalogue-kind").value,
      q = $("catalogue-search").value.toLowerCase(),
      all =
        kind === "bestiary"
          ? catalogueData.bestiary || []
          : (catalogueData.tables || []).find((t) => t.name === kind)?.rows ||
            [],
      rows = all.filter((r) => JSON.stringify(r).toLowerCase().includes(q));
    L.text(
      $("catalogue-total"),
      L.join(rows.length + " / " + all.length, L.m(" pozycji")),
    );
    $("catalogue-detail").hidden = true;
    if (!rows.length) {
      empty(
        $("catalogue-content"),
        L.m("Brak pozycji pasujących do wyszukiwania."),
      );
      return;
    }
    const best = kind === "bestiary",
      t = table(
        best
          ? [L.m("Gatunek"), L.m("Rodzina"), L.m("Rzadkość"), L.m("Trudność")]
          : [L.m("Pozycja"), L.m("Typ / opis"), L.m("Właściwości")],
      );
    cataloguePage = Math.min(
      cataloguePage,
      Math.max(0, Math.ceil(rows.length / 25) - 1),
    );
    for (const r of rows.slice(cataloguePage * 25, cataloguePage * 25 + 25)) {
      const row = el("tr"),
        name = el("td"),
        id = r.monsterId ?? r.id ?? r.Id ?? "",
        title = r.name ?? r.Name ?? r.slug ?? r.Title ?? L.join(L.m("ID "), id);
      name.append(
        button(title, () => showCatalogueDetail(title, r), "plain-button"),
        el(
          "small",
          L.join(L.join(L.m("ID "), id), r.slug ? " · " + r.slug : ""),
        ),
      );
      row.append(name);
      if (best)
        row.append(
          el("td", familyNames[r.family] || r.family),
          el(
            "td",
            {
              1: L.m("Pospolity"),
              2: L.m("Rzadki"),
              3: L.m("Legendarny"),
            }[r.rarity] || r.rarity,
          ),
          el(
            "td",
            r.skulls === undefined
              ? r.difficulty
              : L.join(r.skulls, L.m(" czaszki")),
          ),
        );
      else {
        const keys = Object.keys(r).filter(
          (k) => !["id", "Id", "name", "Name", "Title"].includes(k),
        );
        row.append(
          el(
            "td",
            pretty(
              r.type ??
                r.Type ??
                r.description ??
                r.Description ??
                keys[0] ??
                "—",
            ),
          ),
          el("td", L.join(keys.length, L.m(" pól · otwórz szczegóły"))),
        );
      }
      t.body.append(row);
    }
    $("catalogue-content").replaceChildren(
      t.table,
      pager(rows.length, cataloguePage, (n) => {
        cataloguePage = n;
        renderCatalogue();
      }),
    );
  }
  function pager(count, page, onPage, size = 25) {
    const box = el("div", null, "pagination");
    function turn(next, direction) {
      const host = box.parentElement;
      onPage(next);
      const controls = [...host.querySelectorAll(".pagination button")];
      const wanted = controls[direction],
        target =
          wanted && !wanted.disabled
            ? wanted
            : controls.find((b) => !b.disabled);
      target?.focus({
        preventScroll: true,
      });
    }
    const previous = button(L.m("← Poprzednie"), () => turn(page - 1, 0));
    previous.disabled = page === 0;
    const next = button(L.m("Następne →"), () => turn(page + 1, 1));
    next.disabled = (page + 1) * size >= count;
    const countLabel = el(
      "span",
      L.join(
        L.join(
          Math.min(count, page * size + 1) +
            "–" +
            Math.min(count, (page + 1) * size),
          L.m(" z "),
        ),
        count,
      ),
    );
    countLabel.setAttribute("role", "status");
    box.append(countLabel, previous, next);
    return box;
  }
  function showCatalogueDetail(title, row) {
    const target = $("catalogue-detail");
    target.hidden = false;
    const head = el("div", null, "section-heading");
    head.append(
      el("h2", title),
      button(L.m("Zamknij"), () => {
        target.hidden = true;
      }),
    );
    target.replaceChildren(head, facts(Object.entries(row)));
    target.scrollIntoView({
      behavior: "auto",
      block: "nearest",
    });
  }
  function renderReceipts() {
    const filter = $("audit-filter").value,
      rows = receipts.filter((r) => filter === "all" || r.outcome === filter);
    $("receipts").replaceChildren(...rows.map((r) => receiptItem(r)));
    if (!rows.length)
      empty(
        $("receipts"),
        receipts.length
          ? L.m("Brak operacji pasujących do wybranego wyniku.")
          : L.m("Brak zarejestrowanych operacji panelu."),
      );
  }
  function openProfile(p, action, backup = null) {
    profileAction = {
      p,
      action,
      backup,
    };
    $("profile-form").reset();
    $("dialog-error").hidden = true;
    L.text(
      $("dialog-title"),
      {
        restore: L.m("Przywróć wcześniejszy zapis"),
        reset: L.m("Zresetuj postęp gracza"),
        copy: L.m("Skopiuj postęp z innego profilu"),
        clock: L.m("Przesuń zegar fabuły"),
      }[action],
    );
    L.text(
      $("dialog-effect"),
      {
        restore: L.m(
          "Zapis sprzed wybranej operacji zastąpi bieżący postęp. Bieżący zapis otrzyma własną kopię.",
        ),
        reset: L.m(
          "Gracz zacznie od samouczka. Zastąpione zostaną przedmioty, waluta, umiejętności i historia zadań.",
        ),
        copy: L.m(
          "Postęp źródła zastąpi cały zapis celu. Źródło pozostanie bez zmian; profile dalej rozwijają się niezależnie.",
        ),
        clock: L.m(
          "Zmieni się tylko zegar fabularny tego gracza. Stemple i globalne zadania czasowe zachowają swoją dobę.",
        ),
      }[action],
    );
    L.text(
      $("dialog-target"),
      L.join(
        L.join(
          L.join(L.join(p.name || L.m("Bez nazwy"), L.m(" · cel ")), p.id),
          L.m(" · rewizja "),
        ),
        p.revision,
      ),
    );
    $("source-label").hidden = action !== "copy";
    $("clock-label").hidden = action !== "clock";
    $("profile-source").replaceChildren(
      ...profiles
        .filter((s) => s.id !== p.id && s.schema === 2 && !s.activeSessions)
        .map((s) =>
          L.option(
            L.join(L.join(s.name || L.m("Bez nazwy"), " · "), s.id),
            s.id,
          ),
        ),
    );
    $("profile-submit").disabled =
      action === "copy" && !$("profile-source").options.length;
    L.text(
      $("profile-submit"),
      {
        reset: L.m("Zresetuj ten profil"),
        copy: L.m("Zastąp postęp celu"),
        restore: L.m("Przywróć ten zapis"),
        clock: L.m("Przesuń zegar tego gracza"),
      }[action],
    );
    $("profile-dialog").showModal();
    $("profile-confirm").focus();
  }
  function submit(id, fn, path) {
    $(id).addEventListener("submit", (e) => {
      e.preventDefault();
      busy(
        e.currentTarget,
        () => fn(),
        typeof path === "function" ? path() : path,
      );
    });
  }
  submit(
    "news-form",
    async () => {
      captureNews();
      if (!reviewNews()) return;
      const path = "news/" + newsLanguage,
        result = await api(path, {
          method: "PUT",
          body: JSON.stringify(news),
        });
      news.revision = result.revision;
      newsSavedIds = news.document.news_list.map(item => item.id);
      $("news-errors").hidden = true;
      await finish(result, "news-form", path);
      renderNewsList();
    },
    () => "news/" + newsLanguage,
  );
  submit(
    "balance-form",
    async () => {
      if (!balanceData || !balanceDraft) return;
      const error = balanceValidation();
      if (error) throw new L.Error(error);
      const document = normalizedBalance(balanceDraft);
      const result = await api("world/balance", {
        method: "PUT",
        body: JSON.stringify({ revision: balanceData.saved.revision, document }),
      });
      let current = null;
      try { current = await api("world/balance"); } catch {}
      const verified = await finish(result, "balance-form", "world/balance", current);
      if (verified) {
        balanceData = current;
        balanceDraft = structuredClone(current.saved.document);
        renderBalance();
      } else {
        // A receipt proves acceptance, but keep the operator's draft until read-back succeeds.
        markDirty("balance-form");
        renderBalanceState();
      }
    },
    "world/balance",
  );
  $("balance-form").addEventListener("invalid", (event) => {
    const details = event.target.closest("details");
    if (details) details.open = true;
  }, true);
  for (const name of ["common", "rare", "legendary"])
    $("balance-" + name).addEventListener("input", (event) => {
      if (!balanceDraft) return;
      balanceDraft[name] = event.target.value;
      markDirty("balance-form");
      renderBalanceState();
    });
  for (const id of ["species-search", "species-rarity"])
    $(id).addEventListener(id === "species-search" ? "input" : "change", () => {
      speciesPage = 0;
      renderSpecies();
    });
  $("balance-defaults").addEventListener("click", () => {
    if (!balanceData) return;
    balanceDraft = structuredClone(balanceData.defaults);
    markDirty("balance-form");
    renderBalance();
  });
  $("balance-discard").addEventListener("click", () => {
    if (!balanceData) return;
    balanceDraft = structuredClone(balanceData.saved.document);
    dirtyForms.delete("balance-form");
    syncDraft();
    if ($("notice").classList.contains("error")) $("notice").hidden = true;
    renderBalance();
  });
  submit(
    "world-form",
    async () => {
      const next = {
        ...worldData.saved,
        document: {
          ...worldData.saved.document,
          monsterSlotsPerCell: Number($("world-density").value),
        },
      };
      const result = await api("world", {
        method: "PUT",
        body: JSON.stringify(next),
      });
      worldData.saved = next;
      worldData.saved.revision = result.revision;
      await finish(result, "world-form", "world");
      let now = await api("world");
      if (
        now.effective.monsterSlotsPerCell !== next.document.monsterSlotsPerCell
      ) {
        await new Promise((resolve) => setTimeout(resolve, 1100));
        now = await api("world");
      }
      L.text($("world-effective"), now.effective.monsterSlotsPerCell);
    },
    "world",
  );
  submit(
    "tuning-form",
    async () => {
      const density = Number($("tuning-world-density").value);
      if (density !== worldData.saved.document.monsterSlotsPerCell) {
        const next = { ...worldData.saved, document: { ...worldData.saved.document, monsterSlotsPerCell: density } };
        const saved = await api("world", { method: "PUT", body: JSON.stringify(next) });
        worldData.saved = { ...next, revision: saved.revision };
      }
      const values = {};
      for (const input of $("tuning-fields").querySelectorAll("input[data-key]")) values[input.dataset.key] = Number(input.value);
      const result = await api("tuning", {
        method: "PUT",
        body: JSON.stringify({ revision: tuningData.revision, document: { schemaVersion: 1, values } }),
      });
      tuningData = await api("tuning");
      await finish(result, "tuning-form", "tuning", tuningData);
      renderTuning();
    },
    "tuning",
  );
  $("tuning-defaults").addEventListener("click", () => {
    for (const s of tuningData?.definitions || []) $("tuning-" + s.key).value = s.default;
    if (tuningData) $("tuning-world-density").value = 18;  // WorldSpawns.DefaultMonsterSlotsPerCell
    markDirty("tuning-form");
  });
  submit(
    "weather-form",
    async () => {
      const manual = $("weather-mode").value === "manual",
        expiry = new Date($("weather-expiry").value);
      if (
        manual &&
        (!Number.isFinite(expiry.getTime()) ||
          expiry <= new Date() ||
          expiry > Date.now() + 86400000)
      )
        throw new L.Error(
          L.m(
            "Wybierz przyszły termin wygaśnięcia, nie później niż za 24 godziny.",
          ),
        );
      const document = {
        schemaVersion: 1,
        mode: manual ? "manual" : "automatic",
        code: manual ? Number($("weather-code").value) : null,
        expiresAt: manual ? expiry.toISOString() : null,
      };
      const result = await api("weather", {
        method: "PUT",
        body: JSON.stringify({
          revision: weatherData.saved.revision,
          document,
        }),
      });
      await finish(result, "weather-form", "weather");
      weatherData = await api("weather");
      if (
        weatherData.effective.mode !== document.mode ||
        (manual && !weatherData.effective.overrideActive)
      ) {
        await new Promise((resolve) => setTimeout(resolve, 1100));
        weatherData = await api("weather");
      }
      renderWeather();
    },
    "weather",
  );
  submit(
    "rotation-form",
    async () => {
      const result = await api("tasks/daily", {
        method: "PUT",
        body: JSON.stringify(taskData.daily),
      });
      taskData.daily.revision = result.revision;
      await finish(result, "rotation-form", "tasks");
    },
    "tasks",
  );
  submit(
    "hunt-form",
    async () => {
      taskData.hunt.document.streak = $("hunt-streak").checked;
      const result = await api("tasks/hunt", {
        method: "PUT",
        body: JSON.stringify(taskData.hunt),
      });
      taskData.hunt.revision = result.revision;
      await finish(result, "hunt-form", "tasks");
    },
    "tasks",
  );
  submit(
    "stage-form",
    async () => {
      let document;
      try {
        document = JSON.parse($("task-catalogue").value);
      } catch {
        throw new L.Error(
          L.m(
            "Niepoprawna składnia JSON. Wersja robocza pozostała w edytorze.",
          ),
        );
      }
      const result = await api("tasks/staged", {
        method: "PUT",
        body: JSON.stringify({
          revision: taskData.catalogue.revision,
          document,
        }),
      });
      await finish(result, "stage-form");
      L.text(
        $("staged-list"),
        L.join(L.m("Przygotowano: "), result.receipt.id),
      );
    },
    "tasks",
  );
  submit("image-form", async () => {
    const file = $("image-file").files[0];
    if (!file || file.size > 2 * 1024 * 1024)
      throw new L.Error(L.m("Wybierz obraz PNG/JPEG do 2 MiB."));
    const result = await api("images/" + encodeURIComponent(file.name), {
      method: "PUT",
      headers: {
        "Content-Type": file.type,
        "If-Match": "missing",
      },
      body: file,
    });
    await finish(result, "image-form");
    if (news?.document.news_list.length) {
      $("news-image").value = file.name;
      markDirty("news-form");
    }
    L.text(
      $("image-list"),
      L.join(
        L.join(L.m("Dodano "), file.name),
        L.m(". Opublikuj wiadomości, aby przypisać okładkę."),
      ),
    );
  });
  submit("profile-form", async () => {
    const { p, action, backup } = profileAction,
      source = profiles.find((s) => s.id === $("profile-source").value);
    try {
      const result = await api("profiles/" + encodeURIComponent(p.id), {
        method: "POST",
        body: JSON.stringify({
          revision: p.revision,
          action,
          backup,
          confirm: $("profile-confirm").value,
          source: action === "copy" ? source?.id : null,
          sourceRevision: action === "copy" ? source?.revision : null,
          seconds: action === "clock" ? Number($("clock-seconds").value) : 0,
        }),
      });
      $("profile-dialog").close();
      await finish(result, "profile-form");
      profiles = await api("profiles");
      if (view === "profiles") renderProfiles();
    } catch (e) {
      $("dialog-error").hidden = false;
      L.text($("dialog-error"), L.errorMessage(e));
      $("dialog-error").tabIndex = -1;
      $("dialog-error").focus();
    }
  });
  submit("label-form", async () => {
    const path = "profiles/" + encodeURIComponent(labelProfile.id) + "/label";
    $("label-result").hidden = true;
    try {
      const result = await api(path, {method:"PUT", body:JSON.stringify({revision:labelData.revision,document:{label:$("profile-label").value}})});
      labelData.revision = result.revision;
      labelData.document.label = $("profile-label").value.trim();
      const verified = await finish(result, "label-form", path);
      labelProfile.label = labelData.document.label;
      renderProfiles();
      $("label-result").hidden = false;
      L.text($("label-result"), L.join(L.m("Zapisano"), " · ", result.receipt.id, ". ", verified
        ? L.m("Potwierdzono ponownym odczytem.") : L.m("Odczyt po zapisie nie potwierdził stanu — sprawdź historię.")));
    } catch(e) {
      $("label-result").hidden = false;
      $("label-result").replaceChildren(el("p", L.errorMessage(e)));
      if (e.status === 409) $("label-result").append(button(L.m("Porównaj aktualny zapis"), async () => {
        try {
          const current = await api(path);
          $("label-result").replaceChildren(el("p", L.join(L.m("Obecnie na serwerze"), ": ", current.document.label || "—")),
            button(L.m("Zachowaj moją wersję na nowej rewizji"), () => {
              labelData = current;
              $("label-result").hidden = true; $("profile-label").focus();
            }));
        } catch(readError) { L.text($("label-result"), L.errorMessage(readError)); }
      }));
    }
  });
  $("label-close").addEventListener("click", closeProfileLabel);
  $("label-dialog").addEventListener("cancel", e => { e.preventDefault(); closeProfileLabel(); });
  $("placement-editor").addEventListener("toggle", drawMap);
  $("placement-form").addEventListener("input", placementChanged);
  $("placement-add-area").addEventListener("click", () => addPlacement("exclusions"));
  $("placement-add-point").addEventListener("click", () => addPlacement("preferred"));
  $("placement-discard").addEventListener("click", () => {
    if (!placementData) return;
    placementDraft=structuredClone(placementData.document); placementPreview=null;
    dirtyForms.delete("placement-form"); syncDraft(); renderPlacement(); drawMap();
    L.text($("placement-preview-status"), "");
    if (mapData) void loadMapContext($("map-profile").value, mapRequest);
  });
  $("placement-preview").addEventListener("click", () => {
    if (!$("placement-form").reportValidity()) return;
    busy($("placement-form"), async () => {
      capturePlacement();
      const profile = $("map-profile").value;
      if (!profile || !mapData) throw new L.Error(L.m("Wybierz i pobierz obszar."));
      const body = {revision:placementData.revision, document:placementDraft};
      const checked = await api("placement-policy/preview?profile=" + encodeURIComponent(profile), {method:"POST",body:JSON.stringify(body)});
      if (profile !== $("map-profile").value) return;
      mapContext=checked; placementPreview=JSON.stringify(placementDraft);
      L.text($("placement-preview-status"), L.join(L.m("Podgląd przyszłych miejsc: "), date(checked.epoch * 86400000),
        " · ", checked.cells.reduce((sum,c)=>sum+c.selected,0), " · ", L.m("Sprawdź podgląd przed zapisem. Niebieskie okręgi pokazują przyszłe miejsca.")));
      renderPlacementDiagnostics(); drawMap();
    }, "placement-policy");
  });
  submit("placement-form", async () => {
    capturePlacement();
    if (placementPreview !== JSON.stringify(placementDraft))
      throw new L.Error(L.m("Sprawdź podgląd przed zapisem. Niebieskie okręgi pokazują przyszłe miejsca."));
    const result = await api("placement-policy", {method:"PUT",body:JSON.stringify({revision:placementData.revision,document:placementDraft})});
    let current=null; try {current=await api("placement-policy");} catch {}
    const verified=await finish(result,"placement-form","placement-policy",current);
    if (verified) { placementData=current; placementDraft=structuredClone(current.document); await loadPlacementPolicy(); }
    else markDirty("placement-form");
  }, "placement-policy");
  submit("map-form", loadMap);
  $("gps-form").addEventListener("submit", e => { e.preventDefault(); void loadGps(); });
  $("gps-profile").addEventListener("change", () => { clearGps(); void loadGps(); });
  submit("gps-policy-form", async () => {
    if (!gpsPolicy) return;
    const result=await api("distance-policy",{method:"PUT",body:JSON.stringify({revision:gpsPolicy.revision,document:{mode:$("gps-policy-mode").value}})});
    let confirmed = null;
    try { const d = await api("distance-policy"); if (validGpsPolicy(d)) confirmed = d; } catch {}
    await finish(result,"gps-policy-form","distance-policy",confirmed);
    if (confirmed) { gpsPolicy=confirmed; renderGpsPolicy(); }
    else {
      gpsPolicy=null; $("gps-policy-fields").disabled=true;
      L.text($("gps-policy-status"), L.m("Odczyt po zapisie nie potwierdził stanu — sprawdź historię."));
    }
  }, "distance-policy");
  for (const id of ["dialog-close", "dialog-cancel"])
    $(id).addEventListener("click", () => {
      $("profile-dialog").close();
      dirtyForms.delete("profile-form");
      syncDraft();
    });
  for (const id of ["detail-close", "detail-done"])
    $(id).addEventListener("click", () => $("detail-dialog").close());
  for (const id of ["conflict-close", "conflict-done"])
    $(id).addEventListener("click", () => {
      $("conflict-dialog").close();
      L.text($("conflict-title"), L.m("Porównaj przed ponownym zapisem"));
    });
  $("profile-dialog").addEventListener("cancel", (e) => {
    if (saving) e.preventDefault();
    else {
      dirtyForms.delete("profile-form");
      syncDraft();
    }
  });
  $("refresh").addEventListener("click", async () => {
    if (saving) return;
    if (
      viewDrafts().length &&
      !window.confirm(
        L.m(
          "Odrzucić niezapisane zmiany w tym widoku i pobrać aktualną wersję serwera?",
        ),
      )
    )
      return;
    for (const id of viewDrafts()) dirtyForms.delete(id);
    syncDraft();
    await load();
  });
  document.addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const next = a.getAttribute("href").slice(1);
    if (views[next]) {
      e.preventDefault();
      void navigate(next).then(ok => {
        if (!ok) return;
        if (a.dataset.worldOpen) setWorldTab(a.dataset.worldOpen);
        if (a.dataset.helpTopic) {
          const topic = $(a.dataset.helpTopic);
          if (topic) { topic.open = true; topic.scrollIntoView({block:"start"}); topic.querySelector("summary").focus(); }
        }
      });
    }
  });
  window.addEventListener("popstate", () => {
    const next = location.hash.slice(1);
    if (views[next] && next !== view) navigate(next, false, true);
  });
  window.addEventListener("beforeunload", (e) => {
    if (dirtyForms.size) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  for (const f of document.querySelectorAll("form"))
    if (!["map-form", "gps-form", "balance-form", "engine-form"].includes(f.id)) f.addEventListener("input", () => markDirty(f.id));
  $("news-language").addEventListener("change", () => {
    if (
      viewDrafts("news").length &&
      !window.confirm(L.m("Porzucić niezapisane komunikaty i zmienić język?"))
    ) {
      $("news-language").value = newsLanguage;
      return;
    }
    for (const id of viewDrafts("news")) dirtyForms.delete(id);
    syncDraft();
    load();
  });
  $("news-add").addEventListener("click", () => {
    if (!news) return;
    captureNews();
    const id = Math.max(0, ...news.document.news_list.map((n) => n.id)) + 1;
    news.document.news_list.push({
      id,
      group_id: "news-" + id,
      title: "Nowy komunikat",
      short_description: "",
      date: new Date().toLocaleDateString("en-GB"),
      image_url: "",
      content: "",
    });
    newsIndex = news.document.news_list.length - 1;
    markDirty("news-form");
    renderNewsList();
    renderNews();
    $("news-title").focus();
  });
  $("news-remove").addEventListener("click", () => {
    const item = news.document.news_list.splice(newsIndex, 1)[0];
    if (news.document.featured === item.id) news.document.featured = 0;
    newsIndex = Math.max(0, newsIndex - 1);
    markDirty("news-form");
    renderNewsList();
    renderNews();
  });
  $("news-save-empty").addEventListener("click", () =>
    busy(
      $("news-form"),
      async () => {
        if (!reviewNews()) return;
        const result = await api("news/" + newsLanguage, {
          method: "PUT",
          body: JSON.stringify(news),
        });
        news.revision = result.revision;
        newsSavedIds = [];
        $("news-errors").hidden = true;
        await finish(result, "news-form", "news/" + newsLanguage);
      },
      "news/" + newsLanguage,
    ),
  );
  $("news-form").addEventListener("input", renderNewsPreview);
  for (const b of document.querySelectorAll("[data-task-tab]"))
    b.addEventListener("click", () => {
      activeTaskTab = b.dataset.taskTab;
      for (const n of document.querySelectorAll("[data-task-tab]"))
        n.setAttribute("aria-pressed", String(n === b));
      for (const section of document.querySelectorAll(".task-section"))
        section.hidden =
          section.id !==
          (activeTaskTab === "catalogue"
            ? "task-catalogue-section"
            : "task-" + activeTaskTab);
    });
  $("task-search").addEventListener("input", () => {
    if (taskData) renderRotation();
  });
  $("profile-search").addEventListener("input", renderProfiles);
  $("weather-mode").addEventListener("change", setWeatherMode);
  $("map-search").addEventListener("input", updateMapFilters);
  $("map-rarity").addEventListener("change", updateMapFilters);
  $("map-filter-reset").addEventListener("click", () => {
    $("map-search").value = ""; $("map-rarity").value = "";
    for (const n of document.querySelectorAll("#map-layers input")) n.checked = true;
    updateMapFilters(); fitMap();
  });
  for (const b of document.querySelectorAll("[data-world-tab]"))
    b.addEventListener("click", () => setWorldTab(b.dataset.worldTab));
  $("help-return").addEventListener("click", () => navigate(helpReturnView));
  $("map-profile").addEventListener("change", () => {
    mapRequest++;
    mapCamera = null; mapZoom = 1;
    $("map-filter-empty").hidden = true;
    mapData = null; mapContext = null; placementPreview = null;
    L.text($("map-context-status"), "");
    selectedPoint = null;
    mapPage = 0;
    $("world-map").setAttribute("hidden", "");
    $("map-empty").hidden = false;
    $("map-scale").hidden = true;
    L.text($("map-area-label"), L.m("Nie pobrano danych wybranego profilu"));
    $("map-message").hidden = false;
    L.text(
      $("map-message"),
      L.m(
        "Wybór profilu zmieniony. Otwórz jego ostatni obszar, aby pobrać obserwację.",
      ),
    );
    $("map-selection").replaceChildren(
      el("p", L.m("Wybierz i pobierz obszar."), "muted"),
    );
    for (const k of ["monster", "herb", "nest", "quest"])
      L.text($("layer-" + k), "—");
    $("map-metadata").replaceChildren();
    empty($("map-objects"), L.m("Oczekuje na odczyt wybranego profilu."));
    L.text($("map-count"), "—");
  });
  $("map-layers").addEventListener("change", updateMapFilters);
  $("catalogue-kind").addEventListener("change", () => {
    catalogueData.uiSelection = $("catalogue-kind").value;
    cataloguePage = 0;
    renderCatalogue();
  });
  $("catalogue-search").addEventListener("input", () => {
    if (catalogueData) {
      cataloguePage = 0;
      renderCatalogue();
    }
  });
  $("audit-filter").addEventListener("change", renderReceipts);
  $("server-metrics-refresh").addEventListener("click", () => {
    if (!serverMetricsController) void refreshServerMetrics();
  });
  document.addEventListener("visibilitychange", () => {
    if (view === "engine" && !document.hidden) void engine.load(); else engine.stop();
    if (gpsVisible() && $("gps-profile").value) void loadGps(); else stopGps();
    if (metricsVisible()) void refreshServerMetrics();
    else stopServerMetrics();
  });
  window.addEventListener("pagehide", stopServerMetrics);
  window.addEventListener("pagehide", stopGps);
  window.addEventListener("pagehide", () => engine.stop());
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && view === "engine") void engine.load();
    if (event.persisted && metricsVisible()) void refreshServerMetrics();
    if (event.persisted && gpsVisible() && $("gps-profile").value) void loadGps();
  });
  new ResizeObserver(() => { if (mapData) drawMap(); }).observe($("world-map"));
  $("map-zoom-in").addEventListener("click", () => zoomMap(1.5));
  $("map-zoom-out").addEventListener("click", () => zoomMap(1 / 1.5));
  $("map-zoom-reset").addEventListener("click", fitMap);
  $("world-map").addEventListener("keydown", e => {
    const moves = {ArrowLeft:[55,0],ArrowRight:[-55,0],ArrowUp:[0,55],ArrowDown:[0,-55]};
    if (moves[e.key]) { e.preventDefault(); panMap(...moves[e.key]); }
    else if (["+", "=", "-", "Home"].includes(e.key)) {
      e.preventDefault();
      if (e.key === "Home") fitMap(); else zoomMap(e.key === "-" ? 1 / 1.5 : 1.5);
    }
  });
  $("world-map").addEventListener("pointerdown", e => {
    if (e.button !== 0 || !mapCamera) return;
    mapSuppressClick = false;
    mapDrag = {id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};
    $("world-map").setPointerCapture(e.pointerId);
  });
  $("world-map").addEventListener("pointermove", e => {
    if (mapDrag?.id !== e.pointerId) return;
    if (Math.hypot(e.clientX-mapDrag.startX,e.clientY-mapDrag.startY)>5) mapSuppressClick = true;
    if (mapSuppressClick) panMap(e.clientX-mapDrag.x,e.clientY-mapDrag.y);
    mapDrag.x=e.clientX; mapDrag.y=e.clientY;
  });
  for (const name of ["pointerup","pointercancel","lostpointercapture"])
    $("world-map").addEventListener(name, e => {
      if (mapDrag?.id === e.pointerId) {
        // Capture retargets pointerup: resolve a tap from the current coordinates.
        if (name === "pointerup" && !mapSuppressClick) {
          const hit = document.elementFromPoint(e.clientX,e.clientY),
            cluster = hit?.closest("[data-cluster]"), group = mapClusters.get(cluster?.dataset.cluster);
          if (group) { mapCamera.lat=group.lat; mapCamera.lng=group.lng; zoomMap(2); }
          const marker = hit?.closest("[data-point]");
          const point = mapData?.points?.find(p => p.id === marker?.dataset.point);
          if (point) selectMapPoint(point);
        }
        mapDrag = null;
      }
    });
  navigate(views[location.hash.slice(1)] ? location.hash.slice(1) : "overview");
})();
