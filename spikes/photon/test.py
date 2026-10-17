"""
Photon 2.0 beta smoke test for Tenant (DubHacks '26).

Proves the exact path the demo needs:
  1. create a shared-line assignment for a phone number  -> assignedPhoneNumber
  2. that phone texts the assigned number
  3. we poll received messages and reply

Usage (in a shell where PHOTON_PROJECT_ID and PHOTON_API_KEY are exported):
  python test.py assign +1XXXXXXXXXX          # step 1: returns the number to text
  python test.py listen +1XXXXXXXXXX          # steps 2-3: waits for a text from that handle, replies
  python test.py assignments                  # list current assignments
No third-party packages. Plain HTTP via urllib.
"""
import json, os, sys, time, uuid, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

BASE = "https://api.photon.codes/v1"
PID = os.environ.get("PHOTON_PROJECT_ID")
KEY = os.environ.get("PHOTON_API_KEY")
if not PID or not KEY:
    sys.exit("PHOTON_PROJECT_ID / PHOTON_API_KEY not set in this shell")

def call(method, path, body=None, headers=None, query=None):
    url = f"{BASE}{path}"
    if query:
        url += "?" + "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in query.items() if v is not None)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "tenant-dubhacks/0.1 (+https://github.com)")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return e.code, (json.loads(raw) if raw.startswith("{") else raw)

def assign(handle):
    status, resp = call("POST", f"/projects/{PID}/platforms/imessage/assignments",
                        body={"handle": handle},
                        headers={"Idempotency-Key": f"tenant-assign-{handle}"})
    print(f"assign {handle}: HTTP {status}")
    if status in (200, 201):
        print(f"  -> text this number from {handle}: {resp['assignedPhoneNumber']}  (assignmentId {resp['assignmentId']})")
        return resp["assignedPhoneNumber"]
    print("  ", json.dumps(resp, indent=2)[:800])
    return None

def assignments():
    status, resp = call("GET", f"/projects/{PID}/platforms/imessage/assignments")
    print(f"HTTP {status}")
    items = resp.get("items", resp) if isinstance(resp, dict) else resp
    for a in items or []:
        print(f"  {a.get('handle')} -> {a.get('assignedPhoneNumber')}  id={a.get('assignmentId') or a.get('id')}  "
              f"status={a.get('status')} released={a.get('releasedAt')} created={a.get('createdAt')}")
    if isinstance(resp, dict) and not items:
        print(json.dumps(resp, indent=2)[:800])

def space(space_id):
    status, resp = call("GET", f"/projects/{PID}/spaces/{space_id}")
    print(f"HTTP {status}"); print(json.dumps(resp, indent=2)[:1500])

def listen(handle, window_s=180, poll_s=2):
    started = datetime.now(timezone.utc)
    since = (started - timedelta(seconds=5)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    seen = set()
    print(f"listening for a text from {handle} (up to {window_s}s)... send 'ping' now")
    deadline = time.time() + window_s
    while time.time() < deadline:
        status, resp = call("GET", f"/projects/{PID}/messages",
                            query={"createdSince": since, "direction": "received", "order": "asc",
                                   "pageSize": 100, "platform": "imessage"})
        if status != 200:
            print("list failed:", status, str(resp)[:300]); time.sleep(poll_s); continue
        for m in resp.get("items", []):
            if m["id"] in seen: continue
            seen.add(m["id"])
            sent_by = m.get("sentBy", {}); recv = m.get("receivedBy", {}); space = m.get("space", {})
            text = (m.get("content") or {}).get("text")
            print(f"  received: from={sent_by.get('handle')} to={recv.get('handle')} text={text!r}")
            print(f"    debug: msg.platform={m.get('platform')} space.kind={space.get('kind')} space.platform={space.get('platform')} "
                  f"recv.kind={recv.get('kind')} sentBy.platform={sent_by.get('platform')}")
            if os.environ.get("PHOTON_DEBUG"):
                print("    raw:", json.dumps(m)[:1500])
            if sent_by.get("handle") != handle or recv.get("kind") != "agent":
                continue
            body = {"spaceId": space["id"], "senderId": recv["id"], "parentMessageId": m["id"],
                    "content": {"type": "text", "format": "plain",
                                "text": f"Tenant is connected. You said: {text}"}}
            s2, r2 = call("POST", f"/projects/{PID}/messages", body=body,
                          headers={"idempotency-key": f"tenant-reply-{m['id']}"})
            print(f"  reply: HTTP {s2} {'accepted' if s2 in (200,202) else r2}")
            if s2 in (200, 202):
                print("PASS: inbound received and reply accepted. Check Messages on the phone.")
                return True
        time.sleep(poll_s)
    print("TIMEOUT: no matching text received")
    return False

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "assign": assign(sys.argv[2])
    elif cmd == "listen": listen(sys.argv[2])
    elif cmd == "assignments": assignments()
    elif cmd == "space": space(sys.argv[2])
    else: print(__doc__)
