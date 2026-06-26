# Homely Integration — Architecture

> Beste visning: GitHub, VS Code + Mermaid Preview, eller Obsidian.

---

## 1. Systemoversikt

```mermaid
flowchart TD
    HA["Home Assistant"]
    CFG["Config Entry\n(én per lokasjon)"]
    COORD["DataUpdateCoordinator\nasync_update_data()"]
    WS["HomelyWebSocket\n(python-homely SDK)"]
    API["Homely REST API"]
    CACHE["runtime_data.last_data\ncachet lokasjonspayload"]
    STORE["HA Storage\nhomely.{location_id}"]
    PLAT["Plattformer\nsensor · binary_sensor\nalarm_control_panel · lock"]
    WD["WS Watchdog\nhvert 1 min"]
    NET["internet_available event"]
    FB["6t fallback-poll\n(hvis poll_when_ws=False)"]

    HA --> CFG
    CFG --> COORD
    CFG --> WS
    COORD -->|"hvert scan_interval (std 180s)"| API
    API -->|"full payload"| CACHE
    WS -->|"sanntidshendelser"| CACHE
    CACHE --> PLAT
    COORD -->|"async_update_listeners()"| PLAT
    STORE -.->|"last på oppstart / rate-limit fallback"| CACHE
    CACHE -.->|"lagres etter vellykket poll"| STORE
    WD --> WS
    NET --> WS
    FB --> COORD
```

---

## 2. Oppstart (async_setup_entry)

```mermaid
flowchart TD
    START([async_setup_entry]) --> CREDS{Credentials\ntilgjengelig?}
    CREDS -->|Nei| AUTHFAIL([ConfigEntryAuthFailed])
    CREDS -->|Ja| FETCHTOKEN[POST /oauth/token\nbrukernavn + passord]
    FETCHTOKEN --> TOKENOK{Token OK?}
    TOKENOK -->|invalid_auth| AUTHFAIL
    TOKENOK -->|nettverksfeil| NOTREADY([ConfigEntryNotReady])
    TOKENOK -->|Ja| FETCHLOC[GET /location\nhent alle lokasjoner]
    FETCHLOC --> LOCOK{Lokasjoner OK?}
    LOCOK -->|Nei| NOTREADY
    LOCOK -->|Ja| RESOLVELOC{Finn riktig\nlocation_id}
    RESOLVELOC -->|Lagret location_id| MATCHLOC[Match mot liste]
    RESOLVELOC -->|Legacy home_id| INDEXLOC[Bruk indeks i liste]
    MATCHLOC --> LOCFOUND{Funnet?}
    INDEXLOC --> LOCFOUND
    LOCFOUND -->|Nei| NOTREADY
    LOCFOUND -->|Ja| LOADSTORE[Last fra HA Storage\nhomely.location_id]
    LOADSTORE --> FETCHDATA[GET /location/id\nInitiell datafetch]
    FETCHDATA --> DATASTATUS{HTTP status}
    DATASTATUS -->|200| SAVESTORE[Lagre til HA Storage]
    DATASTATUS -->|429 + stored data| USESTORED[Bruk lagret data\nsom startverdi]
    DATASTATUS -->|429 uten stored| EMPTYDATA[data = tom dict\nentiteter utilgjengelig]
    DATASTATUS -->|annen feil| NOTREADY
    SAVESTORE --> BUILDRUNTIME
    USESTORED --> BUILDRUNTIME
    EMPTYDATA --> BUILDRUNTIME

    BUILDRUNTIME["Bygg HomelyRuntimeData\n· coordinator\n· access_token, refresh_token, expires_at\n· location_id, partner_code\n· last_data\n· tracked_device_ids"]

    BUILDRUNTIME --> BUILDCOORD["DataUpdateCoordinator\nupdate_method = async_update_data\nupdate_interval = scan_interval"]
    BUILDCOORD --> WSENABLED{WebSocket\naktivert?}
    WSENABLED -->|Ja| WSINIT["async_init_websocket()\n(schedules as task)"]
    WSINIT --> REGLISTENERS["Registrer lyttere:\n· internet_available → reconnect\n· watchdog hvert 1 min\n· 6t fallback poll"]
    REGLISTENERS --> FIRSTREFRESH
    WSENABLED -->|Nei| FIRSTREFRESH

    FIRSTREFRESH[async_config_entry_first_refresh] --> PLATFORMS
    PLATFORMS["async_forward_entry_setups\nsensor · binary_sensor · alarm_control_panel · lock"]
    PLATFORMS --> PENDING{Ventende\nlokasjonsimporter?}
    PENDING -->|Ja| SCHEDIMPORT[Schedule config flow\nfor hver ny lokasjon]
    PENDING -->|Nei| DONE([Oppsett ferdig])
    SCHEDIMPORT --> DONE
```

