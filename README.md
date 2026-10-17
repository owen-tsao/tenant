# Tenant

**The room has a brain. Scan the code and you can talk to it. Leave, and it forgets you.**

Tenant lets anyone walk into a space they don't own — a hotel room, a hospital bed, an Airbnb, a conference table — scan a QR code, and control the devices there by text or voice, with no app, no account, and no pairing. Access is a short-lived lease granted by the room. When you leave, or your time runs out, or the host resets the room, the same request is refused.

Built in ~18 hours by two people at DubHacks '26.

## Start here

- [`PLAN.md`](PLAN.md) — what we're building, for whom, the demo, the timeline, and what was deliberately cut (§11 is the merge record with the Morph plan).
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the build spec: components, data model, wire protocol, device capability implementations, failure behaviours.
- [`jay.md`](jay.md) / [`owen.md`](owen.md) — per‑person work files: what each of us owns, in what order, with the check that proves each step.

## Status

Planning complete; scaffolding in progress. Nothing runs yet.

## Honest limits

This is a hackathon build. One room, one process, in-memory state. No camera perception, no smart-home integrations beyond what two phones and a laptop can do. See `PLAN.md` §11 for exactly what is out of scope and why.
