"use strict";
window.MSR_TESTERS = ({ L, api, notice, busy, clearDraft }) => {
  const $ = id => document.getElementById(id), m = L.m, text = L.text;
  let data = null, selection = null, lastTrigger = null, page = 0, blocked = false, enrollmentBlocked = false;
  const states = { pending:m("Oczekuje na zatwierdzenie"), approved:m("Dostęp aktywny"),
    expired:m("Dostęp wygasł"), revoked:m("Dostęp cofnięty"), "request-expired":m("Kod wygasł") };
  const actions = {approve:m("Zatwierdź kod"), renew:m("Ustaw czas dostępu"), rebind:m("Zmień przypisanie"), revoke:m("Cofnij dostęp")};
  const stamp = n => n ? L.date(n * 1000) : "—";
  function node(tag, value, cls) { const n=document.createElement(tag); if(value!=null)text(n,value); if(cls)n.className=cls; return n; }
  function button(label, click, cls="secondary") {const b=node("button",label,cls);b.type="button";b.addEventListener("click",click);return b;}
  function name(id) {
    const p=data?.profiles?.find(p=>p.id===id);
    return p ? (p.label || p.name || String(m("Profil bez nazwy"))) + " · " + id : id || String(m("Nieprzypisany"));
  }
  function serverNow() { return data.state.observedAt + Math.max(0, (Date.now()-data.receivedAt)/1000); }
  function effective(e) {
    const now=serverNow();
    return e.status==="approved" && e.expiresAt<=now ? "expired" : e.status==="pending" && e.pendingUntil<=now ? "request-expired" : e.status;
  }
  function render() {
    $("testers-enabled").hidden=!data?.available;
    $("testers-unavailable").hidden=!!data?.available;
    if(!data?.available){text($("testers-unavailable"),m("Transport instalacji jest wyłączony. Włącz go w konfiguracji serwera przed przyjmowaniem testerów."));return;}
    const s=data.state, open=s.enrollmentOpen && s.enrollmentUntil>serverNow() && s.enrollmentRemaining>0;
    text($("enrollment-state"),open?m("Rejestracja otwarta"):m("Rejestracja zamknięta"));
    text($("enrollment-detail"),L.join(m("Miejsca: "),open?s.enrollmentRemaining:0," · ",m("Do: "),stamp(s.enrollmentUntil)));
    $("enrollment-close").disabled=!open||enrollmentBlocked;
    $("enrollment-form").querySelector("button[type=submit]").disabled=enrollmentBlocked;
    text($("testers-observed"),L.join(m("Odczyt: "),stamp(s.observedAt),m(" · odśwież, aby pobrać nowe kody")));
    const q=$("tester-search").value.trim().toLowerCase(), filter=$("tester-filter").value;
    const rows=s.entries.filter(e=>(filter==="all" || effective(e)===filter) && (e.code+" "+name(e.profile)).toLowerCase().includes(q));
    page=Math.min(page,Math.max(0,Math.ceil(rows.length/20)-1));
    $("tester-rows").replaceChildren();
    for(const e of rows.slice(page*20,page*20+20)) {
      const status=effective(e), tr=node("tr");
      tr.append(node("td",e.code,"tester-code"),node("td",states[status]),node("td",name(e.profile),"tester-profile"),
        node("td",stamp(status==="pending"||status==="request-expired"?e.pendingUntil:e.expiresAt)));
      const controls=node("td",null,"tester-actions");
      const available=status==="pending"?["approve","revoke"]:["approved","expired"].includes(status)?["renew","rebind","revoke"]:[];
      for(const action of available)controls.append(button(actions[action],ev=>openDialog(action,e,ev.currentTarget),action==="revoke"?"danger secondary":"secondary"));
      if(!available.length)controls.append(node("span",status==="request-expired"?m("Otwórz rejestrację i ponów zgłoszenie w LAB."):m("Dostęp cofnięty. Tego kodu nie można ponownie zatwierdzić."),"hint"));
      tr.append(controls);$("tester-rows").append(tr);
    }
    $("tester-empty").hidden=rows.length>0;
    text($("tester-count"),L.join(m("Wyniki: "),rows.length," · ",page+1," / ",Math.max(1,Math.ceil(rows.length/20))));
    $("tester-prev").disabled=page===0; $("tester-next").disabled=(page+1)*20>=rows.length;
  }
  async function load() {
    if($("tester-dialog").open)throw new L.Error(m("Zamknij formularz przed odświeżeniem listy."));
    try {const next=await api("transport");data={...next,receivedAt:Date.now()};enrollmentBlocked=false;render();}
    catch(e) {data=null;$("testers-enabled").hidden=true;$("testers-unavailable").hidden=false;text($("testers-unavailable"),m("Odczyt rejestru nie powiódł się. Nie wykonuj zmian na podstawie nieaktualnej listy."));throw e;}
  }
  function seconds() {return Number($("tester-duration").value)*Number($("tester-unit").value);}
  function openDialog(action, entry, trigger) {
    if(!data?.available)return;
    selection={action,entry:structuredClone(entry),revision:data.state.revision};
    lastTrigger=trigger;blocked=false;
    $("tester-form").reset();$("tester-error").hidden=true;$("tester-submit").disabled=false;
    text($("tester-dialog-title"),actions[action]); text($("tester-target"),entry.code+" · "+name(entry.profile));
    $("tester-profile-fields").hidden=!["approve","rebind"].includes(action);
    $("tester-duration-fields").hidden=!["approve","renew"].includes(action);
    $("tester-typed-label").hidden=!["rebind","revoke"].includes(action);
    $("tester-confirm-code").required=["rebind","revoke"].includes(action);
    $("tester-duration").value=action==="renew"?Math.max(1,Math.ceil((entry.expiresAt-serverNow())/86400)):30;
    $("tester-unit").value="86400";$("tester-mode").value="new";
    $("tester-profile").replaceChildren(L.option(m("Wybierz profil…"),""),...(data.profiles||[]).filter(p=>action!=="rebind"||p.id!==entry.profile)
      .map(p=>L.option(name(p.id),p.id)));
    text($("tester-submit"),actions[action]);
    preview();$("tester-dialog").showModal();$("tester-dialog-title").focus();
  }
  function preview() {
    if(!selection)return;
    const {action,entry}=selection, binding=["approve","rebind"].includes(action), existing=binding&&$("tester-mode").value==="existing";
    $("tester-existing-label").hidden=!existing;$("tester-profile").required=existing;
    const dest=existing?$("tester-profile").value:null, count=data.state.entries.filter(e=>e.code!==entry.code&&e.profile===dest&&["approved","expired"].includes(effective(e))).length;
    const pieces=[L.join(m("Kod instalacji: "),entry.code)];
    if(binding)pieces.push(L.join(m("Obecny profil: "),name(entry.profile)),L.join(m("Nowy profil: "),existing?name(dest):m("Nowy osobny profil — zapis powstanie przy pierwszym połączeniu.")));
    if(existing)pieces.push(L.join(m("Inne przypisania tego profilu: "),count,m(". Wybrany telefon uzyska dostęp do jego postępu.")));
    if(["approve","renew"].includes(action)){
      pieces.push(L.join(m("Obecny termin: "),stamp(entry.expiresAt)),L.join(m("Nowy termin (od teraz): "),stamp(Math.floor(serverNow()+seconds()))));
      if(action==="renew"&&serverNow()+seconds()<entry.expiresAt)pieces.push(m("Uwaga: ta zmiana skróci obecny dostęp."));
    }
    if(action==="rebind")pieces.push(m("Telefon zostanie rozłączony. Uruchom LAB ponownie. Zapisy obu profili i termin dostępu pozostają."));
    if(action==="revoke")pieces.push(m("Telefon utraci dostęp i zostanie rozłączony. Zapis gracza pozostanie. Cofniętego dostępu nie można odnowić."));
    $("tester-preview").replaceChildren(...pieces.map(p=>node("p",p)));
  }
  const errors={
    "Installation state changed. Refresh and review before saving.":m("Stan instalacji zmienił się. Zamknij formularz, odśwież listę i sprawdź wybór ponownie."),
    "The pairing request expired or is no longer pending.":m("Kod wygasł albo został już obsłużony. Odśwież listę."),
    "Choose a different profile.":m("Wybierz inny profil."),
    "Only approved or expired access can be changed. Revoked access stays revoked.":m("Cofniętego dostępu nie można odnowić."),
  };
  $("tester-form").addEventListener("submit",async ev=>{
    ev.preventDefault(); if(blocked||!selection||!$("tester-form").reportValidity())return;
    const {action,entry,revision}=selection, typed=["rebind","revoke"].includes(action);
    if(typed&&$("tester-confirm-code").value.trim().toUpperCase()!==entry.code){text($("tester-error"),m("Wpisz dokładny kod wybranej instalacji."));$("tester-error").hidden=false;return;}
    const body={revision,action,code:entry.code,confirm:entry.code};
    if(["approve","rebind"].includes(action)){body.newProfile=$("tester-mode").value==="new";if(!body.newProfile)body.profile=$("tester-profile").value;}
    if(["approve","renew"].includes(action)){
      body.seconds=seconds();
      if(!Number.isInteger(body.seconds)||body.seconds<60||body.seconds>31536000){text($("tester-error"),m("Wybierz czas od 1 minuty do 365 dni."));$("tester-error").hidden=false;return;}
    }
    await busy($("tester-form"),async()=>{
      try {
        const result=await api("transport",{method:"POST",body:JSON.stringify(body)});
        const next=await api("transport"), expected=result.state.entries.find(e=>e.code===entry.code), actual=next.state?.entries.find(e=>e.code===entry.code);
        if(!actual||JSON.stringify(actual)!==JSON.stringify(expected))throw new L.Error(m("Odczyt po zapisie nie potwierdził stanu — sprawdź historię."));
        data={...next,receivedAt:Date.now()};$("tester-dialog").close();render();
        notice(L.join(m("Zapisano")," · ",entry.code," · ",actions[action],m(". Potwierdzenie: "),result.receipt.id));
      }catch(e){blocked=true;$("tester-error").hidden=false;text($("tester-error"),L.join(errors[e.message]||L.errorMessage(e)," ",m("Sprawdź historię i odśwież stan przed kolejną zmianą.")));}
    });
    if(blocked){$("tester-submit").disabled=true;$("tester-error").focus();}
  });
  for(const id of ["tester-mode","tester-profile","tester-duration","tester-unit"])$(id).addEventListener("input",preview);
  $("tester-dialog-close").addEventListener("click",()=>$("tester-dialog").close());
  $("tester-dialog").addEventListener("cancel",ev=>{if($("tester-form").getAttribute("aria-busy")==="true")ev.preventDefault();});
  $("tester-dialog").addEventListener("close",()=>{selection=null;clearDraft("tester-form");if(lastTrigger?.isConnected)lastTrigger.focus();else $("tester-search").focus();});
  for(const id of ["tester-search","tester-filter"])$(id).addEventListener("input",()=>{page=0;render();});
  $("tester-prev").addEventListener("click",()=>{page--;render();});$("tester-next").addEventListener("click",()=>{page++;render();});
  async function enrollment(action) {
    if(!data?.available||enrollmentBlocked)return;
    const body={revision:data.state.revision,action,confirm:"enrollment"};
    if(action==="open"){body.seconds=Number($("enrollment-minutes").value)*60;body.slots=Number($("enrollment-slots").value);}
    await busy($("enrollment-form"),async()=>{
      try {
        const result=await api("transport",{method:"POST",body:JSON.stringify(body)});
        await load();
        if(data.state.revision!==result.state.revision||data.state.enrollmentUntil!==result.state.enrollmentUntil||data.state.enrollmentRemaining!==result.state.enrollmentRemaining)throw new L.Error(m("Odczyt po zapisie nie potwierdził stanu — sprawdź historię."));
        clearDraft("enrollment-form");
        notice(L.join(action==="open"?m("Rejestracja otwarta"):m("Rejestracja zamknięta"),m(". Potwierdzenie: "),result.receipt.id));
      }catch(e){enrollmentBlocked=true;notice(L.join(errors[e.message]||L.errorMessage(e)," ",m("Sprawdź historię i odśwież stan przed kolejną zmianą.")),true);}
    });
    render();
    if(enrollmentBlocked)$("refresh").focus();
  }
  $("enrollment-form").addEventListener("submit",ev=>{ev.preventDefault();if($("enrollment-form").reportValidity())void enrollment("open");});
  $("enrollment-close").addEventListener("click",()=>void enrollment("close"));
  function receiptDetails(r) {
    const box=node("div",null,"tester-preview");
    let before,after;
    try{before=JSON.parse(r.before);after=r.after?JSON.parse(r.after):null;}catch{before=null;after=null;}
    const row=(label,a,b)=>box.append(node("p",L.join(label,": ",a??"—"," → ",b??"—")));
    if(!["transport-open","transport-close"].includes(r.action)){
      const a=before?.installation,b=after?.installation;
      row(m("Przypisany profil"),a?a.profile??m("Nieprzypisany"):null,b?b.profile??m("Nieprzypisany"):null);
      row(m("Stan dostępu"),a?states[a.status]||a.status:null,b?states[b.status]||b.status:null);
      row(m("Ważne do"),a?stamp(a.status==="pending"||a.status==="request-expired"?a.pendingUntil:a.expiresAt):null,b?stamp(b.status==="pending"||b.status==="request-expired"?b.pendingUntil:b.expiresAt):null);
    }else{
      row(m("Ważne do"),before?stamp(before.enrollmentUntil):null,after?stamp(after.enrollmentUntil):null);
      row(m("Liczba miejsc"),before?.enrollmentRemaining,after?.enrollmentRemaining);
    }
    if(!after)box.append(node("p",r.outcome==="refused"?m("Odmowa"):m("Stan serwera niepotwierdzony")));
    return box;
  }
  return {load,receiptDetails};
};