---

## 3. Poll-syklusen (coordinator async_update_data)

```mermaid
flowchart TD
    TRIGGER([Poll trigget]) --> GETRD{runtime_data OK?}
    GETRD -->|Nei| FAIL([UpdateFailed])
    GETRD -->|Ja| TOKENEXP{Token utløpt?}

    TOKENEXP -->|Ja + WS aktiv\n+ skip_rest=True| BGREFRESH[Prøv refresh_token\nbakgrunnsoppdatering]
    BGREFRESH --> BGSYNC[Synk nytt token\ntil WS via sync_token]
    BGSYNC --> WSCHECK

    TOKENEXP -->|Ja + polling aktiv| REFRESH[fetch_refresh_token\nPOST /oauth/refresh]
    REFRESH --> REFOK{Success?}
    REFOK -->|Ja| UPDTOKEN[Oppdater runtime tokens\nSynk til WS]
    UPDTOKEN --> WSCHECK
    REFOK -->|Nei| FULLLOGIN1[Full innlogging\nPOST /oauth/token]
    FULLLOGIN1 --> LOGINOK1{Success?}
    LOGINOK1 -->|Ja| UPDTOKEN
    LOGINOK1 -->|invalid_auth| USECACHE1[_use_cached_data]
    LOGINOK1 -->|nettverksfeil| USECACHE1
    USECACHE1 --> FRESH1{Cache\nfrisk nok?}
    FRESH1 -->|Ja| RETCACHE([return last_data])
    FRESH1 -->|Nei - for gammel| FAIL

    TOKENEXP -->|Nei| WSCHECK{WS koblet\n+ poll_when_ws=False\n+ force_refresh=False?}
    WSCHECK -->|Ja - hopp over REST| RETLASTDATA([return last_data])
    WSCHECK -->|Nei| FETCHAPI[GET /location/id]

    FETCHAPI --> STATUS{HTTP\nstatus}
    STATUS -->|200 + data| PROCESSDATA
    STATUS -->|401 eller 403| RETRYCREDS[Full innlogging\n+ retry GET /location/id]
    RETRYCREDS --> RETRYOK{Success?}
    RETRYOK -->|Ja| PROCESSDATA
    RETRYOK -->|Nei| USECACHE2[_use_cached_data]
    USECACHE2 --> FRESH2{Frisk?}
    FRESH2 -->|Ja| RETCACHE
    FRESH2 -->|Nei| FAIL
    STATUS -->|429 500 502 503 504| TRANSIENT[Returner last_data\nhvis tilgjengelig]
    TRANSIENT --> FAIL

    PROCESSDATA[Preserve alarm state\nhvis mangler i ny data] --> UPDLAST[Oppdater runtime_data.last_data]
    UPDLAST --> TOPO[Sjekk device topology\nadded/removed devices?]
    TOPO --> TOPOCHG{Endring?}
    TOPOCHG -->|Ja| RELOAD[Schedule entry reload\nfor å oppdage nye enheter]
    TOPOCHG -->|Nei| SAVEDATA
    RELOAD --> SAVEDATA
    SAVEDATA[Lagre til HA Storage] --> DONE([return updated\nasync_update_listeners])
```

