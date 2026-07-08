// TWMS boot capture + redirect. Focus: OnetimeWebstuffPreloader (the synchronous boot-time static-data
// fetch that blocks the title screen). Offsets are arm64 RVAs from dump/arm64_v1043 (v1.0.43).
// See docs/protocol-boot.md §9b for the decoded protocol.
const IP = "127.0.0.1";   // via `adb reverse tcp:4253` -> PC:4253 (bypasses WiFi/firewall)
const PORT = 4253;
const REDIRECT = true;   // force the preloader to connect to our server (Host=IP, Port, UseGatekeeper=false)

const startTime = Date.now();
function log(msg) { send("[" + (Date.now() - startTime) + "ms] " + msg); }

// Preloader RVAs
const R = {
    ctor:                    0x18A60B4,
    Preload:                 0x18A610C,
    Connect:                 0x18A62B8,
    GetServerAddress:        0x18A653C,
    SendStaticGameDataRequest:0x18A6448,
    CreateRequestPayload:    0x18A66F0,
    ReceiveStaticGameDataJson:0x18A647C,
    DnsGetHostEntry:         0x20C5EFC,
    // gatekeeper URL redirect (for the later main flow)
    UriCtor1:                0x295D220,
    UriCtor2:                0x295D484,
};

function readStr(p) {
    try {
        if (p.isNull()) return "(null)";
        const len = p.add(0x10).readInt();
        if (len < 0 || len > 8192) return "(len " + len + "?)";
        if (len === 0) return "";
        return p.add(0x14).readUtf16String(len);
    } catch (e) { return "(err)"; }
}

function hexArr(p, max) {
    try {
        if (p.isNull()) return "(null-array)";
        const len = p.add(0x18).readInt();          // il2cpp Array: length @ 0x18, data @ 0x20
        const n = Math.min(len, max || 64);
        const bytes = p.add(0x20).readByteArray(n);
        return "len=" + len + " [" + Array.from(new Uint8Array(bytes)).map(b => ("0" + b.toString(16)).slice(-2)).join(" ") + "]";
    } catch (e) { return "(arr-err)"; }
}

let mod = null;
let strNew = null;
function mkstr(s) { return strNew(Memory.allocUtf8String(s)); }

let installed = false;


function hookUnityWebRequest() {
    function rewriteUrlArg(args, argIndex) {
        try {
            let urlStr = args[argIndex];
            if (urlStr.isNull()) return;
            let len = urlStr.add(0x10).readU32();
            if (len <= 0 || len > 2000) return;
            let text = urlStr.add(0x14).readUtf16String(len);
            if (text.startsWith("https://")) {
                let withoutHttps = text.substring(8);
                let slashIdx = withoutHttps.indexOf("/");
                let newText = "http://34.107.152.195:8080" + (slashIdx === -1 ? "" : withoutHttps.substring(slashIdx));
                if (newText.length <= text.length) {
                    log("UWR rewrite IN-PLACE: " + text + " -> " + newText);
                    urlStr.add(0x10).writeU32(newText.length);
                    urlStr.add(0x14).writeUtf16String(newText);
                } else {
                    log("UWR rewrite FAILED (longer): " + text + " -> " + newText);
                }
            }
        } catch(e) {}
    }

    Interceptor.attach(at(0x3118E68), { onEnter: function(args) { rewriteUrlArg(args, 1); }});
    Interceptor.attach(at(0x3118F64), { onEnter: function(args) { rewriteUrlArg(args, 1); }});
    Interceptor.attach(at(0x3119148), { onEnter: function(args) { rewriteUrlArg(args, 1); }});
    Interceptor.attach(at(0x3118ED8), { onEnter: function(args) { rewriteUrlArg(args, 1); }});
    Interceptor.attach(at(0x311AB74), { onEnter: function(args) { rewriteUrlArg(args, 0); }});
    Interceptor.attach(at(0x311AC08), { onEnter: function(args) { rewriteUrlArg(args, 0); }});
    Interceptor.attach(at(0x311AF78), { onEnter: function(args) { rewriteUrlArg(args, 0); }});
}

