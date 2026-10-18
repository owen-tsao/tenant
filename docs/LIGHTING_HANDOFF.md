# Lighting runtime handoff

Base: main f3d919f8ba268ecbc0fce5f80ab4a079af6b0a86. Branch: jay/lighting-runtime.
Scope: real-device protocol and host lighting path only. No Owen files changed.

## Run

Python 3.12, one process/one worker (in-memory registry).

```sh
python -m pip install -r requirements.txt
# Export DEVICE_TOKEN and HOST_TOKEN using private local values; do not commit them.
export ROOM_CODE=7F3A
python -m uvicorn brain.main:app --host 0.0.0.0 --port 8000 --no-access-log
```

HTTPS must be supplied by the hosting owner. Do not expose uvicorn directly for phone enrollment over plain LAN HTTP. Disable/redact proxy query-string logging for /ws/device because the documented auth contract puts the token in ?t. No .env is read automatically. PUBLIC_URL is accepted in config for later display integration; it does not configure TLS. Empty host/device tokens fail closed.

## One physical check (not yet performed)

On an actual iPhone open `https://YOUR_HOST/d/phone-a?room=7F3A`, enter DEVICE_TOKEN in the password field, tap Join, allow camera, and keep the page visible. Unsupported cameras must show an error and never enroll light.

From the host terminal (private exported HOST_TOKEN):

```sh
curl -sS https://YOUR_HOST/host/do -H "Authorization: Bearer $HOST_TOKEN" -H 'Content-Type: application/json' --data '{"device_id":"phone-a","cap":"light","args":{"on":true}}'
curl -sS https://YOUR_HOST/host/do -H "Authorization: Bearer $HOST_TOKEN" -H 'Content-Type: application/json' --data '{"device_id":"phone-a","cap":"light","args":{"on":false}}'
```

Pass: actual rear torch visibly turns on then off; each response is `ok:true` with matching `result.on`. Repeat after network disconnect/reconnect: connection returns without the earlier action replaying. Browser acknowledgement is not an optical observation. Failure/timeout must never be described as confirmed physical success. Guest-surface physical check remains gated on the coordinator's guest/access integration.

## Audio owner: device connection

Dial `wss://YOUR_HOST/ws/device?t=DEVICE_TOKEN`. First frame within 5 s:

```json
{"type":"hello","id":"laptop","label":"Room audio","room":"7F3A","caps":{"say":{"description":"Speak text","args":{"text":{"type":"string"}}}}}
```

Receive `welcome` with room and server_time. Reply `pong` to server `ping` every 5 s; no pong for 10 s closes/offlines. The server rejects an already-online duplicate ID; reconnect after the old connection closes. Re-send hello on each connection. Never replay actions automatically.

Receive `do {req,cap,args,deadline_ms,epoch}`. Return `ok {req,result:{...}}` only after actual API completion, or `err {req,code,message}`. Keep req dedupe across reconnect in the same process, one effect at a time, absolute state where applicable. Implement only capabilities that really work. Supported manifest argument types: boolean, string, number, integer; optional enum/minimum/maximum. Manifest args are all required, additional args refused. Unsupported complex schemas fail registration rather than being silently ignored.

## Coordinator integration points

- `app.state.registry`, `.bus`, `.config` are the shared runtime. `Registry.online_in(room)` lists reachable devices.
- `await bus.call(id, cap, args, timeout=5, authorize=callback)` returns `Result` (`.ok`, `.result`, `.code`, `.message`, `.as_dict()`). Default authorization is DENY.
- Callback signature: synchronous `callback(device, cap, args) -> bool`, run after acquiring the per-device queue lock immediately before initiating send. Capture the originating lease identity and re-check active state, expiry, current room and scopes here. Do not cache an earlier permission boolean. No await belongs in this callback. The bus does not implement guest policy.
- Queue time is included in timeout. If a queued command times out, nothing is sent. Sent timeout/disconnect is UNKNOWN and never automatically retried. An uncertain live connection is quarantined until a matching late response or disconnect; it cannot receive another action while unresolved. Queued work binds to its original connection and never migrates to a replacement.
- Correlation requires both req and originating Device object; late/wrong-device responses cannot complete another action.
- `/host/do` is the host-authenticated POST check explicitly described by jay.md. It permits light only. `/ws/display` host.do integration remains with the coordinator; no display/reset/guest implementations are claimed here.
- State/registry change notifications and JSONL log integration are still the coordinator's work. This slice does not claim full display or guest functionality.

## Spec contradictions requiring coordinator decision

ARCHITECTURE §3's claim that epoch prevents any queued old action firing after reset is false: a disconnected client cannot know a new epoch. Highest-seen epoch only rejects older frames after the newer epoch arrives. An already-received or executing action cannot be revoked by this field. §10 reset timing/cleanup likewise cannot guarantee physical cancellation. No reserved reset/revocation policy was implemented, and no shared contract was changed.

PLAN uses old `can` manifests in overview examples; implementation follows authoritative ARCHITECTURE §3 `caps` manifests. All current wire names remain unchanged. The guest timeout copy in §12 should not imply outcome certainty; bus exposes UNKNOWN explicitly. Dispatch policy and any future wire changes need coordinator review and Owen coordination.

## Evidence

Commands and final counts are recorded below after independent review. Browser tests use fake camera/WebSocket objects: protocol proof only, never a working physical demo. No physical phone, deployed HTTPS host, or credentials were reachable from this checkout. No scheduled/unattended continuation was configured; this bounded implementation completes here and leaves the physical check above.

Primary implementation references: https://w3c.github.io/mediacapture-image/ (torch capability sequence and constraints); https://fastapi.tiangolo.com/advanced/websockets/ (socket lifecycle/disconnect). Reused standard browser camera constraints and FastAPI websockets; no new integration framework.

Final checks (2026-10-17):

- `python -m unittest discover -s tests -v`: 17 passed, 0 failed (includes simulated host POST → device WS → correlated reply).
- `node --test tests/device-runtime.test.cjs`: 9 passed, 0 failed; simulated browser API only.
- `python -m compileall -q brain`: pass.
- `git diff --check`: pass.
- Independent reviewer demonstrated and regression-tested malformed late replies releasing timeout quarantine; fixed. Also challenged heartbeat send failure, canonical light args, dispatch recheck, missing pongs, and host auth.
- Physical checks: 0 performed. HTTPS deployment and iPhone observation still required. Guest/access integration is outside this slice.

Apply by fetching the branch and cherry-picking its commits in order onto the coordinator checkout; inspect conflicts in shared bootstrap files rather than overwriting another workstream. Never switch branches in another chat's checkout. `web/device.html` is the only web file changed; no Owen-owned files are included.