---

## 4. Token-refresh beslutningstre

```mermaid
flowchart TD
    CHECK{time.time >= expires_at?} -->|Nei| SKIP([Hopp over])
    CHECK -->|Ja| TRY1[POST /oauth/token/refresh\nmed refresh_token]
    TRY1 --> R1{Svar}
    R1 -->|200 + valid payload| UPDATE1["Sett:\naccess_token\nrefresh_token\nexpires_at = now + expires_in - 60\nSynk til WS"]
    R1 -->|Nettverksfeil| TRY2
    R1 -->|Ugyldig payload| TRY2
    R1 -->|invalid_refresh_token| TRY2
    TRY2[POST /oauth/token\nmed brukernavn+passord] --> R2{Svar}
    R2 -->|200 + valid| UPDATE2[Oppdater tokens\nSynk til WS]
    R2 -->|invalid_auth| CACHE2[Bruk cached data\nprøv igjen neste poll]
    R2 -->|Nettverksfeil| CACHE2
    CACHE2 --> STALE{For gammel\ncache?}
    STALE -->|Nei| RETCACHE([return last_data])
    STALE -->|Ja| FAIL([UpdateFailed])
```

---

## 5. WebSocket-livssyklus

```mermaid
flowchart TD
    INIT([async_init_websocket]) --> BUILD["HomelyWebSocket(\n  location_id\n  access_token\n  partner_code\n  on_data_update callback\n  status_update_callback\n)"]
    BUILD --> STORE_WS[runtime_data.websocket = ws]
    STORE_WS --> CONNECT[ws.connect]
    CONNECT --> CONNOK{Koblet?}
    CONNOK -->|Ja| LISTEN([Lytter på hendelser])
    CONNOK -->|Nei| LOGWARN[logger.info:\npolling fortsetter]
    LOGWARN --> RECONN_LOOP

    LISTEN --> RECV{Hendelse}
    RECV --> HANDLER[build_websocket_data_handler\non_websocket_data]
    HANDLER --> APPLY[apply_websocket_event_to_data]
    APPLY --> EVTYPE{event_type}

    EVTYPE -->|alarm-state-changed| ALARM_UPD["Skriv til:\nlast_data.alarmState\nlast_data.features.alarm\n.states.alarm.value\nasync_update_listeners()"]
    EVTYPE -->|device-state-changed| DEV_UPD[Finn device i last_data.devices\nApply changes in-place]
    DEV_UPD --> CHANGES{Endringer\napplied?}
    CHANGES -->|Ja| NOTIFY[async_update_listeners]
    CHANGES -->|Nei - lock partial| FORCE["force_api_refresh_once = True\ncoordinator.async_request_refresh()"]
    FORCE --> NOTIFY
    EVTYPE -->|connect / disconnect| IGNOREEVT[record event\ning listener-push]

    NOTIFY --> LISTEN

    LISTEN --> DISC{Kobling brutt?}
    DISC --> STATUS_CB[status_callback: Disconnected]
    STATUS_CB --> DEBOUNCE{Siste refresh\n< 30s siden?}
    DEBOUNCE -->|Nei| IMMEDIATEPOLL[coordinator.async_request_refresh\nnødpoll for fersk data]
    DEBOUNCE -->|Ja| SKIP_POLL[hopp over nødpoll]
    STATUS_CB --> RECONN_LOOP[ws.request_reconnect\ninnebygd reconnect-loop i SDK]
    RECONN_LOOP --> CONNECT

    subgraph WATCHDOG["Watchdog — hvert 1. minutt"]
        WDC{WS ikke koblet\n+ ingen aktiv reconnect-loop\n+ 90s debounce OK?}
        WDC -->|Ja| WDR[ws.request_reconnect\nrecord_websocket_watchdog_recovery]
        WDR --> WDWARN{>= 3 recoveries\niste 30 min?}
        WDWARN -->|Ja| WDLOG[logger.warning]
    end

    subgraph INTERNET["internet_available event (HA bus)"]
        INET[ws.request_reconnect\nreason=internet_available]
    end

    subgraph FALLBACK["6t fallback poll (poll_when_ws=False)"]
        FBC{WS koblet?}
        FBC -->|Ja| FBF["force_api_refresh_once = True\ncoordinator.async_request_refresh()"]
        FBC -->|Nei| FBSKIP[hopp over]
    end
```