function installIl2cpp() {
    if (installed) return;
    const m = Process.findModuleByName("libil2cpp.so");
    if (m === null) return;                 // not loaded yet; caller will retry
    installed = true;
    mod = m;
    log("libil2cpp.so @ " + m.base + " (size " + m.size + "). Installing hooks.");

    const strNewPtr = m.findExportByName("il2cpp_string_new");
    if (strNewPtr) strNew = new NativeFunction(strNewPtr, 'pointer', ['pointer']);

    function at(rva) { return m.base.add(rva); }

    // --- ctor: log the injected config (Host, Port, UseGatekeeper, GatekeeperUrl) ---
    Interceptor.attach(at(R.ctor), { onEnter: function (a) {
        log("Preloader.ctor  host=" + readStr(a[1]) + "  port=" + a[2].toInt32() +
            "  useGatekeeper=" + (a[3].toInt32() & 1) + "  gatekeeperUrl=" + readStr(a[4]));
    }});

    // --- Preload: the top-level driver ---
    Interceptor.attach(at(R.Preload), {
        onEnter: function () { log(">>> Preloader.Preload() ENTER"); },
        onLeave: function (r) { log("<<< Preloader.Preload() LEAVE container=" + (r.isNull() ? "NULL" : r)); }
    });

    // --- Connect: read + optionally overwrite config so it connects to us ---
    Interceptor.attach(at(R.Connect), {
        onEnter: function (a) {
            const self = a[0];
            const host = readStr(self.add(0x10));
            const port = self.add(0x18).readInt();
            const useGk = self.add(0x1c).readU8();
            const gkUrl = readStr(self.add(0x20));
            log(">>> Preloader.Connect()  host=" + host + " port=" + port + " useGatekeeper=" + useGk + " gkUrl=" + gkUrl);
            if (REDIRECT) {
                if (strNew) self.add(0x10).writePointer(mkstr(IP));
                self.add(0x18).writeInt(PORT);
                self.add(0x1c).writeU8(0);      // UseGatekeeper=false -> use Host directly, skip HTTP
                log("    REDIRECT -> host=" + IP + " port=" + PORT + " useGatekeeper=0");
            }
        },
        onLeave: function (r) { log("<<< Preloader.Connect() socket=" + (r.isNull() ? "NULL (failed)" : r)); }
    });

    // --- GetServerAddress: the {GatekeeperUrl}/bob HTTP call (only if useGatekeeper) ---
    Interceptor.attach(at(R.GetServerAddress), {
        onEnter: function (a) { this.uid = readStr(a[1]); },
        onLeave: function (r) { log("GetServerAddress(" + this.uid + ") = " + readStr(r)); }
    });

    // --- CreateRequestPayload: confirm the 17 request bytes match our derivation ---
    Interceptor.attach(at(R.CreateRequestPayload), {
        onLeave: function (r) { log("CreateRequestPayload -> " + hexArr(r, 32)); }
    });

    // --- ReceiveStaticGameDataJson: did we get JSON back? ---
    Interceptor.attach(at(R.ReceiveStaticGameDataJson), {
        onLeave: function (r) { log("ReceiveStaticGameDataJson -> " + (r.isNull() ? "NULL" : hexArr(r, 24))); }
    });

    // --- Dns.GetHostEntry: log host; backtrace the game-server lookup to find the caller class ---
    Interceptor.attach(at(R.DnsGetHostEntry), {
        onEnter: function (a) {
            this.host = readStr(a[0]);
            if (this.host && this.host.indexOf("game-server") !== -1) {
                try {
                    const bt = Thread.backtrace(this.context, Backtracer.FUZZY)
                        .map(function (p) { return "libil2cpp+0x" + p.sub(mod.base).toString(16); })
                        .join("\n      ");
                    log("Dns.GetHostEntry(" + this.host + ") caller backtrace:\n      " + bt);
                } catch (e) { log("bt err " + e); }
            }
        }
    });

    // === Boot-path (ThreadedClient) diagnostics — the REAL boot client, per docs/protocol-boot.md §9c.
    // The preloader hooks above never fire at boot; these do. Goal: find why the socket re-syncs at 58%.
    const B = {
        TC_Connect: 0x2F85970,   // ThreadedClient.Connect
        TC_Run:     0x2F85B74,   // ThreadedClient.Run (worker loop)
        TC_Close:   0x2F860E8,   // ThreadedClient.Close (socket teardown)
        ResetGame:  0x1F3DE50,   // ResetGame..ctor
        Loader_SetText:     0x31BAF6C,   // Loader.SetText(string) -> the on-screen InitializationText
        Loader_SetProgress: 0x31BAFC4,   // Loader.SetProgress(int jobNumber, int jobsCount)
        SyncModule_OnInitialPlayerData: 0x17A4598,   // SynchronizationModule.OnGetInitialPlayerDataResponse
        SyncStatus_get_IsSynchronized:  0x1F99FD4,   // SynchronizationStatus.get_IsSynchronized (PlayerSynced && MapSynced)
        // job 123 stall investigation
        ShopKeeper_InitModule:   0x179F4AC,   // ShopKeeperModule.InitializeModule
        ShopKeeper_InitLines:    0x179F4C4,   // ShopKeeperModule.InitializeLinesProviders (coroutine ctor)
        Transaction_InitModule:  0x18FEB38,   // TransactionModule.InitializeModule
        ServerFact_InitModule:   0x178A3EC,   // ServerFactDatabaseModule.InitializeModule (approximate — confirm via SetText)
    };
    // Force SynchronizationStatus.IsSynchronized (PlayerSynced && MapSynced) -> true so the game
    // stops waiting at the final "Synchronizing game state" (200/200) gate and transitions to Map State.
    const FORCE_SYNC = true;

    function bt(ctx) {
        try {
            return Thread.backtrace(ctx, Backtracer.FUZZY)
                .map(function (p) { return "libil2cpp+0x" + p.sub(mod.base).toString(16); })
                .join("\n      ");
        } catch (e) { return "(bt err " + e + ")"; }
    }

    Interceptor.attach(at(B.TC_Connect), { onEnter: function () {
        log("== ThreadedClient.Connect()  (socket connect / RECONNECT = loop boundary)");
    }});
    Interceptor.attach(at(B.TC_Run), {
        onEnter: function () { log("== ThreadedClient.Run() ENTER (worker loop start)"); },
        onLeave: function () { log("== ThreadedClient.Run() LEAVE (worker loop exit)"); }
    });
    Interceptor.attach(at(B.TC_Close), { onEnter: function () {
        log("== ThreadedClient.Close()  <-- SOCKET TEARDOWN. backtrace:\n      " + bt(this.context));
    }});
    Interceptor.attach(at(B.ResetGame), { onEnter: function () {
        log("== ResetGame..ctor  <-- FULL GAME RESET. backtrace:\n      " + bt(this.context));
    }});

    Interceptor.attach(at(0x31BC61C), { // LoaderModule.OnGameInitializing
        onEnter: function (args) {
          try {
            const obj = args[1];
            if (obj.isNull() || obj.compare(ptr(0x10000)) < 0) return;   // progress ticks pass a non-pointer here
            const modNameStr = obj.add(0x10).readPointer();
            const initTextStr = obj.add(0x18).readPointer();

            let modName = "(null)";
            if (!modNameStr.isNull()) {
                let len = modNameStr.add(0x10).readU32();
                if (len >= 0 && len < 1000) modName = modNameStr.add(0x14).readUtf16String(len);
            }

            let initText = "(null)";
            if (!initTextStr.isNull()) {
                let len = initTextStr.add(0x10).readU32();
                if (len >= 0 && len < 1000) initText = initTextStr.add(0x14).readUtf16String(len);
            }

            log("OnGameInitializing: " + modName + " text: " + initText);
          } catch (e) {}
        }
    });

    let lastText = null;
    Interceptor.attach(at(B.Loader_SetText), { onEnter: function (a) {
        const s = readStr(a[1]);
        if (s !== lastText) { 
            lastText = s; 
            log("Loader.SetText: \"" + s + "\"");
        }
    }});
    let lastProg = null;
    Interceptor.attach(at(B.Loader_SetProgress), { onEnter: function (a) {
        const p = a[1].toInt32() + "/" + a[2].toInt32();
        if (p !== lastProg) { lastProg = p; log("Loader.SetProgress: job " + p); }
    }});

    // Job 123 stall: hook ShopKeeperModule and TransactionModule InitializeModule entry/exit
    Interceptor.attach(at(B.ShopKeeper_InitModule), {
        onEnter: function() { log(">> ShopKeeperModule.InitializeModule ENTER"); },
        onLeave: function() { log("<< ShopKeeperModule.InitializeModule LEAVE (coroutine queued)"); }
    });
    Interceptor.attach(at(B.ShopKeeper_InitLines), {
        onEnter: function() { log(">> ShopKeeperModule.InitializeLinesProviders coroutine ctor"); },
        onLeave: function(r) { log("<< InitializeLinesProviders coroutine obj=" + r); }
    });

    // Diagnosing PlayerData hang at 68%
    const PD_Signals = [
        {name: 'OnPlayerInfoResponse', rva: 0x1745324},
        {name: 'OnGetKilledMonstersResponse', rva: 0x17456E8},
        {name: 'OnGetEquipmentResponse', rva: 0x174575C},
        {name: 'OnGetAchievementsResponse', rva: 0x1745768},
        {name: 'OnGetInventoryResponse', rva: 0x1745774},
        {name: 'OnGetSkillsResponse', rva: 0x1745780}
    ];
    for (let s of PD_Signals) {
        try {
            Interceptor.attach(at(s.rva), {
                onEnter: function() { log(">>> PlayerData." + s.name + " ENTER"); },
                onLeave: function() { log("<<< PlayerData." + s.name + " LEAVE"); }
            });
        } catch(e) {}
    }



    
    // ── UN-BYPASS TOGGLE (white-screen -> visible UI bring-up) ───────────────────
    // Default EMPTY = current proven behavior (all modules below stay bypassed, boot stays clean).
    // To re-enable a module, uncomment BOTH of its RVAs (InitializeModule + get_Initialized) and re-run.
    // WARNING: un-bypassing PlayerData re-introduces the original boot deadlock UNLESS the server
    // completes the sync batch (GetInitialPlayerData sub-responses 3/5/7/9/24/63). GuiModule likely
    // pulls PlayerData + PlayerModule with it — escalate them together and watch for the next NRE.
    // ── UN-BYPASS TOGGLE ─────────────────────────────────────────────────────────
    // BRING-UP PLAN — enable ONE step at a time, confirm on phone, then advance:
    //   Run 1 (NOW):  empty set → diagnostic only; avatar hooks reveal real equipped ids
    //   Run 2:        if avatar asked for id≠1, fix ids in LoadoutOverrides + equippedId; re-run
    //   Run 3:        set env Player__SendInitialData=true; confirm SyncModule parses without throw
    //   Run 4:        uncomment GuiModule + PlayerData + PlayerModule together (needs full sync batch)
    //
    // WARNING: un-bypassing PlayerData WITHOUT the full sync batch (sub-responses 3/5/7/9/24/63)
    // re-introduces the original boot deadlock. Do NOT un-bypass PlayerData before Run 3 succeeds.
    const UNBYPASS_RVAS = new Set([
        0x17F04E0, 0x17F04CC,   // GuiModule    (UI canvas — verified self-contained: reads only its own
                                //               injected fields + Screen APIs, sets Initialized=true itself)
        0x178A3D0, 0x178A3BC,   // ServerFactDatabaseModule
        0x179F4AC, 0x179F0E0,   // ShopKeeperModule
        0x18FD0F0, 0x18FCF1C,   // ShopStorageModule
        0x18FEB38, 0x18FE994,   // TransactionModule
        // StoryModule RE-BYPASSED (2026-07-05): its InitializeModule reads the method-70/60 batch responses
        // and calls PoiModule.SetActiveQuestGivers / SetActiveQuestNodes, which iterate PoiModule's collections
        // (null because PoiModule.InitializeModule is bypassed) -> NRE freezes boot at job 196/200. StoryModule
        // CANNOT init until PoiModule genuinely initializes (allocates Instances @0x98 / Locations @0x160).
        // Un-bypass StoryModule + PoiModule + WitcherSenses together once PoiModule bring-up is done.
        0x17A0F94, 0x17A0F80,   // StoryModule (tutorial runs through it)
        // PoiModule UN-BYPASSED (2026-07-05): disasm of InitializeModule (0x17B34B8) proves it is FULLY
        // SYNCHRONOUS with NO network Synchronize call — it allocates Instances@0x98 + Locations@0x160 itself
        // (as empty dicts) and builds two Pool<DespawnFX> from _settings@0x110/0x118 (null prefabs -> our
        // Instantiate bypass). The earlier "collections null -> NRE" was ONLY because the module was bypassed;
        // the earlier stall was the pool receiving a bare GameObject (DespawnFX resolved on the wrong image).
        // Fixed: getFakeDespawnFX now queries Game.dll. Re-enable Poi + Story + WitcherSenses together.
        0x17B34B8, 0x17B3328,   // PoiModule
        0x18C6EC8, 0x18C6E8C,   // CameraModule
        0x1755F58, 0x1755F04,   // EnviroModule
        0x190BF74, 0x190BF18,   // WeatherModule (un-bypassed: Weather response added to server)
        0x1787BC4, 0x1787BB0,   // PlayerModifiersModule
        0x17E850C, 0x17E847C,   // DailyContractsModule (un-bypassed: batch Method 20 added to server)
        // WeeklyContractsModule RE-BYPASSED: its InitializeModule fires OnNewDay, which builds a
        // WeeklyQuestReward + RewardItem from IIntStorage<WeeklyQuestReward> (static weekly_quests_rewards).
        // That array is empty -> null reward -> NRE that FROZE boot at 66% (job 133/200, verified 2026-07-05).
        // Making it operational needs a weekly_quests_rewards record AND a valid backing reward item (a
        // content chain) — out of scope for "screens + tutorial". Follow-up: populate weekly_quests_rewards.
        // 0x17EE69C, 0x17EE630,   // WeeklyContractsModule
        0x17DDC80, 0x17DDC54,   // FriendsModule
        0x1799BC4, 0x1799B58,   // RewardsModule
        0x17998CC, 0x1799860,   // RateGameModule
        // WitcherSensesModule UN-BYPASSED (2026-07-05): it injects PoiModule + StoryModule and derefs their
        // runtime state — safe now that PoiModule genuinely initializes (its collections are allocated).
        0x190DAF8, 0x190D4CC,   // WitcherSensesModule
        0x17AB57C, 0x17AB568,   // TargetCompassModule
        0x17436E8, 0x17436B4,   // PlayerData   (needs sync batch — Player:SendInitialData now defaults true)
        0x173862C, 0x17384F8,   // PlayerModule (3D avatar + stats)
        0x31972F8, 0x319726C,   // BehaviourGraphModule (un-bypassed: Tutorial runs through it — server now
                                //               enables it via TutorialFinished=0. _settings is DI-bound
                                //               (BindInstance<BehaviurGraphSettings>) so may init fine; if it
                                //               NREs on null _settings, flip on the injection block below.)
    ]);

    const BypassInitModuleRVAs = [0x18FD0F0, 0x179F4AC, 0x18FEB38, 0x18C6EC8, 0x17E850C, 0x17EE69C, 0x17DDC80, 0x1755F58, 0x178A3D0, 0x1799BC4, 0x17998CC, 0x17B34B8, 0x190DAF8, 0x17AB57C, 0x190BF74, 0x31972F8, 0x17A0F94, 0x17436E8, 0x173862C, 0x1787BC4, 0x17F04E0];
    for (let rva of BypassInitModuleRVAs) {
        if (UNBYPASS_RVAS.has(rva)) { log("UN-BYPASSED InitializeModule RVA " + rva.toString(16) + " (running normally)"); continue; }
        try {
            Interceptor.replace(at(rva), new NativeCallback(function() {
                log("Bypassed InitializeModule Execution for RVA " + rva.toString(16));
            }, 'void', ['pointer']));
        } catch (e) { log("Failed to bypass InitializeModule RVA " + rva.toString(16) + ": " + e); }
    }

    // Bypass Shop and Transaction modules stalling by forcing get_Initialized() to return true
    const BypassInitRVAs = [0x18FCF1C, 0x179F0E0, 0x18FE994, 0x18C6E8C, 0x17E847C, 0x17EE630, 0x17DDC54, 0x1755F04, 0x178A3BC, 0x1799B58, 0x1799860, 0x17B3328, 0x190D4CC, 0x17AB568, 0x190BF18, 0x319726C, 0x17A0F80, 0x17436B4, 0x17384F8, 0x1787BB0, 0x17F04CC];
    for (let rva of BypassInitRVAs) {
        if (UNBYPASS_RVAS.has(rva)) { log("UN-BYPASSED get_Initialized RVA " + rva.toString(16) + " (real value)"); continue; }
        try {
            Interceptor.replace(at(rva), new NativeCallback(function() {
                return 1;
            }, 'int', ['pointer']));
            log("Bypassed get_Initialized for RVA " + rva.toString(16));
        } catch (e) { log("Failed to bypass RVA " + rva.toString(16) + ": " + e); }
    }

    // CheckTutorial() NO LONGER bypassed. Now that PlayerData correctly parses the initial sync payload,
    // transition the game out of the loading screen.
    // try {
    //     Interceptor.replace(at(0x1F9A10C), new NativeCallback(function (thiz) {
    //         log(">>> CheckTutorial() BYPASSED (no-op) — boot loop should now complete.");
    //     }, 'void', ['pointer']));
    //     log("CheckTutorial bypass installed @ 0x1F9A10C");
    // } catch (e) { log("Failed to bypass CheckTutorial: " + e); }

    // TUTORIAL TRACE (observation only) — does the S00 tutorial logic fire after boot completes?
    try { Interceptor.attach(at(0x1F9A10C), { onEnter: function() { log(">>> Tutorial.CheckTutorial ENTER"); }, onLeave: function() { log("<<< Tutorial.CheckTutorial LEAVE"); } }); log("Tutorial.CheckTutorial trace installed"); } catch(e) { log("Failed to trace CheckTutorial: " + e); }
    try { Interceptor.attach(at(0x1F9A530), { onEnter: function() { log(">>> Tutorial.ForceTutorialFinished ENTER"); } }); } catch(e) { log("Failed to trace ForceTutorialFinished: " + e); }
    try { Interceptor.attach(at(0x1F9A69C), { onEnter: function() { log('>>> Tutorial.EndTutorial ENTER'); } }); } catch(e) { log('Failed to trace EndTutorial: ' + e); }
    try { Interceptor.attach(at(0x1789A88), { onEnter: function(args) { this.key = args[1].toInt32(); }, onLeave: function(retval) { log('>>> FactDatabaseModule.GetFact(' + this.key + ') -> ' + retval.toInt32()); } }); log('FactDatabaseModule.GetFact trace installed'); } catch(e) { log('Failed to trace GetFact: ' + e); }
    try { Interceptor.attach(at(0x18A6D98), { onEnter: function(args) { log('>>> StoryModule.GetAvailableQuestNodeIds ENTER'); } }); log('StoryModule.GetAvailableQuestNodeIds trace installed'); } catch(e) { log('Failed to trace GetAvailableQuestNodeIds: ' + e); }

    // SYNCHRONIZER TRACE — SynchronizationModule.Synchronize<T> shared generic body (0x184C9F4).
    // args: (this, int methodId, Action onResponse, MethodInfo). Logs which methodId each module requests
    // from the GetInitialPlayerData batch, so we can see which sub-responses our server must add (a missing
    // methodId in _responses -> null Data -> NRE, e.g. the StoryModule InitializeModule crash at job ~196).
    try {
        Interceptor.attach(at(0x184C9F4), { onEnter: function(args) {
            log(">>> Synchronize<T> requested methodId=" + args[1].toInt32());
        }});
        log("Synchronize<T> trace installed @ 0x184C9F4");
    } catch(e) { log("Failed to trace Synchronize: " + e); }

    // BATCH-PARSE TRACE — GetInitialPlayerDataResponse.Factory.readResponse (static, 0x1F785D8).
    // args: (int methodId, ByteBuffer buffer). Logs each methodId the batch parser reads IN ORDER, plus
    // whether a response object came back. If the sequence drifts to unexpected ids (e.g. 2, 1) the method
    // read JUST BEFORE the first bad id is over/under-consuming bytes = the misalignment to fix on the server.
    try {
        Interceptor.attach(at(0x1F785D8), {
            onEnter: function(args) { this.mid = args[0].toInt32(); log(">>> readResponse methodId=" + this.mid); },
            onLeave: function(retval) { log("<<< readResponse methodId=" + this.mid + " -> " + (retval.isNull() ? "NULL (no handler)" : "ok")); }
        });
        log("readResponse trace installed @ 0x1F785D8");
    } catch(e) { log("Failed to trace readResponse: " + e); }

    // QUEST-POI SPAWN TRACE — confirms the served method-60 quest node reaches PoiModule and creates a POI.
    // List<T> il2cpp layout: _items @0x10, _size (count) @0x18. args=(this, List, ...).
    function listCount(p){ try { return (p && !p.isNull()) ? p.add(0x18).readInt() : -1; } catch(e){ return -2; } }
    try {
        Interceptor.attach(at(0x17B7C20), { onEnter: function(args){   // PoiModule.UpdateLocations(List<Location>)
            log(">>> PoiModule.UpdateLocations  locations=" + listCount(args[1]));
        }});
        Interceptor.attach(at(0x17B73E0), {   // PoiModule.SetActiveQuestNodes(List<QuestNodeInstance>, int tracked)
            onEnter: function(args){ log(">>> PoiModule.SetActiveQuestNodes  nodes=" + listCount(args[1]) + " tracked=" + args[2].toInt32()); },
            onLeave: function(){ log("<<< PoiModule.SetActiveQuestNodes LEAVE"); }
        });
        Interceptor.attach(at(0x17b7bcc), { onEnter: function(){        // QuestPoiInstance..ctor
            log(">>> QuestPoiInstance..ctor  (a quest POI is being created — node passed the PlaceId check!)");
        }});
        Interceptor.attach(at(0x17C041C), {   // QuestPoiOnMapController.OnClicked()
            onEnter: function(args) {
                const self = args[0];
                let inRange = -1, started = -1, inst = ptr(0), qid = 0, iid = 0, graph = "(n/a)";
                try { inRange = self.add(0x78).readU8(); } catch(e) {}
                try { started = self.add(0x119).readU8(); } catch(e) {}
                try {
                    inst = self.add(0x110).readPointer();
                    if (!inst.isNull()) {
                        qid = inst.add(0x5c).readInt();
                        iid = inst.add(0x38).readS64();
                        graph = readStr(inst.add(0x70).readPointer());
                    }
                } catch(e) {}
                log(">>> QuestPoiOnMapController.OnClicked inRange=" + inRange + " graphStarted=" + started +
                    " inst=" + inst + " qid=" + qid + " iid=" + iid + " graph=" + graph);
            },
            onLeave: function() { log("<<< QuestPoiOnMapController.OnClicked LEAVE"); }
        });
        Interceptor.attach(at(0x17C132C), {   // QuestPoiOnMapController.QuestNodePressed()
            onEnter: function(args) {
                const self = args[0];
                let inst = ptr(0), qid = 0, iid = 0, graph = "(n/a)";
                try {
                    inst = self.add(0x110).readPointer();
                    if (!inst.isNull()) {
                        qid = inst.add(0x5c).readInt();
                        iid = inst.add(0x38).readS64();
                        graph = readStr(inst.add(0x70).readPointer());
                    }
                } catch(e) {}
                log(">>> QuestNodePressed inst=" + inst + " qid=" + qid + " iid=" + iid + " graph=" + graph);
            }
        });
        Interceptor.attach(at(0x31982D8), {   // BehaviourGraphModule.StartQuestGraph(string,...)
            onEnter: function(args) {
                log(">>> BehaviourGraphModule.StartQuestGraph path=" + readStr(args[1]) +
                    " questNodeId=" + args[3].toInt32() + " instanceId=" + args[4].toString());
            },
            onLeave: function() { log("<<< BehaviourGraphModule.StartQuestGraph LEAVE"); }
        });
        log("Quest-POI spawn/click trace installed (UpdateLocations / SetActiveQuestNodes / QuestPoiInstance / OnClicked / StartQuestGraph)");
    } catch(e) { log("Failed to install quest-POI spawn trace: " + e); }

    // (Removed the PoiModule.SetActiveQuestGivers no-op experiment: StoryModule also calls SetActiveQuestNodes
    //  and likely more PoiModule methods, so no-oping is whack-a-mole. Real fix = initialize PoiModule.)

    // Confirm the coroutine reached the end and flipped ModulesInitialized -> true (Map State transition).
    // (RVA 0x17D5D30 = Game.get_ModulesInitialized. Was previously hooked at top-level where at() is
    //  undefined -> it threw and never installed; moved here so it actually works.)
    let modulesInitLogged = false;
    Interceptor.attach(at(0x17D5D30), { onLeave: function (retval) {
        if (!modulesInitLogged && retval.toInt32() === 1) {
            modulesInitLogged = true;
            log("############ Game.ModulesInitialized IS NOW TRUE — BOOT LOOP COMPLETE ############");
        }
    }});

    Interceptor.attach(at(B.SyncModule_OnInitialPlayerData), {
        onEnter: function () { log(">>> SynchronizationModule.OnGetInitialPlayerDataResponse ENTER"); },
        onLeave: function () { log("<<< SynchronizationModule.OnGetInitialPlayerDataResponse LEAVE (returned, no throw)"); }
    });

    let lastSync = null, forcedLogged = false;
    Interceptor.attach(at(B.SyncStatus_get_IsSynchronized), { onLeave: function (r) {
        let v = r.toInt32() & 1;
        if (FORCE_SYNC && v === 0) {
            r.replace(ptr(1));
            if (!forcedLogged) { forcedLogged = true; log("SyncStatus.IsSynchronized FORCED -> 1 (experiment)"); }
            v = 1;
        }
        if (v !== lastSync) { lastSync = v; log("SyncStatus.IsSynchronized = " + v); }
    }});

    // One-shot dump of the deserialized Container's 82 array fields (offsets 0x10..0x298) at
    // DataManager.<Load>d__100.MoveNext entry — tells us which arrays came back NULL from our JSON.
    let dumpedContainer = false;
    Interceptor.attach(at(0x1878B14), { onEnter: function (a) {
        if (dumpedContainer) return;
        try {
            const db = a[0].add(0x28).readPointer();   // <Load>d__100.database (Container)
            if (db.isNull()) return;
            dumpedContainer = true;
            let nulls = [], lens = [];
            for (let off = 0x10; off <= 0x298; off += 8) {
                const p = db.add(off).readPointer();
                if (p.isNull()) nulls.push("0x" + off.toString(16));
                else { const len = p.add(0x18).readInt(); if (len !== 0) lens.push("0x" + off.toString(16) + "=" + len); }
            }
            log("Container dump: " + nulls.length + " NULL fields = [" + nulls.join(", ") + "]");
            log("Container dump: non-empty fields = [" + lens.join(", ") + "]");
        } catch (e) { log("container dump err " + e); }
    }});

    // ── AVATAR DIAGNOSTICS (white-screen investigation) ──────────────────────────
    // The loud boot NRE is PlayerAvatar.Initialize -> ChangeSwordInternal ->
    // CreateCustomizableReference<Sword> -> LqPlayerAssetsDistributor.GetPrefabAddress(null,gender)
    // (verified: cbz appearance -> throw). These hooks reveal which equipped sword/armor/head the
    // avatar actually received (runtime Item.Id @0x20, Appearance.PrefabPath @0x58) and the address
    // the distributor resolves — so we can confirm the Container entry ids line up.
    function appStr(p) {
        if (p.isNull()) return "null";
        try { return "{id=" + p.add(0x20).readInt() + " prefab=\"" + readStr(p.add(0x58).readPointer()) + "\"}"; }
        catch (e) { return "{read-err}"; }
    }
    try {
        Interceptor.attach(at(0x17C333C), { onEnter: function (a) {   // PlayerAvatar.Initialize(gender,sword,armor,head,layer)
            log(">> PlayerAvatar.Initialize gender=" + (a[1].toInt32() & 0xff) +
                " sword=" + appStr(a[2]) + " armor=" + appStr(a[3]) + " head=" + appStr(a[4]));
        }});
        log("Avatar diag: PlayerAvatar.Initialize hook installed @ 0x17C333C");
    } catch (e) { log("Failed to hook PlayerAvatar.Initialize: " + e); }
    try {
        Interceptor.attach(at(0x17C31D8), {   // LqPlayerAssetsDistributor.GetPrefabAddress(appearance,gender)
            onEnter: function (a) {
                this.app = a[1]; this.g = a[2].toInt32() & 0xff;
                log(">> LqGetPrefabAddress ENTER appearance=" + appStr(this.app) + " gender=" + this.g);
            },
            onLeave: function (r) { log("<< LqGetPrefabAddress -> \"" + readStr(r) + "\""); }
        });
        log("Avatar diag: LqPlayerAssetsDistributor.GetPrefabAddress hook installed @ 0x17C31D8");
    } catch (e) { log("Failed to hook GetPrefabAddress: " + e); }

    // Capture the FIRST JSON-looking chunk the client's GZipStream decompresses — this is exactly
    // what DataContractJsonSerializer(typeof(Container)).ReadObject reads. Confirms gzip vs parse issue.
    let gzLogged = false;
    Interceptor.attach(at(0x214c5b8), {   // System.IO.Compression.GZipStream.Read(byte[] buf, int off, int count)
        onEnter: function (a) { this.buf = a[1]; this.off = a[2].toInt32(); },
        onLeave: function (r) {
            if (gzLogged) return;
            const n = r.toInt32();
            if (n <= 0 || this.buf.isNull()) return;
            const u = new Uint8Array(this.buf.add(0x20 + this.off).readByteArray(Math.min(n, 300)));
            let s = "";
            for (let i = 0; i < u.length; i++) s += (u[i] >= 32 && u[i] < 127) ? String.fromCharCode(u[i]) : ".";
            if (s.indexOf("{") !== -1 || s.indexOf('"') !== -1) { gzLogged = true; log("GZip.Read n=" + n + " text: " + s); }
        }
    });

    // ── MAP TILE REDIRECT (Step 1: kill the ~60s "Загрузка карты" stall) ─────────
    // Google Maps Gaming SDK fetches vector tiles via WwwRequest.CreateGetRequest(url,headers,timeout)
    // (static, arg[0]=url; wraps a UnityWebRequest). With connect():443 force-failed, ProtoTileProducer
    // retries with backoff for ~60s before MapModule gives up. Rewriting the tile URL in-place to our
    // :8080 server makes the fetch return an instant HTTP 200 → isRetriable=false → no 60s backoff.
    // http://34.107.152.195:8080/<path>  ->  hookConnect() rewrites port-8080 to 127.0.0.1:8080 (our server).
    let tileUrlLogged = 0;
    try {
        Interceptor.attach(at(0x30F55A8), { onEnter: function (a) {
            try {
                const urlStr = a[0];
                if (urlStr.isNull()) return;
                const len = urlStr.add(0x10).readU32();
                if (len <= 0 || len > 4000) return;
                const text = urlStr.add(0x14).readUtf16String(len);
                if (tileUrlLogged < 3) { tileUrlLogged++; log("WwwRequest.CreateGetRequest url=" + text); }
                if (text.startsWith("https://")) {
                    const rest = text.substring(8);
                    const slashIdx = rest.indexOf("/");
                    const newText = "http://34.107.152.195:8080" + (slashIdx === -1 ? "/" : rest.substring(slashIdx));
                    if (newText.length <= text.length) {
                        urlStr.add(0x10).writeU32(newText.length);
                        urlStr.add(0x14).writeUtf16String(newText);
                        if (tileUrlLogged <= 3) log("    tile REDIRECT -> " + newText);
                    } else {
                        log("    tile redirect FAILED (longer): " + newText);
                    }
                }
            } catch (e) { log("tile hook err " + e); }
        }});
        log("Map-tile redirect hook installed @ 0x30F55A8 (WwwRequest.CreateGetRequest)");
    } catch (e) { log("Failed to hook WwwRequest.CreateGetRequest: " + e); }

// MOD_HOOKS
    // SignalBus.Fire(object) null-Data bypass (RVA 0x1C5C6DC = SignalBus.Fire(object signal), confirmed in
    // dump). Defense-in-depth for the SignalBus-driven handlers: any MethodMessage<T> whose .Data (@0x20) is
    // null gets swallowed (skip original) so the compiler-generated null-check can't throw. NOTE: the
    // GetKnownRecipes(6) NRE that froze the 2026-07-04 boot was NOT on this path — PlayerInventory.Initialize
    // invokes its handler via ISynchronizer directly, bypassing SignalBus — so the REAL fix is sending
    // Method 6 in the batch (GameSocketService). This replace only guards the async/SignalBus packets that
    // other (still-bypassed) modules will consume later. il2cpp ABI: x0=this, x1=signal, x2=MethodInfo*.
    try {
        const fireAddr = at(0x1C5C6DC);
        const fireOrig = new NativeFunction(fireAddr, 'void', ['pointer', 'pointer', 'pointer']);
        Interceptor.replace(fireAddr, new NativeCallback(function(thiz, signal, mi) {
            try {
                if (!signal.isNull()) {
                    let klass = signal.readPointer();
                    if (!klass.isNull()) {
                        let namePtr = klass.add(0x10).readPointer();
                        if (!namePtr.isNull()) {
                            let name = namePtr.readCString();
                            if (name && name.indexOf("MethodMessage") !== -1 && signal.add(0x20).readPointer().isNull()) {
                                log(">>> BYPASSED SignalBus.Fire for missing packet: " + name);
                                return;   // skip original -> neutralize the null-Data NRE
                            }
                        }
                    }
                }
            } catch (e) {}
            fireOrig(thiz, signal, mi);   // present packets / non-MethodMessage signals: fire normally
        }, 'void', ['pointer', 'pointer', 'pointer']));
        log("SignalBus.Fire null-Data bypass (replace) installed @ 0x1C5C6DC");
    } catch(e) { log("Failed to hook SignalBus.Fire: " + e); }

    try {
        Interceptor.attach(at(0x1CE3728), {
            onEnter: function(args) {
                let msg = "(null)";
                if (!args[1].isNull()) {
                    let len = args[1].add(0x10).readInt();
                    msg = args[1].add(0x14).readUtf16String(len);
                }
                log("!!! EXCEPTION THROWN: " + msg);
                log("Backtrace:\n" + Thread.backtrace(this.context, Backtracer.ACCURATE).map(function(p) {
                    return "  " + p.sub(mod.base).toString(16);
                }).join("\n"));
            }
        });
        log("Exception hook installed @ 0x1CE3728");
    } catch(e) { log("Failed to hook Exception: " + e); }

    try { Interceptor.attach(at(0x31BC200), { onEnter: function() { log(">> LoaderModule.InitializeModule ENTER"); }, onLeave: function() { log("<< LoaderModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to LoaderModule: " + e); }
    try { Interceptor.attach(at(0x2F897F4), { onEnter: function() { log(">> WebstuffClientModule.InitializeModule ENTER"); }, onLeave: function() { log("<< WebstuffClientModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to WebstuffClientModule: " + e); }
    try { Interceptor.attach(at(0x193D1BC), { onEnter: function() { log(">> ScreenSpaceFXController.InitializeModule ENTER"); }, onLeave: function() { log("<< ScreenSpaceFXController.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to ScreenSpaceFXController: " + e); }
    try { Interceptor.attach(at(0x190DAF8), { onEnter: function() { log(">> WitcherSensesModule.InitializeModule ENTER"); }, onLeave: function() { log("<< WitcherSensesModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to WitcherSensesModule: " + e); }
    try { Interceptor.attach(at(0x190BF74), { onEnter: function() { log(">> WeatherModule.InitializeModule ENTER"); }, onLeave: function() { log("<< WeatherModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to WeatherModule: " + e); }
    try { Interceptor.attach(at(0x17AC340), { onEnter: function() { log(">> FakeDateTimeSource.InitializeModule ENTER"); }, onLeave: function() { log("<< FakeDateTimeSource.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to FakeDateTimeSource: " + e); }
    try { Interceptor.attach(at(0x17ACD1C), { onEnter: function() { log(">> SyncedTime.InitializeModule ENTER"); }, onLeave: function() { log("<< SyncedTime.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to SyncedTime: " + e); }
    try { Interceptor.attach(at(0x17AB57C), { onEnter: function() { log(">> TargetCompassModule.InitializeModule ENTER"); }, onLeave: function() { log("<< TargetCompassModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to TargetCompassModule: " + e); }
    try { Interceptor.attach(at(0x17A9FD0), { onEnter: function() { log(">> SystemNotificationsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< SystemNotificationsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to SystemNotificationsModule: " + e); }
    try { Interceptor.attach(at(0x17A4448), { onEnter: function() { log(">> SynchronizationModule.InitializeModule ENTER"); }, onLeave: function() { log("<< SynchronizationModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to SynchronizationModule: " + e); }
    try { Interceptor.attach(at(0x17A0F94), { onEnter: function() { log(">> StoryModule.InitializeModule ENTER"); }, onLeave: function() { log("<< StoryModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to StoryModule: " + e); }
    try { Interceptor.attach(at(0x179F4AC), { onEnter: function() { log(">> ShopKeeperModule.InitializeModule ENTER"); }, onLeave: function() { log("<< ShopKeeperModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to ShopKeeperModule: " + e); }
    try { Interceptor.attach(at(0x1799BC4), { onEnter: function() { log(">> RewardsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< RewardsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to RewardsModule: " + e); }
    try { Interceptor.attach(at(0x17998CC), { onEnter: function() { log(">> RateGameModule.InitializeModule ENTER"); }, onLeave: function() { log("<< RateGameModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to RateGameModule: " + e); }
    try { Interceptor.attach(at(0x17436E8), { onEnter: function() { log(">> PlayerData.InitializeModule ENTER"); }, onLeave: function() { log("<< PlayerData.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to PlayerData: " + e); }
    try { Interceptor.attach(at(0x173862C), { onEnter: function() { log(">> PlayerModule.InitializeModule ENTER"); }, onLeave: function() { log("<< PlayerModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to PlayerModule: " + e); }
    try { Interceptor.attach(at(0x17B34B8), { onEnter: function() { log(">> PoiModule.InitializeModule ENTER"); }, onLeave: function() { log("<< PoiModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to PoiModule: " + e); }
    try { Interceptor.attach(at(0x182CFD4), { onEnter: function() { log(">> NotificationModule.InitializeModule ENTER"); }, onLeave: function() { log("<< NotificationModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to NotificationModule: " + e); }
    try { Interceptor.attach(at(0x182C43C), { onEnter: function() { log(">> NiceVibrationsWrapper.InitializeModule ENTER"); }, onLeave: function() { log("<< NiceVibrationsWrapper.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to NiceVibrationsWrapper: " + e); }
    try { Interceptor.attach(at(0x18270C4), { onEnter: function() { log(">> MapModule.InitializeModule ENTER"); }, onLeave: function() { log("<< MapModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to MapModule: " + e); }
    try { Interceptor.attach(at(0x1961254), { onEnter: function() { log(">> LocationModule.InitializeModule ENTER"); }, onLeave: function() { log("<< LocationModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to LocationModule: " + e); }
    try { Interceptor.attach(at(0x19609F4), { onEnter: function() { log(">> LanguageModule.InitializeModule ENTER"); }, onLeave: function() { log("<< LanguageModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to LanguageModule: " + e); }
    // BehaviourGraphModule diagnostic (richer than the neighbouring one-liners): dump candidate DI-field
    // pointers so the orchestrator can see at runtime whether the injected `BehaviurGraphSettings _settings`
    // is null. Real layout (dump.cs ~634932-634963): _settings (BehaviurGraphSettings) @ 0x18; the other
    // [Inject] fields follow at 0x20..0x78; <Initialized> bool @ 0xE8. If _settings @0x18 is NULL, enable the
    // BEHAVIURGRAPHSETTINGS AUTO-INJECTION fallback block further below.
    try { Interceptor.attach(at(0x31972F8), {
        onEnter: function(a) {
            log(">> BehaviourGraphModule.InitializeModule ENTER");
            try {
                const self = a[0];
                let parts = [];
                for (let off = 0x18; off <= 0xF0; off += 8) {
                    const p = self.add(off).readPointer();
                    const tag = (off === 0x18) ? "_settings@0x18" : ("+0x" + off.toString(16));
                    parts.push(tag + "=" + (p.isNull() ? "NULL" : p));
                }
                log("   BGModule fields: " + parts.join(" "));
                const settings = self.add(0x18).readPointer();   // BehaviurGraphSettings _settings @ 0x18
                log("   >>> _settings (BehaviurGraphSettings) = " + (settings.isNull()
                    ? "NULL  -> enable BEHAVIURGRAPHSETTINGS AUTO-INJECTION block"
                    : settings + "  (non-null -> plain un-bypass OK, no injection needed)"));
            } catch (e) { log("   BGModule field dump err " + e); }
        },
        onLeave: function() { log("<< BehaviourGraphModule.InitializeModule LEAVE"); }
    }); } catch(e) { log("Failed to attach to BehaviourGraphModule: " + e); }
    try { Interceptor.attach(at(0x179C578), { onEnter: function() { log(">> SettingsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< SettingsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to SettingsModule: " + e); }
    try { Interceptor.attach(at(0x179B444), { onEnter: function() { log(">> PreGameConditionsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< PreGameConditionsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to PreGameConditionsModule: " + e); }
    try { Interceptor.attach(at(0x18FD0F0), { onEnter: function() { log(">> ShopStorageModule.InitializeModule ENTER"); }, onLeave: function() { log("<< ShopStorageModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to ShopStorageModule: " + e); }
    try { Interceptor.attach(at(0x18FEB38), { onEnter: function() { log(">> TransactionModule.InitializeModule ENTER"); }, onLeave: function() { log("<< TransactionModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to TransactionModule: " + e); }
    try { Interceptor.attach(at(0x17F04E0), { onEnter: function() { log(">> GuiModule.InitializeModule ENTER"); }, onLeave: function() { log("<< GuiModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to GuiModule: " + e); }
    try { Interceptor.attach(at(0x17E850C), { onEnter: function() { log(">> DailyContractsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< DailyContractsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to DailyContractsModule: " + e); }
    try { Interceptor.attach(at(0x17EE69C), { onEnter: function() { log(">> WeeklyContractsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< WeeklyContractsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to WeeklyContractsModule: " + e); }
    try { Interceptor.attach(at(0x17DDC80), { onEnter: function() { log(">> FriendsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< FriendsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to FriendsModule: " + e); }
    try { Interceptor.attach(at(0x178A3D0), { onEnter: function() { log(">> ServerFactDatabaseModule.InitializeModule ENTER"); }, onLeave: function() { log("<< ServerFactDatabaseModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to ServerFactDatabaseModule: " + e); }
    try { Interceptor.attach(at(0x1787BC4), { onEnter: function() { log(">> PlayerModifiersModule.InitializeModule ENTER"); }, onLeave: function() { log("<< PlayerModifiersModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to PlayerModifiersModule: " + e); }
    try { Interceptor.attach(at(0x1755F58), { onEnter: function() { log(">> EnviroModule.InitializeModule ENTER"); }, onLeave: function() { log("<< EnviroModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to EnviroModule: " + e); }
    try { Interceptor.attach(at(0x1952358), { onEnter: function() { log(">> TimeScaleController.InitializeModule ENTER"); }, onLeave: function() { log("<< TimeScaleController.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to TimeScaleController: " + e); }
    try { Interceptor.attach(at(0x186EBD4), { onEnter: function() { log(">> DataManager.InitializeModule ENTER"); }, onLeave: function() { log("<< DataManager.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to DataManager: " + e); }
    try { Interceptor.attach(at(0x18C6EC8), { onEnter: function() { log(">> CameraModule.InitializeModule ENTER"); }, onLeave: function() { log("<< CameraModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to CameraModule: " + e); }
    try { Interceptor.attach(at(0x18C45D0), { onEnter: function() { log(">> BatterySaver.InitializeModule ENTER"); }, onLeave: function() { log("<< BatterySaver.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to BatterySaver: " + e); }
    try { Interceptor.attach(at(0x18C0020), { onEnter: function() { log(">> AuthenticationModule.InitializeModule ENTER"); }, onLeave: function() { log("<< AuthenticationModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to AuthenticationModule: " + e); }
    try { Interceptor.attach(at(0x18B97C4), { onEnter: function() { log(">> AudioModule.InitializeModule ENTER"); }, onLeave: function() { log("<< AudioModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to AudioModule: " + e); }
    try { Interceptor.attach(at(0x31CA760), { onEnter: function() { log(">> AnalyticsModule.InitializeModule ENTER"); }, onLeave: function() { log("<< AnalyticsModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to AnalyticsModule: " + e); }
    try { Interceptor.attach(at(0x31C3960), { onEnter: function() { log(">> AmbientModule.InitializeModule ENTER"); }, onLeave: function() { log("<< AmbientModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to AmbientModule: " + e); }
    try { Interceptor.attach(at(0x31BD150), { onEnter: function() { log(">> AddressablesModule.InitializeModule ENTER"); }, onLeave: function() { log("<< AddressablesModule.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to AddressablesModule: " + e); }
    try { Interceptor.attach(at(0x17D03EC), { onEnter: function() { log(">> Console.InitializeModule ENTER"); }, onLeave: function() { log("<< Console.InitializeModule LEAVE"); } }); } catch(e) { log("Failed to attach to Console: " + e); }

    // ── POISETTINGS AUTO-INJECTION (Blocker 2 bypass) ──
    let globalPoiSettings = null;
    let fakePoiSettings = null;
    try {
        // WebstuffClientModule.InitializeModule (0x2F897F4)
        Interceptor.attach(at(0x2F897F4), {
            onEnter: function(args) {
                try {
                    const self = args[0];
                    globalPoiSettings = self.add(0x58).readPointer();
                    log(">>> Extracted globalPoiSettings from WebstuffClientModule: " + globalPoiSettings);
                    
                    if (globalPoiSettings && !globalPoiSettings.isNull()) {
                        // Allocate and populate a fake settings block
                        fakePoiSettings = Memory.alloc(512);
                        for (let i = 0; i < 512; i++) {
                            fakePoiSettings.add(i).writeU8(0);
                        }
                        
                        // Copy the class pointer for type identification
                        const klass = globalPoiSettings.readPointer();
                        fakePoiSettings.writePointer(klass);
                        
                        // Populate field values
                        fakePoiSettings.add(0x40).writeFloat(1.0);  // nestOnMapScaleFactor
                        fakePoiSettings.add(0x44).writeFloat(100.0); // nestHideDistance
                        fakePoiSettings.add(0x48).writeFloat(50.0);  // nestColorGradingStartDistance
                        fakePoiSettings.add(0x58).writeInt(10);      // PoiModuleTickRate
                        fakePoiSettings.add(0x5C).writeInt(10);      // PoiModuleSpawnTickRate
                        fakePoiSettings.add(0x60).writeInt(15);      // s2CellLevel
                        fakePoiSettings.add(0x64).writeInt(30);      // DefaultIndicatorSize
                        fakePoiSettings.add(0x68).writeInt(5);       // destroyDelayTime
                        fakePoiSettings.add(0x6C).writeInt(60);      // BigIndicatorSize
                        fakePoiSettings.add(0x70).writeFloat(50.0);  // AllowRelocateQuestMinDistance
                        fakePoiSettings.add(0x80).writeFloat(100.0); // NestLoopSFXMaxDistance
                        fakePoiSettings.add(0xA0).writeFloat(1.0);   // ActiveNestOutlineWidth
                        fakePoiSettings.add(0xA4).writeFloat(1.0);   // InactiveNestOutlineWidth
                        fakePoiSettings.add(0xB8).writeFloat(1.0);   // ActiveHerbOutlineWidth
                        fakePoiSettings.add(0xBC).writeFloat(1.0);   // InactiveHerbOutlineWidth
                        fakePoiSettings.add(0xD8).writeFloat(100.0); // herbHideDistance
                        fakePoiSettings.add(0xDC).writeFloat(1.0);   // herbsOnMapScaleFactor
                        fakePoiSettings.add(0xF0).writeFloat(1.0);   // ActiveMonsterOutlineWidth
                        fakePoiSettings.add(0xF4).writeFloat(1.0);   // InactiveMonsterOutlineWidth
                        fakePoiSettings.add(0x104).writeFloat(100.0); // monsterUndiscoveredDistance
                        fakePoiSettings.add(0x108).writeFloat(100.0); // monsterDiscoveredDistance
                        fakePoiSettings.add(0x120).writeFloat(1.0);   // monsterOnMapScaleFactor
                        fakePoiSettings.add(0x124).writeFloat(1.0);   // monsterOnMapDifficultyIconScaleFactor
                        fakePoiSettings.add(0x128).writeFloat(100.0); // monsterHideDistance
                        fakePoiSettings.add(0x13C).writeFloat(1.0);   // InactiveQuestOutlineWidth
                        fakePoiSettings.add(0x140).writeFloat(1.0);   // ActiveQuestOutlineWidth
                        fakePoiSettings.add(0x144).writeFloat(1.0);   // questOnMapScaleFactor
                        fakePoiSettings.add(0x164).writeFloat(100.0); // questOnMapHideDistance
                        fakePoiSettings.add(0x168).writeFloat(100.0); // HuntHideDistance
                        fakePoiSettings.add(0x18C).writeFloat(1.0);   // PlayerWeightMultiplier
                        fakePoiSettings.add(0x190).writeFloat(1.0);   // NestAndQuestPointsWeightMultiplier
                        fakePoiSettings.add(0x194).writeFloat(1.0);   // MultipleSpawnPenaltyWeightMultiplier
                        
                        log(">>> Created and populated fakePoiSettings at: " + fakePoiSettings);
                    }
                } catch (e) {
                    log("Failed to extract globalPoiSettings: " + e);
                }
            }
        });
    } catch (e) {
        log("Failed to hook WebstuffClientModule to extract settings: " + e);
    }

    let isInPoiInit = false;
    try {
        // PoiModule.InitializeModule (0x17B34B8)
        Interceptor.attach(at(0x17B34B8), {
            onEnter: function(args) {
                isInPoiInit = true;
                try {
                    const self = args[0];
                    if (fakePoiSettings) {
                        self.add(0x60).writePointer(fakePoiSettings);
                        log(">>> Dynamically injected populated fakePoiSettings into PoiModule._settings field (0x60)!");
                    }
                } catch (e) {
                    log("Failed to inject fakePoiSettings: " + e);
                }
            },
            onLeave: function(retval) {
                isInPoiInit = false;
                log("<< PoiModule.InitializeModule LEAVE (completed) — Instances+Locations now allocated");
            }
        });
    } catch (e) {
        log("Failed to hook PoiModule to inject settings: " + e);
    }

    // ── BEHAVIURGRAPHSETTINGS AUTO-INJECTION (READY-TO-ENABLE FALLBACK — DISABLED BY DEFAULT) ──
    // Modeled on the PoiSettings injection above. DO NOT enable by default: try the plain un-bypass FIRST.
    // Enable this ONLY if the on-device boot NREs on a null `_settings` (the BehaviourGraphModule diagnostic
    // above logs `_settings (BehaviurGraphSettings) = NULL`). BehaviurGraphSettings is DI-bound
    // (dump.cs ~449889 `BindInstance<BehaviurGraphSettings>`, sourced from BehaviourGraphInstaller.settings
    // @0x20), so `_settings` may already resolve correctly and this block may never be needed.
    //
    // REAL OFFSETS (verified from dump.cs — NOT the Poi 0x60):
    //   BehaviourGraphModule._settings (BehaviurGraphSettings)   @ 0x18   <-- inject target
    //   BehaviourGraphModule.<Initialized>k__BackingField (bool) @ 0xE8
    // BehaviurGraphSettings (ScriptableObject, dump.cs ~635147) has NO scalar fields to populate — all 8
    // fields are object refs: standardFightGraph@0x18, standardNestGraph@0x20, standardSummonedFightGraph@0x28,
    // standardPresentationGraph@0x30, PreFightGraphs@0x38, PostFightGraphs@0x40, PreNestGraphs@0x48,
    // PostNestGraphs@0x50. We cannot fabricate real BehaviourGraph/InjectGraphsStorage assets, so the fake is
    // a zeroed, correctly-typed block (klass ptr at object[0], all 8 fields left NULL). That is enough to get
    // past a bare `_settings` null-deref in InitializeModule, but any path that actually STARTS a graph will
    // still need the real assets — full combat/tutorial playthrough is a FOLLOW-UP milestone, not this round.
    // TODO(orchestrator): if this fallback runs but a later StartFightGraph/StartQuestGraph NREs on a null
    //   graph field, the real fix is DI (ensure BehaviourGraphInstaller.settings is populated) — not a fake.
    /*
    let fakeBGSettings = null;
    try {
        Interceptor.attach(at(0x31972F8), {            // BehaviourGraphModule.InitializeModule
            onEnter: function(args) {
                try {
                    const self = args[0];
                    if (!self.add(0x18).readPointer().isNull()) {   // _settings @ 0x18 already present
                        log(">>> BehaviourGraphModule._settings already non-null — skipping injection");
                        return;
                    }
                    if (!fakeBGSettings) {
                        // object[0] == Il2CppClass*; reuse the getClass() helper defined below in this file.
                        const klass = getClass("Assembly-CSharp",
                            "WitcherWorld.Modules.Graphs.Behaviour", "BehaviurGraphSettings");
                        if (!klass || klass.isNull()) { log("BG inject: could not resolve BehaviurGraphSettings klass"); return; }
                        fakeBGSettings = Memory.alloc(256);
                        for (let i = 0; i < 256; i++) fakeBGSettings.add(i).writeU8(0);
                        fakeBGSettings.writePointer(klass);         // Il2CppObject header: klass pointer
                        // all 8 settings fields (0x18..0x50) intentionally left NULL — no real graph assets.
                        log(">>> Created zeroed fakeBGSettings (klass=" + klass + ") at " + fakeBGSettings);
                    }
                    self.add(0x18).writePointer(fakeBGSettings);    // BehaviourGraphModule._settings @ 0x18
                    log(">>> Injected fakeBGSettings into BehaviourGraphModule._settings (0x18)");
                } catch (e) { log("Failed to inject fakeBGSettings: " + e); }
            }
        });
    } catch (e) {
        log("Failed to hook BehaviourGraphModule to inject settings: " + e);
    }
    */

    // ── GENERIC INSTANTIATE NULL BYPASS ──
    let fakeGameObject = null;
    let fakeDespawnFxInstance = null;

    // Resolve an il2cpp image by assembly name via DOMAIN ENUMERATION. This is far more reliable than
    // il2cpp_domain_assembly_open(NULL, name), which returned a WRONG 49-class image for "Assembly-CSharp"
    // (so DespawnFX could not be found -> PoiModule.InitializeModule NRE'd at job 180/200).
    function getImageByName(targetName) {
        try {
            const il2cpp = Process.getModuleByName("libil2cpp.so");
            const domain_get = new NativeFunction(il2cpp.findExportByName("il2cpp_domain_get"), 'pointer', []);
            const get_assemblies = new NativeFunction(il2cpp.findExportByName("il2cpp_domain_get_assemblies"), 'pointer', ['pointer', 'pointer']);
            const assembly_get_image = new NativeFunction(il2cpp.findExportByName("il2cpp_assembly_get_image"), 'pointer', ['pointer']);
            const image_get_name = new NativeFunction(il2cpp.findExportByName("il2cpp_image_get_name"), 'pointer', ['pointer']);
            const domain = domain_get();
            const countPtr = Memory.alloc(Process.pointerSize);
            countPtr.writePointer(ptr(0));
            const assemblies = get_assemblies(domain, countPtr);
            const count = countPtr.readU32();
            for (let i = 0; i < count; i++) {
                const asm = assemblies.add(i * Process.pointerSize).readPointer();
                if (asm.isNull()) continue;
                const img = assembly_get_image(asm);
                if (img.isNull()) continue;
                const nm = image_get_name(img).readUtf8String();
                if (nm === targetName || nm === targetName + ".dll") return img;
            }
        } catch (e) { log("getImageByName(" + targetName + ") failed: " + e); }
        return null;
    }

    function getClass(assemblyName, namespace, className) {
        try {
            const il2cpp = Process.getModuleByName("libil2cpp.so");
            const assembly_open = il2cpp.findExportByName("il2cpp_domain_assembly_open");
            const assembly_get_image = new NativeFunction(il2cpp.findExportByName("il2cpp_assembly_get_image"), 'pointer', ['pointer']);
            const class_from_name = new NativeFunction(il2cpp.findExportByName("il2cpp_class_from_name"), 'pointer', ['pointer', 'pointer', 'pointer']);

            // Preferred: enumerate the domain for the real image (fixes the 49-class wrong-image bug).
            let image = getImageByName(assemblyName);
            if (!image || image.isNull()) {
                const namePtr = Memory.allocUtf8String(assemblyName);
                let assembly = null;
                // Try 2-parameter signature with NULL domain first (safe on newer and older)
                try {
                    const assembly_open_2 = new NativeFunction(assembly_open, 'pointer', ['pointer', 'pointer']);
                    assembly = assembly_open_2(ptr(0), namePtr);
                } catch(e) {
                    const assembly_open_1 = new NativeFunction(assembly_open, 'pointer', ['pointer']);
                    assembly = assembly_open_1(namePtr);
                }
                if (!assembly || assembly.isNull()) {
                    const nameWithDllPtr = Memory.allocUtf8String(assemblyName + ".dll");
                    try {
                        const assembly_open_2 = new NativeFunction(assembly_open, 'pointer', ['pointer', 'pointer']);
                        assembly = assembly_open_2(ptr(0), nameWithDllPtr);
                    } catch(e) {
                        const assembly_open_1 = new NativeFunction(assembly_open, 'pointer', ['pointer']);
                        assembly = assembly_open_1(nameWithDllPtr);
                    }
                }
                log("getClass (" + className + ") assembly (fallback): " + assembly);
                if (!assembly || assembly.isNull()) return null;
                image = assembly_get_image(assembly);
            }
            log("getClass (" + className + ") image: " + image);
            if (!image || image.isNull()) return null;
            
            const nsPtr = Memory.allocUtf8String(namespace);
            const clsNamePtr = Memory.allocUtf8String(className);
            let klass = class_from_name(image, nsPtr, clsNamePtr);
            log("getClass (" + className + ") class: " + klass);
            
            if (klass.isNull()) {
                log(">>> class_from_name returned NULL. Searching image for matching classes...");
                try {
                    const get_class_count = new NativeFunction(il2cpp.findExportByName("il2cpp_image_get_class_count"), 'size_t', ['pointer']);
                    const get_class = new NativeFunction(il2cpp.findExportByName("il2cpp_image_get_class"), 'pointer', ['pointer', 'size_t']);
                    const get_class_name = new NativeFunction(il2cpp.findExportByName("il2cpp_class_get_name"), 'pointer', ['pointer']);
                    const get_class_ns = new NativeFunction(il2cpp.findExportByName("il2cpp_class_get_namespace"), 'pointer', ['pointer']);
                    
                    const count = get_class_count(image);
                    log("getClass image class count: " + count);
                    // NOTE: do NOT log("  Class " + i + ...) per class here. Emitting a Frida send() for
                    // every class in Assembly-CSharp (tens of thousands) over USB is what froze boot at
                    // 90% "Loading Points of Interest" (PoiModule.InitializeModule waiting on this scan).
                    for (let i = 0; i < count; i++) {
                        const cls = get_class(image, i);
                        if (cls.isNull()) continue;
                        const cName = get_class_name(cls).readUtf8String();
                        if (cName === className) {
                            klass = cls;
                            log(">>> Resolved class match (" + className + ") at index " + i + ": " + klass);
                            break;
                        }
                    }
                } catch(errSearch) {
                    log("Class search failed: " + errSearch);
                }
            }
            
            if (!klass.isNull()) return klass;
        } catch (e) {
            log("Failed in getClass (" + className + "): " + e + "\n" + new Error().stack);
        }
        return null;
    }

    function getFakeGameObject() {
        if (fakeGameObject) return fakeGameObject;
        try {
            const il2cpp = Process.getModuleByName("libil2cpp.so");
            const il2cpp_object_new = new NativeFunction(il2cpp.findExportByName("il2cpp_object_new"), 'pointer', ['pointer']);
            const goClass = getClass("UnityEngine.CoreModule", "UnityEngine", "GameObject");
            if (!goClass) return null;
            
            fakeGameObject = il2cpp_object_new(goClass);
            const goCtor = new NativeFunction(at(0x23e02d8), 'void', ['pointer']);
            goCtor(fakeGameObject);
            
            log(">>> Created real dummy GameObject: " + fakeGameObject);
            return fakeGameObject;
        } catch (e) {
            log("Failed to create fake GameObject: " + e + "\n" + new Error().stack);
            return null;
        }
    }

    function getFakeDespawnFX() {
        if (fakeDespawnFxInstance) return fakeDespawnFxInstance;
        try {
            const go = getFakeGameObject();
            if (!go) return null;
            
            const il2cpp = Process.getModuleByName("libil2cpp.so");
            const il2cpp_class_get_type = new NativeFunction(il2cpp.findExportByName("il2cpp_class_get_type"), 'pointer', ['pointer']);
            const il2cpp_type_get_object = new NativeFunction(il2cpp.findExportByName("il2cpp_type_get_object"), 'pointer', ['pointer']);
            // DespawnFX lives in Game.dll (TypeDefIndex 12285, image range 10273..15027), NOT Assembly-CSharp.
            // Querying the wrong image returned null -> a bare GameObject was pooled instead of a real
            // IMonoPoolable DespawnFX, which is what stalled PoiModule bring-up. (verified from dump image table)
            const despawnFxClass = getClass("Game", "WitcherWorld.Modules.POI", "DespawnFX");
            if (!despawnFxClass) return null;
            
            const despawnFxTypeStruct = il2cpp_class_get_type(despawnFxClass);
            const despawnFxType = il2cpp_type_get_object(despawnFxTypeStruct);
            
            const addComponent = new NativeFunction(at(0x23dfb0c), 'pointer', ['pointer', 'pointer']);
            fakeDespawnFxInstance = addComponent(go, despawnFxType);
            
            log(">>> Created real dummy DespawnFX component: " + fakeDespawnFxInstance);
            return fakeDespawnFxInstance;
        } catch (e) {
            log("Failed to create fake DespawnFX: " + e + "\n" + new Error().stack);
            return null;
        }
    }

    // ── GENERIC INSTANTIATE NULL BYPASS (REPLACE ROUTINES) ──
    try {
        const inst_1_orig = new NativeFunction(at(0x19efbb0), 'pointer', ['pointer', 'pointer']);
        Interceptor.replace(at(0x19efbb0), new NativeCallback(function(original, method) {
            if (original.isNull()) {
                log(">>> replaced Instantiate 0x19efbb0 called with NULL original!");
                log("Backtrace:\n" + Thread.backtrace(this.context, Backtracer.ACCURATE).map(DebugSymbol.fromAddress).join("\n"));
                const go = getFakeGameObject();
                const comp = getFakeDespawnFX();
                if (isInPoiInit) {
                    log(">>> Bypassing NULL Instantiate with fake DespawnFX component!");
                    return (!comp || comp.isNull()) ? go : comp;
                } else {
                    log(">>> Bypassing NULL Instantiate with fake GameObject!");
                    return go;
                }
            }
            return inst_1_orig(original, method);
        }, 'pointer', ['pointer', 'pointer']));
    } catch(e) { log("Failed to replace Instantiate 0x19efbb0: " + e); }

    try {
        const inst_2_orig = new NativeFunction(at(0x19efcd8), 'pointer', ['pointer', 'pointer', 'pointer']);
        Interceptor.replace(at(0x19efcd8), new NativeCallback(function(original, parent, method) {
            if (original.isNull()) {
                log(">>> replaced Instantiate 0x19efcd8 called with NULL original!");
                const go = getFakeGameObject();
                const comp = getFakeDespawnFX();
                if (isInPoiInit) {
                    log(">>> Bypassing NULL Instantiate with fake DespawnFX component!");
                    return (!comp || comp.isNull()) ? go : comp;
                } else {
                    log(">>> Bypassing NULL Instantiate with fake GameObject!");
                    return go;
                }
            }
            return inst_2_orig(original, parent, method);
        }, 'pointer', ['pointer', 'pointer', 'pointer']));
    } catch(e) { log("Failed to replace Instantiate 0x19efcd8: " + e); }

    // TRACES FOR TUTORIAL
    try { 
        Interceptor.attach(at(0x1F9A1B8), { 
            onEnter: function(args) { 
                var funcPtr = this.context.x8;
                var arg0 = this.context.x0;
                var arg1 = this.context.x1;
                log('=== CheckTutorial calling Virtual Method at: ' + funcPtr + ' with w1=' + arg1);
            }
        }); 
        log('CheckTutorial virtual call trace installed'); 
    } catch(e) { log('Failed to trace CheckTutorial virtual call: ' + e); }

    try { 
        Interceptor.attach(at(0x1789A88), { 
            onEnter: function(args) { 
                this.key = args[1].toInt32(); 
            }, 
            onLeave: function(retval) { 
                log('=== FactDatabaseModule.GetFact(' + this.key + ') -> ' + retval.toInt32()); 
            } 
        }); 
        log('FactDatabaseModule.GetFact trace installed'); 
    } catch(e) { log('Failed to trace GetFact: ' + e); }

    try { 
        Interceptor.attach(at(0x18A6D98), { 
            onEnter: function(args) { 
                log('=== StoryModule.GetAvailableQuestNodeIds ENTER'); 
            },
            onLeave: function(retval) {
                log('=== StoryModule.GetAvailableQuestNodeIds RETURNED: ' + retval);
                if (!retval.isNull()) {
                    var count = retval.add(0x20).readInt();
                    var lastIndex = retval.add(0x24).readInt();
                    log('  count: ' + count + ', lastIndex: ' + lastIndex);
                    var slots = retval.add(0x18).readPointer();
                    if (!slots.isNull()) {
                        var slotCount = slots.add(0x18).readInt();
                        log('  slots length: ' + slotCount);
                        for (var i = 0; i < lastIndex; i++) {
                            var valOffset = 0x20 + (i * 12) + 8;
                            var val = slots.add(valOffset).readInt();
                            log('  item ' + i + ': ' + val);
                        }
                    }
                }
            } 
        }); 
        log('StoryModule.GetAvailableQuestNodeIds trace installed'); 
    } catch(e) { log('Failed to trace GetAvailableQuestNodeIds: ' + e); }

    log("Boot + preloader hooks installed.");
}

// The dead prod server IP both gatekeeper + game-server resolve to.
const DEAD_IP = "34.107.152.195";

// libc connect() trace + redirect. Rewrites the dead game-server (:80) to our TCP server via the
// adb-reverse loopback tunnel. Independent of il2cpp (works even before it loads).
function hookConnect() {
    let connectPtr = null;
    try { connectPtr = Process.getModuleByName("libc.so").findExportByName("connect"); } catch (e) {}
    if (!connectPtr) { log("libc connect not found"); return; }
    Interceptor.attach(connectPtr, { onEnter: function (args) {
        try {
            const sa = args[1];
            const family = sa.readU16();
            if (family === 2) { // AF_INET
                const port = (sa.add(2).readU8() << 8) | sa.add(3).readU8();
                const ip = sa.add(4).readU8() + "." + sa.add(5).readU8() + "." + sa.add(6).readU8() + "." + sa.add(7).readU8();
                if (REDIRECT && ip === DEAD_IP && port === 80) {
                    // -> 127.0.0.1:PORT (adb reverse tcp:PORT -> PC). Rewrite port + IPv4 in sockaddr_in.
                    sa.add(2).writeU8((PORT >> 8) & 0xff);
                    sa.add(3).writeU8(PORT & 0xff);
                    sa.add(4).writeU8(127); sa.add(5).writeU8(0); sa.add(6).writeU8(0); sa.add(7).writeU8(1);
                    log("connect() " + ip + ":" + port + "  REDIRECTED -> 127.0.0.1:" + PORT);
                } else if (port === 8080) {
                    sa.add(4).writeU8(127); sa.add(5).writeU8(0); sa.add(6).writeU8(0); sa.add(7).writeU8(1);
                    log("connect() -> IPv4 8080 REDIRECTED to 127.0.0.1:8080");
                } else if (port === 443) {
                    // Force HTTPS connection to fail instantly
                    sa.add(2).writeU8(0); sa.add(3).writeU8(1); // port 1
                    sa.add(4).writeU8(127); sa.add(5).writeU8(0); sa.add(6).writeU8(0); sa.add(7).writeU8(1);
                    log("connect() -> IPv4 443 FORCED TO FAIL!");
                } else {
                    log("connect() -> " + ip + ":" + port);
                }
            } else if (family === 10) { // AF_INET6
                const port = (sa.add(2).readU8() << 8) | sa.add(3).readU8();
                if (port === 8080) {
                    for (let i = 0; i < 10; i++) sa.add(8 + i).writeU8(0);
                    sa.add(18).writeU8(0xff); sa.add(19).writeU8(0xff);
                    sa.add(20).writeU8(127); sa.add(21).writeU8(0); sa.add(22).writeU8(0); sa.add(23).writeU8(1);
                    log("connect() -> IPv6 8080 REDIRECTED to ::ffff:127.0.0.1:8080");
                } else if (port === 443) {
                    sa.add(2).writeU8(0); sa.add(3).writeU8(1); // port 1
                    for (let i = 0; i < 15; i++) sa.add(8 + i).writeU8(0);
                    sa.add(8 + 15).writeU8(1); // ::1
                    log("connect() -> IPv6 443 FORCED TO FAIL!");
                } else {
                    log("connect() -> [IPv6] port " + port);
                }
            }
        } catch (e) {}
    }});
    log("libc connect() trace+redirect installed.");

    
}

function hookDlopen() {
    let android_dlopen_ext = null, dlopen = null;
    try {
        const libdl = Process.getModuleByName("libdl.so");
        dlopen = libdl.findExportByName("dlopen");
        android_dlopen_ext = libdl.findExportByName("android_dlopen_ext");
    } catch (e) {}
    function intercept(name, target) {
        if (!target) return;
        Interceptor.attach(target, {
            onEnter: function (a) { if (!a[0].isNull()) this.path = a[0].readUtf8String(); },
            onLeave: function () {
                if (this.path && this.path.indexOf("libil2cpp.so") !== -1) {
                    log("dlopen(libil2cpp.so) via " + name);
                    installIl2cpp();
                }
            }
        });
    }
    try { 
        Interceptor.attach(at(0x1F9A1B8), { 
            onEnter: function(args) { 
                var funcPtr = this.context.x8;
                var arg0 = this.context.x0;
                var arg1 = this.context.x1;
                log('=== CheckTutorial calling Virtual Method at: ' + funcPtr + ' with w1=' + arg1);
            }
        }); 
        log('CheckTutorial virtual call trace installed'); 
    } catch(e) { log('Failed to trace CheckTutorial virtual call: ' + e); }

    try { 
        Interceptor.attach(at(0x1789A88), { 
            onEnter: function(args) { 
                this.key = args[1].toInt32(); 
            }, 
            onLeave: function(retval) { 
                log('=== FactDatabaseModule.GetFact(' + this.key + ') -> ' + retval.toInt32()); 
            } 
        }); 
        log('FactDatabaseModule.GetFact trace installed'); 
    } catch(e) { log('Failed to trace GetFact: ' + e); }

    try { 
        Interceptor.attach(at(0x18A6D98), { 
            onEnter: function(args) { 
                log('=== StoryModule.GetAvailableQuestNodeIds ENTER'); 
            } 
        }); 
        log('StoryModule.GetAvailableQuestNodeIds trace installed'); 
    } catch(e) { log('Failed to trace GetAvailableQuestNodeIds: ' + e); }
    intercept("dlopen", dlopen);
    intercept("android_dlopen_ext", android_dlopen_ext);
}

log("script loaded. REDIRECT=" + REDIRECT);
hookConnect();
hookDlopen();
installIl2cpp();                     // in case libil2cpp.so is already mapped
let tries = 0;
const poll = setInterval(function () {
    tries++;
    if (installed || tries > 120) { clearInterval(poll); if (!installed) log("giving up il2cpp install after " + tries + " polls"); return; }
    installIl2cpp();
}, 250);

