# Tenant

**The room has a brain. Scan the code and you can talk to it. Leave, and it forgets you.**

Tenant lets anyone walk into a space they don't own — a hotel room, a hospital bed, an Airbnb, a conference table — scan a QR code, and control the devices there by text or voice, with no app, no account, and no pairing. Access is a short-lived lease granted by the room. When you leave, or your time runs out, or the host resets the room, the same request is refused.

Built in ~18 hours by two people at DubHacks '26.

## Start here

- [`PLAN.md`](PLAN.md) — what we're building, for whom, the demo, the timeline, and what was deliberately cut (§11 is the merge record with the Morph plan).
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the build spec: components, data model, wire protocol, device capability implementations, failure behaviours.
- [`jay.md`](jay.md) / [`owen.md`](owen.md) — per‑person work files: what each of us owns, in what order, with the check that proves each step.

## Run it

Use Python 3.12, Node for browser tests, and the pinned dependencies in `requirements.txt`.
Create a private `.env` from `.env.example` once, keeping existing values. Set separate random
`HOST_TOKEN` and `DEVICE_TOKEN`, `ROOM_CODE`, and the public HTTPS `PUBLIC_URL`.
The optional Photon fields are not required for the web-chat path.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
sh scripts/dev.sh
```

On the room Mac, choose the desired default audio output yourself. Prepare a local Music
playlist named `Tenant`, or run `python scripts/prepare_demo_audio.py` for an original test clip.
Start the bridge in a second terminal; it does not change volume or output on startup:

```sh
uv run --env-file .env .venv/bin/python agent/laptop.py --check
uv run --env-file .env .venv/bin/python agent/laptop.py
```

For a demo that stays running after a chat command ends, use the explicit local launcher
instead of the foreground commands above:

```sh
.venv/bin/python scripts/runtime.py start brain
.venv/bin/python scripts/runtime.py start audio
.venv/bin/python scripts/runtime.py start tunnel
```

Use `status` or `stop` in place of `start` for each service. Private service logs stay in
`.venv/tenant-runtime/`. The tunnel's public address lasts only while that tunnel runs;
set `PUBLIC_URL` to its actual address and restart the Brain after an address change.
Restarting the Brain ends guest sessions, so guests must join again. Keep enrolled light
pages visible and awake; switching away can release their cameras or connections.

The current planner requires the validated signed-in Codex CLI version recorded in
`brain/core/planner.py`; guests use the host’s Codex through Tenant’s permission checks.
Guest sessions are temporary. `TENANT_STATE_PATH` preserves only room identity, epoch,
and enrolled aliases across restarts. Keep the single-process server’s informational and
access logs disabled: device and guest WebSocket query strings carry private credentials.

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/device-runtime.test.cjs
```

See `tests/evidence/` for the distinction between automated, acknowledged, and physically
observed results. Photo, coordinated outputs, proactive rules, and guest-provided agents
remain gated. A public HTTPS endpoint and Owen’s pages are needed for the complete QR flow.

## Status

Planning complete; scaffolding in progress. Nothing runs yet.

## Honest limits

This is a hackathon build. One room, one process, in-memory state. No camera perception, no smart-home integrations beyond what two phones and a laptop can do. See `PLAN.md` §11 for exactly what is out of scope and why.