---

## 6. WS-hendelse → cache → entiteter

```mermaid
flowchart LR
    RAW["Rå WS-hendelse\n{type, data/payload}"] --> NORM["_normalize_event_type()\nkebab-case"]

    NORM --> AT{alarm-state\n-changed?}
    AT -->|Ja| A1["payload.state / payload.alarmState"]
    A1 --> A2["last_data.alarmState = state"]
    A2 --> A3["last_data.features.alarm\n.states.alarm.value = state"]

    NORM --> DT{device-state\n-changed?}
    DT -->|Ja| D1["Finn device\nlast_data.devices\nwhere id == deviceId"]
    D1 --> D2["For hver change:\ndevice.features\n.{feature}.states\n.{stateName}.value = value"]

    A3 --> PUSH["coordinator\n.async_update_listeners()"]
    D2 --> PUSH

    PUSH --> E1["alarm_control_panel\nlast_data.alarmState"]
    PUSH --> E2["sensor / binary_sensor\ndevice.features.X\n.states.Y.value"]
    PUSH --> E3["lock\ndevice.features.lock\n.states.locked.value"]
```

**Alarmtilstand etter omstart:** WS sender bare *endringer* (ingen initiell snapshot), men
`alarmState` persisteres til `Store` (`.storage/homely.{location_id}`) hver gang en
`alarm-state-changed` skrives. Ved oppstart laster setup denne lagrede `last_data`, så
`HomelyAlarmPanel.alarm_state` viser **siste kjente status med en gang**. Den er bare `unknown`
ved aller første oppsett uten lagret data — da fylles den på første `alarm-state-changed`.
Endres alarmen mens HA er av, vises gammel verdi til neste event korrigerer den. Verdien må
finnes i `STATE_MAP` (`DISARMED`, `ARMED_*`, `*_PENDING`, `TRIGGERED`, `BREACHED`), ellers blir
den `unknown` og logges som `Unknown alarm state from API`.

---

## 6b. WebSocket-only modus (REST-polling nede)

**Bakgrunn (hvorfor):** Homelys `/home/{locationId}`-endepunkt er for tiden ødelagt — det
svarer med HTTP **439** i stedet for lokasjonspayloaden. Dette endepunktet er eneste kilde til
full enhets-/batteritilstand, så mens det er nede kan vi ikke polle for det. `439` er ikke en
standard HTTP-kode og ligger ikke i `_TRANSIENT_HTTP_STATUS` (`{429, 500, 502, 503, 504}`), så
den behandles som en vanlig poll-feil → cached data / WS-only i stedet for retry. WS leverer
fortsatt live endringer (`alarm-state-changed`, `device-state-changed`), så integrasjonen kjører
videre på WS alene fremfor å dø helt.

Når `/home`-pollen feiler men WS er tilkoblet kjører integrasjonen videre på WS alene
(`runtime_data.api_available = False`). Entiteter som bare lever på polldata skal da ikke
vise stale/falske verdier:

- **Live update connection status** (`HomelyWebSocketStatusSensor`): `available` er alltid
  `True` (rapporterer WS-helse uavhengig av poll) og er nå `entity_registry_enabled_default = True`,
  så den er synlig som standard.
