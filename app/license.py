import os, time
from datetime import datetime, timezone
import requests
from flask import request
from . import db
from .models import SiteSetting

LICENSE_CACHE_SECONDS = int(os.getenv("LICENSE_CACHE_SECONDS", "21600"))
OFFLINE_GRACE_SECONDS = int(os.getenv("LICENSE_OFFLINE_GRACE_SECONDS", "259200"))

def _setting(key, default=""):
    x = db.session.execute(db.select(SiteSetting).filter_by(key=key)).scalar_one_or_none()
    return x.value if x else default

def _save(key, value):
    x = db.session.execute(db.select(SiteSetting).filter_by(key=key)).scalar_one_or_none()
    if not x:
        x = SiteSetting(key=key)
        db.session.add(x)
    x.value = str(value)

def current_domain():
    # DOMAIN_OVERRIDE is useful behind reverse proxies.
    return (os.getenv("LICENSE_DOMAIN_OVERRIDE") or request.host).split(":")[0].lower().strip()

def required():
    return os.getenv("LICENSE_REQUIRED", "0").lower() in {"1","true","yes","on"}

def status():
    key = _setting("license.key", os.getenv("LICENSE_KEY","")).strip()
    if not key:
        return {"valid": False, "reason": "missing", "plan": "", "expires_at": ""}

    cached_at = float(_setting("license.checked_at","0") or 0)
    cached_valid = _setting("license.cached_valid","0") == "1"
    expires_at = _setting("license.expires_at","")
    plan = _setting("license.plan","")
    now = time.time()

    # Fast local cache while still inside the normal validation window.
    if cached_valid and now - cached_at < LICENSE_CACHE_SECONDS:
        if plan == "lifetime":
            return {"valid": True, "reason": "cached", "plan": plan, "expires_at": expires_at}
        try:
            if datetime.fromisoformat(expires_at.replace("Z","+00:00")).timestamp() <= now:
                return {"valid": False, "reason": "expired", "plan": plan, "expires_at": expires_at}
        except Exception:
            pass
        return {"valid": True, "reason": "cached", "plan": plan, "expires_at": expires_at}

    server = os.getenv("LICENSE_SERVER_URL","").rstrip("/")
    if not server:
        # Development mode: license enforcement is intentionally disabled unless a server is configured.
        return {"valid": not required(), "reason": "server_not_configured", "plan": plan, "expires_at": expires_at}

    try:
        r = requests.get(
            server + "/api/v1/validate",
            params={"license_key": key, "domain": current_domain()},
            timeout=float(os.getenv("LICENSE_TIMEOUT","6"))
        )
        data = r.json()
        valid = bool(data.get("valid"))
        _save("license.checked_at", str(now))
        _save("license.cached_valid", "1" if valid else "0")
        _save("license.plan", data.get("plan",""))
        _save("license.expires_at", data.get("expires_at",""))
        _save("license.customer", data.get("customer",""))
        db.session.commit()
        return data
    except Exception as exc:
        # Short offline grace period avoids taking a live shop offline during a temporary outage.
        if cached_valid and now - cached_at <= OFFLINE_GRACE_SECONDS:
            return {"valid": True, "reason": "offline_grace", "plan": plan, "expires_at": expires_at}
        return {"valid": False, "reason": "server_unreachable", "plan": plan, "expires_at": expires_at, "error": str(exc)}

def activate(key):
    key = (key or "").strip().upper()
    if not key:
        return {"valid": False, "reason": "missing"}
    server = os.getenv("LICENSE_SERVER_URL","").rstrip("/")
    if not server:
        return {"valid": False, "reason": "server_not_configured"}
    try:
        r = requests.get(server + "/api/v1/activate", params={"license_key": key, "domain": current_domain()},
                          timeout=float(os.getenv("LICENSE_TIMEOUT","6")))
        data = r.json()
        if data.get("valid"):
            _save("license.key", key)
            _save("license.checked_at", str(time.time()))
            _save("license.cached_valid","1")
            _save("license.plan",data.get("plan",""))
            _save("license.expires_at",data.get("expires_at",""))
            _save("license.customer",data.get("customer",""))
            db.session.commit()
        return data
    except Exception as exc:
        return {"valid": False, "reason": "server_unreachable", "error": str(exc)}

def clear():
    for k in ["license.key","license.checked_at","license.cached_valid","license.plan","license.expires_at","license.customer"]:
        _save(k,"")
    db.session.commit()
