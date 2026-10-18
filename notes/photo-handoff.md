# Photo backend → Root / Owen handoff

Owner: local photo backend. Initial exact interface, October 17, 2026. Base HEAD0058cc1; no deployment or physical effects. Implementation below is being built in new files only. Root routes this request to Owen; no other chat was messaged.

## Accepted behavior

Operator explicitly opts the exact enrolled phone into still photos and frames the group locally. Camera/torch OS permission alone does not authorize capture. Current guest asks for one still; same authenticated phone captures/uploads it and the selected authenticated Mac viewer displays it. Keep the latest displayed photo through Leave/expiry/new guests until replacement or host reset. Clear guest context/queued commands on replacement; no image bytes in model history. Host retention setting, gallery and perception are excluded. Mac/projector routing remains a later display operation; this backend establishes actual still → selected Mac viewer.

## Exact phone contract — Owen

After enrolling normally at /ws/device, advertise capability:

```json
{"camera.capture":{"description":"Take one explicitly permitted still","args":{"capture_id":{"type":"string"},"upload_url":{"type":"string"},"upload_token":{"type":"string"}}}}
```

Photo opt-in is a separate local switch, initially OFF on every page/socket load. Once the chosen existing preview stream is live, send on that SAME authenticated device socket:

```json
{"type":"photo.consent","enabled":true,"ready":true}
```

Opt-out/stream failure: send enabled:false,ready:false (or enabled:true,ready:false if still opted in). Root routes only this frame to service.device_event(dev,frame), replies with its returned frame `{type:"photo.consent",ok:true,revision:N,enabled:bool,ready:bool}`. Repeating identical state is idempotent. State change/reconnect invalidates pending work. No arbitrary source ID is trusted in consent frames. Device must locally recheck consent immediately before shutter.

On normal `do` for camera.capture, args contain capture_id, same-origin upload_url and private upload_token; do not log/show them or include them in model replies. Respect deadline_ms and epoch as for other device actions. Use the existing chosen preview stream, take ONE JPEG frame; no lens switch, competing stream or automatic retry. POST raw image/jpeg bytes to upload_url with Authorization: Bearer upload_token. Bound:5MiB input,16million decoded pixels. After upload returns ok, ACK through the existing device result path:

```json
{"type":"ok","req":"BUS_REQ","result":{"capture_id":"CAPTURE_ID","state":"captured"}}
```

On denial/failure use existing err req/code/message. A repeated do/capture_id must return its recorded outcome without another shutter. UNKNOWN must not recapture. Upload success is storage staging, not a claim of Mac rendering. Capture/upload and matching phone ACK are both required before viewer publication. Keep the previous displayed image on failure.

## Exact host/viewer HTTP contract — Owen

All JSON mutations require approved same-origin Origin. Host endpoints additionally require normal Authorization: Bearer HOST_TOKEN. No host token is placed in URLs. Root includes the new router before the static mount.

1. `POST /host/photos/config` body `{source_device_id:"PHONE_ID",viewer_id:"mac-main",enabled:true}`. Exact fields; IDs1–128 chars. enabled:false revokes new capture/publication. Changes fence pending work, preserve the existing displayed photo. This binds photo-specific source/viewer roles without editing device identity persistence.
2. From the actual intended Mac viewer browser: `POST /host/photos/viewer` body `{viewer_id:"mac-main"}` with host authorization. Server sets private HttpOnly SameSite=Strict cookie `tenant_photo_viewer`, Path=/photos, Secure on HTTPS. Re-enrollment replaces the viewer binding, invalidates pending work and old cookie. No credential comes back in JSON. Response `{ok:true,viewer_id:"mac-main"}`.
3. `GET /photos/viewer/state`, cookie required, no-store. Poll about every second; this also establishes selected viewer liveness (15s window). Returns `{ok:true,version:N,photo:null|{photo_id,image_url,captured_at,source_label,version},pending:bool}`. `version` increases on replacement/clear/invalidation. The photo is either the authorized current candidate or the latest actually render-confirmed still; no public /ws/display photo URL is added. Keep the old visible image until new image successfully loads. Discard any old-version load finishing after a newer state/clear. A null state clears only when it represents an actual newer host reset/absence, not a transient request/network failure. Guest ending cancels a pending candidate, not the accepted displayed photo.
4. `GET /photos/images/{photo_id}` uses the same viewer cookie; returns normalized JPEG only for that selected viewer's currently allowed candidate/latest. No-store/nosniff; an opaque URL alone never grants access. Do not fetch remote URLs.
5. After actual decode/render of the exact photo, `POST /photos/viewer/receipt` body `{photo_id:"...",version:N}` using viewer cookie. Matching current authenticated viewer + current candidate required; first valid receipt promotes it to latest displayed. Duplicates for the retained latest are idempotent even after guest ending. The software receipt is not physical screen evidence. Reset invalidates old images/receipts and broadcasts via state polling a newer null version.

## Guest / native integration — Root

- `POST /photos/captures` body `{guest_id,request_id,source_device_id}`, original per-guest HttpOnly cookie required. Exact current active lease, camera.capture + photo.show scope (or *), controller/generation, source consent/connection, host source/viewer roles and live selected viewer required. No activation/renewal by this route. Response is safe status only, never ticket/image URL/bytes.
- `GET /photos/captures/{request_id}?guest_id=...`, same guest cookie, returns that request's safe status. Pending, captured, stored and displayed are distinct. Duplicate immutable request IDs never create another ticket/shutter; conflicting reuse fails. UNKNOWN is never replayed.
- Native helper should invoke `await core.photos.capture(lease,request_id,source_device_id,generation=grant.generation)` through its existing authorized turn path; no shell HTTP host bypass and no model-visible upload token. New scoped native operation/inventory wiring is a narrow Root integration task; this owner does not edit native_devices.py. `core.photos.inventory(lease,generation=...)` returns safe readiness only.
- Bind service's current-controller authority callback to `core.agent.allows_program(lease,generation)` in native mode; fail closed if controller changes. Non-native tests explicitly supply a callback. Never use a caller-supplied generation as authority. REST adapter derives generation from the current server agent.
- Root instantiates PhotoService and installs the router; see proposed integration patch after tests. Route photo.consent via the actual authenticated device object, call photos.sweep() from sweep, photos.invalidate_guest(guest_id) on revoke, and synchronous photos.reset() immediately after lease reset BEFORE any await in host reset. Only explicit host reset clears latest; room.epoch changes from ordinary Leave do not clear it.
- No photo bytes/credentials enter transcript/log/model history or public state. Source labels are human-facing only. Service uses exact enrolled Device object + socket, current cap schema, consent/role/viewer revisions, lease object, epoch and controller generation as fences. Runtime metadata owner can route host photo role changes through configure; do not invent physical identities.

## Library / review / evidence

Image normalizer, backend, routes and dedicated tests are being implemented separately. Final tested hashes, independent review, dependency version and remaining integration/physical gates will be appended here. No source PASS, deployment or physical success is claimed by this initial contract.