- **Battery problem** (`HomelyAllBatteriesHealthySensor`): batteridata bæres kun av REST-pollen,
  så `available` gates på `api_available` via `api_available_getter`. Når polling er nede blir den
  *utilgjengelig* i stedet for å rapportere falsk «all healthy». Per-enhet batterisensorer blir
  ikke opprettet uten polldata (tom `{}`-seed → ingen `devices`).

---

## 7. Datamodell (HomelyRuntimeData)

```mermaid
flowchart TD
    subgraph RD["HomelyRuntimeData (per config entry)"]
        T["Tokens\naccess_token · refresh_token · expires_at"]
        L["Lokasjon\nlocation_id · partner_code"]
        LD["last_data: dict\nFull lokasjonspayload fra API"]
        WO["websocket: HomelyWebSocket | None"]
        WS2["WS-state\nws_status · ws_status_reason\nlast_disconnect_reason"]
        TM["Tidsstempler (monotonic)\nlast_successful_poll\nlast_data_activity\nlast_websocket_event"]
        FL["Flagg\napi_available · force_api_refresh_once\ntopology_reload_pending"]
        DV["tracked_device_ids: set[str]"]
        CO["coordinator: DataUpdateCoordinator"]
    end

    subgraph LD_SHAPE["last_data — struktur fra Homely API"]
        ROOT["locationId · name\nalarmState  ← top-level (write-through)"]
        FEAT["features:\n  alarm:\n    states:\n      alarm: {value: ARMED|DISARMED|...}"]
        DEVS["devices: [\n  {\n    id · name\n    features: {\n      alarm:       {states: {alarm: {value}}}\n      lock:        {states: {locked: {value}}}\n      temperature: {states: {temperature: {value}}}\n      humidity:    {states: {humidity: {value}}}\n      ... (auto-discovert via sensors/discover.py)\n    }\n  }\n]"]
    end

    LD --> ROOT
    LD --> FEAT
    LD --> DEVS
```

---

## 8. Feilhåndtering og fallback-hierarki

```mermaid
flowchart TD
    ERR([Feil oppstår]) --> TYPE{Feiltype}

    TYPE -->|Token utløpt| TF1[Prøv refresh_token]
    TF1 --> TF2{OK?}
    TF2 -->|Ja| CONTINUE([Fortsett])
    TF2 -->|Nei| TF3[Full innlogging]
    TF3 --> TF4{OK?}
    TF4 -->|Ja| CONTINUE
    TF4 -->|Nei| TF5[Bruk cached data]
    TF5 --> TF6{Cache frisk?}
    TF6 -->|Ja| RETCACHE([return last_data])
    TF6 -->|Nei| FAIL1([UpdateFailed\nentiteter utilgjengelig])

    TYPE -->|HTTP 401/403\nfra GET /location| RF1[Full innlogging + retry]
    RF1 --> RF2{OK?}
    RF2 -->|Ja| CONTINUE
    RF2 -->|Nei| RF3[Cached data]
    RF3 --> FAIL1

    TYPE -->|HTTP 429/5xx| TR1{last_data\ntilgjengelig?}
    TR1 -->|Ja| RETCACHE
    TR1 -->|Nei| FAIL1

    TYPE -->|WS kobling brutt| WF1[request_reconnect\nSDK-loop prøver på nytt]
    WF1 --> WF2[Umiddelbar poll\nfor fersk data]
    WF2 --> WF3{Polling OK?}
    WF3 -->|Ja| CONTINUE
    WF3 -->|Nei| WF4[Watchdog tar over\nhvert 1. min]

    TYPE -->|Nettverksfeil| NF1[Bruk last_data\nhvis innenfor grace-period]
    NF1 --> NF2{"Cache-alder\n< grace_seconds\n(max(60, min(scan_interval, 300)))"}
    NF2 -->|Ja| RETCACHE
    NF2 -->|Nei| FAIL1
```
