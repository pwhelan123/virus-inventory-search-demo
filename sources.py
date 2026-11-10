"""Resolve a source entry (local OneDrive-synced path, or Graph sharing link) to bytes/path, read-only."""
from __future__ import annotations
import base64, io, os
from pathlib import Path


def _share_id(url: str) -> str:
    b = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return "u!" + b


def _msal_app():
    import msal
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    if not client_id:
        raise RuntimeError("Set GRAPH_CLIENT_ID (Entra app registration, delegated Files.Read.All) to use 'graph' sources.")
    tenant = os.environ.get("GRAPH_TENANT", "organizations")
    cache_file = Path.home() / ".virus_search_msal.json"
    cache = msal.SerializableTokenCache()
    if cache_file.exists():
        cache.deserialize(cache_file.read_text())
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)
    return app, cache, cache_file


SCOPES = ["Files.Read.All"]


class NeedsSignIn(Exception):
    pass


def start_device_flow() -> dict:
    app, _, _ = _msal_app()
    return app.initiate_device_flow(scopes=SCOPES)      # has "message", "user_code", "verification_uri"


def complete_device_flow(flow: dict) -> None:
    """Blocks until the user finishes signing in in their browser."""
    app, cache, cache_file = _msal_app()
    res = app.acquire_token_by_device_flow(flow)
    if "access_token" not in res:
        raise RuntimeError(res.get("error_description", res))
    cache_file.write_text(cache.serialize())
    cache_file.chmod(0o600)


def _graph_token() -> str:
    app, cache, cache_file = _msal_app()
    accts = app.get_accounts()
    res = app.acquire_token_silent(SCOPES, account=accts[0]) if accts else None
    if not res or "access_token" not in res:
        raise NeedsSignIn()
    if cache.has_state_changed:
        cache_file.write_text(cache.serialize())
    return res["access_token"]


def fetch(source: dict):
    """Return (buffer_or_path, mtime_str)."""
    t = source.get("type", "local")
    if t == "local":
        p = Path(os.path.expanduser(source["path"]))
        if not p.exists():
            raise FileNotFoundError(f"{p} not found (is the OneDrive folder synced / 'Always keep on this device'?)")
        import datetime as dt
        return p, dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    if t == "graph":
        import requests
        tok = _graph_token()
        r = requests.get(f"https://graph.microsoft.com/v1.0/shares/{_share_id(source['url'])}/driveItem/content",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        r.raise_for_status()
        return io.BytesIO(r.content), "live (Graph)"
    raise ValueError(f"unknown source type {t}")
