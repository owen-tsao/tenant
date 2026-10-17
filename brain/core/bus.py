import asyncio
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass

@dataclass
class Result:
    ok: bool
    result: dict | None = None
    code: str | None = None
    message: str | None = None
    # Internal correlation metadata; keep the existing public response shape.
    req: str | None = None

    def as_dict(self):
        return {"ok": True, "result": self.result} if self.ok else {"ok": False, "code": self.code, "message": self.message}

class Bus:
    def __init__(self, registry):
        self.registry = registry
        self.locks = defaultdict(asyncio.Lock)
        self.pending = {}
        self.uncertain = {}

    @staticmethod
    def valid_args(spec, args):
        if not isinstance(args, dict) or set(args) != set(spec.args):
            return False
        for key, schema in spec.args.items():
            value = args[key]
            typ = schema["type"]
            if typ == "boolean" and type(value) is not bool: return False
            if typ == "string" and not isinstance(value, str): return False
            if typ == "string" and "maxLength" in schema and len(value) > schema["maxLength"]: return False
            if typ == "integer" and type(value) is not int: return False
            if typ == "number" and (type(value) not in (int, float) or not math.isfinite(value)): return False
            if "enum" in schema and value not in schema["enum"]: return False
            if "minimum" in schema and value < schema["minimum"]: return False
            if "maximum" in schema and value > schema["maximum"]: return False
        return True

    async def call(self, device_id, cap, args, timeout=5.0, *, authorize=None):
        # Snapshot inputs and connection before queueing. Never migrate queued work to a new socket.
        import copy
        args = copy.deepcopy(args)
        dev = self.registry.devices.get(device_id)
        if not dev or not dev.online: return Result(False, code="OFFLINE", message="Device offline; nothing sent")
        sent = False
        expires = asyncio.get_running_loop().time() + timeout
        req = None
        try:
            async with asyncio.timeout(timeout):
                async with self.locks[device_id]:
                    if self.registry.devices.get(device_id) is not dev or not dev.online:
                        return Result(False, code="OFFLINE", message="Connection changed; nothing sent")
                    if any(owner is dev for owner in self.uncertain.values()):
                        return Result(False, code="UNKNOWN", message="Previous action unresolved; no new action sent")
                    spec = dev.caps.get(cap)
                    if not spec: return Result(False, code="UNSUPPORTED", message="Capability absent")
                    if not self.valid_args(spec, args): return Result(False, code="INVALID", message="Invalid arguments")
                    # Required synchronous dispatch-time policy; no await between check and send initiation.
                    # Guest owner must capture lease identity/scopes/room in this callback.
                    if authorize is None or not authorize(dev, cap, args):
                        return Result(False, code="PERMISSION", message="Dispatch authorization absent or denied")
                    req = "r_" + uuid.uuid4().hex
                    future = asyncio.get_running_loop().create_future()
                    self.pending[req] = (dev, future)
                    dev.busy = True
                    sent = True  # send failure may still have delivered bytes
                    await dev.ws.send_json({"type":"do", "req":req, "cap":cap, "args":args,
                                            "deadline_ms":max(1, int((expires - asyncio.get_running_loop().time())*1000)), "epoch":self.registry.room.epoch})
                    result = await future
                    result.req = req
                    return result
        except TimeoutError:
            if sent: self.uncertain[req] = dev
            return Result(False, code="UNKNOWN" if sent else "TIMEOUT", message="Outcome unknown; not retried" if sent else "Queue timeout; nothing sent", req=req)
        except asyncio.CancelledError:
            if sent: self.uncertain[req] = dev
            raise
        except Exception:
            if sent: self.uncertain[req] = dev
            return Result(False, code="UNKNOWN" if sent else "FAILED", message="Outcome unknown; not retried" if sent else "Nothing sent", req=req)
        finally:
            if req:
                item = self.pending.pop(req, None)
                if item and not item[1].done(): item[1].cancel()
                dev.busy = False

    def receive(self, dev, frame):
        if not isinstance(frame, dict): return
        req = frame.get("req")
        if not isinstance(req, str): return
        valid_reply = (frame.get("type") == "ok" and isinstance(frame.get("result"), dict)) or (frame.get("type") == "err" and isinstance(frame.get("code"), str) and isinstance(frame.get("message"), str))
        if self.uncertain.get(req) is dev and valid_reply:
            self.uncertain.pop(req, None)
        item = self.pending.get(req)
        if not item or item[0] is not dev or item[1].done(): return
        if frame.get("type") == "ok" and isinstance(frame.get("result"), dict):
            item[1].set_result(Result(True, result=frame["result"]))
        elif frame.get("type") == "err" and isinstance(frame.get("code"), str) and isinstance(frame.get("message"), str):
            item[1].set_result(Result(False, code=frame["code"], message=frame["message"]))

    def disconnect(self, dev):
        self.registry.offline(dev)
        self.uncertain = {req: owner for req, owner in self.uncertain.items() if owner is not dev}
        for owner, future in list(self.pending.values()):
            if owner is dev and not future.done():
                future.set_result(Result(False, code="UNKNOWN", message="Disconnected; outcome unknown; not retried"))
