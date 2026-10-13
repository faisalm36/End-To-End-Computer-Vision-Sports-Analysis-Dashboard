#!/usr/bin/env python3
"""Regenerate docs/API.md from the real FastAPI app.

Every endpoint section is built from app.openapi() (paths, auth, parameters, bodies), and the response examples
come from real calls made with FastAPI's TestClient against a THROWAWAY SQLite database seeded by backend/seed.py,
using the stub CV pipeline. MySQL, backend/.env and backend/uploads/ are never touched (same isolation as tests).

Usage (from the repo root):  backend/.venv/bin/python scripts/gen_api_docs.py [--out docs/API.md]
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TMP = Path(tempfile.mkdtemp(prefix="soccer-api-docs-"))
os.environ.update({
    "BACKEND_ENV_FILE": "", "DATABASE_URL": f"sqlite:///{TMP / 'docs.db'}",
    "UPLOAD_DIR": str(TMP / "uploads"), "THUMBNAIL_DIR": str(TMP / "uploads" / "thumbnails"),
    "CV_OUTPUT_DIR": str(TMP / "cv_outputs"), "CV_PIPELINE_MODE": "stub", "CV_PIPELINE_STUB": "true",
    "CV_PIPELINE_PATH": str(TMP / "no-cv" / "run_pipeline.py"), "THUMBNAILS_ENABLED": "false",
    "JWT_SECRET": "docs-generator-secret-at-least-32-bytes!!", "MAX_UPLOAD_MB": "500",
})
sys.path.insert(0, str(BACKEND))

import database  # noqa: E402
assert database.engine.url.get_backend_name() == "sqlite", "refusing to run against a real database"
from fastapi.testclient import TestClient  # noqa: E402
import seed  # noqa: E402
from main import app  # noqa: E402

FAKE_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 256
DEMO = {"email": "faisal@example.com", "password": "capstone123"}

# Error codes raised in the code (routers/*.py, security.py, main.py) beyond the 200/201/202/204 success code.
AUTH_ERR = ["401 missing/invalid/expired Bearer token"]
ERRORS = {
    ("post", "/api/auth/register"): ["409 email already registered", "422 validation (password < 8 chars, bad email, names)"],
    ("post", "/api/auth/login"): ["401 incorrect email or password", "422 missing fields"],
    ("post", "/api/auth/token"): ["401 incorrect email or password", "422 missing fields"],
    ("get", "/api/auth/me"): AUTH_ERR,
    ("patch", "/api/auth/me"): AUTH_ERR + ["409 email already registered", "422 blank / too long names"],
    ("post", "/api/auth/change-password"): AUTH_ERR + ["400 current password incorrect / new == current", "422 new password too short"],
    ("post", "/api/videos"): AUTH_ERR + ["404 match_id not yours", "413 file larger than MAX_UPLOAD_MB",
                                          "415 extension / content type / file signature not a video",
                                          "422 empty file, missing match info, home_team == away_team, bad tags JSON"],
    ("get", "/api/videos"): AUTH_ERR,
    ("get", "/api/videos/{video_id}"): AUTH_ERR + ["404 not found or not yours"],
    ("delete", "/api/videos/{video_id}"): AUTH_ERR + ["404 not found or not yours"],
    ("get", "/api/videos/{video_id}/stats"): AUTH_ERR + ["404 not found or not yours",
                                                          "409 not processed yet / failed: {detail, status, stage, progress, error_message}"],
    ("get", "/api/videos/{video_id}/heatmap"): AUTH_ERR + ["404 not found or not yours", "409 not processed yet (same body as /stats)"],
    ("get", "/api/videos/{video_id}/thumbnail"): ["401 no Bearer token and no valid ?token=", "404 no thumbnail / not yours"],
    ("get", "/api/players/{player_id}"): ["404 player not found"],
    ("get", "/api/players/{player_id}/metrics"): AUTH_ERR + ["404 not your player"],
    ("get", "/api/players/{player_id}/heatmap"): AUTH_ERR + ["404 not your player"],
    ("patch", "/api/matches/{match_id}"): AUTH_ERR + ["404 not your match",
                                                       "422 nothing to change, scores not paired, bad our_side, result contradicts score"],
    ("get", "/api/insights"): AUTH_ERR + ["404 player_id / team_id not yours", "422 tag_key/key missing"],
    ("get", "/api/insights/tags"): AUTH_ERR + ["404 player_id / team_id not yours", "422 key missing"],
}
for _m, _p in [("get", "/api/matches"), ("get", "/api/matches/{match_id}"), ("get", "/api/tags"),
               ("get", "/api/tags/keys"), ("get", "/api/tags/values")]:
    ERRORS.setdefault((_m, _p), AUTH_ERR + (["404 not your match"] if "{" in _p else []))
for _p in ("/api/matches/{match_id}/tags", "/api/videos/{video_id}/tags"):
    for _m in ("get", "post", "put", "delete"):
        ERRORS[(_m, _p)] = AUTH_ERR + ["404 not found or not yours"] + (
            ["422 bad tag (empty / too long / ':' in key) or > 50 tags"] if _m in ("post", "put") else
            ["422 key missing"] if _m == "delete" else [])


def shrink(x, depth=0):
    """Keep examples readable: long lists -> first 2 items + a note; long strings cut."""
    if isinstance(x, list):
        if x and all(isinstance(i, (int, float)) for i in x) and len(x) > 6:
            return x[:6] + [f"... {len(x) - 6} more"]
        if len(x) > 2:
            return [shrink(i, depth + 1) for i in x[:2]] + [f"... {len(x) - 2} more"]
        return [shrink(i, depth + 1) for i in x]
    if isinstance(x, dict):
        return {k: shrink(v, depth + 1) for k, v in x.items()}
    if isinstance(x, str) and x.startswith("eyJ"):
        return "<JWT>"
    if isinstance(x, str) and "token=eyJ" in x:
        return x.split("token=")[0] + "token=<JWT>"
    if isinstance(x, str) and len(x) > 160:
        return x[:157] + "..."
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "API.md"))
    args = ap.parse_args()
    seed.seed()
    spec = app.openapi()
    calls = {}
    with TestClient(app) as c:
        def rec(method, path, url, **kw):
            r = c.request(method.upper(), url, **kw)
            body = None
            if r.headers.get("content-type", "").startswith("application/json") and r.content:
                body = shrink(r.json())
            elif r.content:
                body = f"<{r.headers.get('content-type')} {len(r.content)} bytes>"
            calls[(method, path)] = {"url": url, "status": r.status_code, "body": body,
                                     "req": kw.get("json", kw.get("data")), "files": "files" in kw}
            return r

        tok = c.post("/api/auth/login", json=DEMO).json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}
        rec("get", "/health", "/health")
        rec("get", "/api/config", "/api/config")
        rec("post", "/api/auth/register", "/api/auth/register",
            json={"name": "Sam Analyst", "email": "sam@example.com", "password": "supersecret1"})
        rec("post", "/api/auth/login", "/api/auth/login", json=DEMO)
        rec("post", "/api/auth/token", "/api/auth/token",
            data={"username": DEMO["email"], "password": DEMO["password"]})
        sam = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "sam@example.com",
                                                                            "password": "supersecret1"}).json()["access_token"]}
        rec("get", "/api/auth/me", "/api/auth/me", headers=H)
        rec("patch", "/api/auth/me", "/api/auth/me", headers=sam, json={"name": "Samantha Analyst"})
        rec("post", "/api/auth/change-password", "/api/auth/change-password", headers=sam,
            json={"current_password": "supersecret1", "new_password": "evenmoresecret2"})
        form = {"title": "Derby first half", "match_date": "2026-09-20", "home_team": "Eagles FC",
                "away_team": "Riverside", "our_side": "home", "tags": json.dumps([{"key": "weather", "value": "Windy"}])}
        up = rec("post", "/api/videos", "/api/videos", headers=H, data=form,
                 files={"file": ("derby.mp4", FAKE_MP4, "video/mp4")})
        vid, mid = up.json()["id"], up.json()["match_id"]
        rec("get", "/api/videos", "/api/videos", headers=H)
        rec("get", "/api/videos/{video_id}", f"/api/videos/{vid}", headers=H)
        st = rec("get", "/api/videos/{video_id}/stats", f"/api/videos/{vid}/stats", headers=H)
        pid = st.json()[0]["player_id"]
        rec("get", "/api/videos/{video_id}/heatmap", f"/api/videos/{vid}/heatmap?player_id={pid}", headers=H)
        rec("get", "/api/videos/{video_id}/thumbnail", f"/api/videos/{vid}/thumbnail", headers=H)
        rec("post", "/api/videos/{video_id}/tags", f"/api/videos/{vid}/tags", headers=H,
            json={"tags": [{"key": "competition", "value": "League"}]})
        rec("get", "/api/videos/{video_id}/tags", f"/api/videos/{vid}/tags", headers=H)
        rec("put", "/api/videos/{video_id}/tags", f"/api/videos/{vid}/tags", headers=H,
            json={"tags": [{"key": "weather", "value": "Windy"}, {"key": "competition", "value": "Cup"}]})
        rec("delete", "/api/videos/{video_id}/tags", f"/api/videos/{vid}/tags?key=competition&value=Cup", headers=H)
        rec("patch", "/api/matches/{match_id}", f"/api/matches/{mid}", headers=H, json={"home_score": 2, "away_score": 1})
        rec("get", "/api/matches", "/api/matches", headers=H)
        rec("get", "/api/matches/{match_id}", f"/api/matches/{mid}", headers=H)
        rec("post", "/api/matches/{match_id}/tags", f"/api/matches/{mid}/tags", headers=H,
            json={"tags": [{"key": "pitch", "value": "Turf"}]})
        rec("get", "/api/matches/{match_id}/tags", f"/api/matches/{mid}/tags", headers=H)
        rec("put", "/api/matches/{match_id}/tags", f"/api/matches/{mid}/tags", headers=H,
            json={"tags": [{"key": "weather", "value": "Windy"}, {"key": "pitch", "value": "Grass"}]})
        rec("delete", "/api/matches/{match_id}/tags", f"/api/matches/{mid}/tags?key=pitch", headers=H)
        rec("get", "/api/tags", "/api/tags", headers=H)
        rec("get", "/api/tags/keys", "/api/tags/keys", headers=H)
        rec("get", "/api/tags/values", "/api/tags/values?key=weather", headers=H)
        rec("get", "/api/metrics", "/api/metrics")
        rec("get", "/api/players/stats", "/api/players/stats?include=metrics&metrics=sprint_count,hsr_distance_km")
        rec("get", "/api/players/{player_id}", f"/api/players/{pid}")
        rec("get", "/api/players/{player_id}/metrics", f"/api/players/{pid}/metrics?metrics=distance_km,sprint_count", headers=H)
        rec("get", "/api/players/{player_id}/heatmap", f"/api/players/{pid}/heatmap", headers=H)
        rec("get", "/api/insights", "/api/insights?tag_key=weather", headers=H)
        rec("get", "/api/insights/tags", "/api/insights/tags?key=weather", headers=H)
        # 409 example: a video that hasn't been processed yet (background task disabled for this one upload)
        import routers.videos as rv
        orig = rv.process_video
        rv.process_video = lambda _vid: None
        q = c.post("/api/videos", headers=H, data=dict(form, title="Queued clip"),
                   files={"file": ("q.mp4", FAKE_MP4, "video/mp4")}).json()["id"]
        rv.process_video = orig
        r409 = c.get(f"/api/videos/{q}/stats", headers=H)
        not_found = c.get("/api/videos/999999", headers=H)
        no_auth = c.get("/api/videos")
        bad422 = c.post("/api/auth/register", json={"email": "not-an-email", "password": "x"})
        rec("delete", "/api/videos/{video_id}", f"/api/videos/{q}", headers=H)

    out = render(spec, calls, r409, not_found, no_auth, bad422)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(out)
    missing = [(m, p) for p, ops in spec["paths"].items() for m in ops if (m, p) not in calls]
    print(f"wrote {args.out}: {sum(len(v) for v in spec['paths'].values())} endpoints, "
          f"{len(calls)} with live examples, missing={missing}")


def ref_name(schema):
    if not schema:
        return None
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in schema:
        return " or ".join(filter(None, (ref_name(s) or s.get("type") for s in schema["anyOf"])))
    return schema.get("type")


def body_fields(spec, schema):
    name = ref_name(schema)
    comp = spec["components"]["schemas"].get(name or "", {})
    req = set(comp.get("required", []))
    rows = []
    for k, v in comp.get("properties", {}).items():
        t = ref_name(v) or (" or ".join(filter(None, (s.get("type") for s in v.get("anyOf", [])))) or v.get("format", ""))
        rows.append(f"| `{k}` | {t} | {'yes' if k in req else 'no'} | {(v.get('description') or '').replace('|', '/')} |")
    return rows


def render(spec, calls, r409, not_found, no_auth, bad422):
    L = []
    w = L.append
    w("# API reference")
    w("")
    w(f"Generated from the backend code (FastAPI app `{spec['info']['title']}` v{spec['info']['version']}) by "
      "`scripts/gen_api_docs.py`. Every response example below is a real response, recorded against a throwaway "
      "SQLite database loaded with `backend/seed.py` and using the **stub** CV pipeline, so the numbers are demo "
      "data. Long lists are shortened (`\"... N more\"`). Regenerate after any API change:")
    w("")
    w("```bash\nbackend/.venv/bin/python scripts/gen_api_docs.py\n```")
    w("")
    w("Interactive docs from the running server: `http://localhost:8000/docs` (Swagger), `/redoc`, `/openapi.json`.")
    w("")
    w("## Conventions")
    w("")
    w("- **Base URL**: `http://localhost:8000` in development (the frontend reads it from `VITE_API_URL`).")
    w("- **Auth**: `Authorization: Bearer <access_token>`. Get the token from `POST /api/auth/login` (JSON) or "
      "`POST /api/auth/register`. Tokens are HS256 JWTs, valid for `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60). "
      "There is no refresh endpoint; log in again when you get a 401.")
    w("- **Ownership**: videos, matches, tags and player history are per-user. Anything that belongs to another "
      "user returns **404**, not 403, so it's impossible to tell whether it exists.")
    w("- **Public (no token)**: `/health`, `/api/config`, `/api/metrics`, `/api/players/stats`, "
      "`/api/players/{player_id}`, `/api/auth/register|login|token`. Note that `/api/players/stats` and "
      "`/api/players/{id}` are not user-scoped: they return every player in the database.")
    w("- **Timestamps** are UTC ISO-8601 with `Z`. **Units**: speeds in mph (`*_kmh` variants where noted), "
      "distances in km, pitch coordinates in metres.")
    w("- **Errors** are JSON `{\"detail\": ...}`. Common shapes (all recorded live):")
    w("")
    w(f"  - 401 `GET /api/videos` without a token: `{json.dumps(no_auth.json())}`")
    w(f"  - 404 `GET /api/videos/999999`: `{json.dumps(not_found.json())}`")
    w(f"  - 409 `GET /api/videos/{{id}}/stats` before processing finishes: `{json.dumps(r409.json())}`")
    b = bad422.json()
    b["detail"] = b["detail"][:1]
    w(f"  - 422 validation error (FastAPI): `{json.dumps(b)}` (one entry per invalid field)")
    w("  - 503 `{\"detail\": \"Database unavailable\"}` when MySQL can't be reached, and 500 "
      "`{\"detail\": \"Internal server error\"}` for unexpected errors. `/health` never fails; it reports "
      "`\"db\": \"unreachable\"` instead.")
    w("")
    w("## Endpoints")
    w("")
    w("| Method | Path | Auth | Summary |")
    w("|---|---|---|---|")
    order = []
    for p, ops in spec["paths"].items():
        for m, o in ops.items():
            order.append((p, m, o))
    groups = [("Health & config", ("/health", "/api/config")), ("Auth", ("/api/auth",)),
              ("Videos (upload, processing, results)", ("/api/videos",)), ("Matches", ("/api/matches",)),
              ("Tags", ("/api/tags",)), ("Players & metrics", ("/api/metrics", "/api/players")),
              ("Insights", ("/api/insights",))]

    def grp(p):
        for i, (_, prefixes) in enumerate(groups):
            if any(p == x or p.startswith(x + "/") or p == x for x in prefixes):
                return i
        return len(groups)
    order.sort(key=lambda t: (grp(t[0]), t[0], ["post", "get", "put", "patch", "delete"].index(t[1])))
    for p, m, o in order:
        anchor = "".join(ch for ch in f"{m} {p}".lower() if ch.isalnum() or ch in " -_").replace(" ", "-")
        w(f"| {m.upper()} | [`{p}`](#{anchor}) | {'Bearer' if o.get('security') else 'public'} | {o.get('summary', '')} |")
    w("")
    cur = None
    for p, m, o in order:
        g = grp(p)
        if g != cur:
            cur = g
            w(f"## {groups[g][0] if g < len(groups) else 'Other'}")
            w("")
        w(f"### {m.upper()} {p}")
        w("")
        w(f"**Auth:** {'Bearer token' if o.get('security') else 'none (public)'}"
          + ("; the thumbnail also accepts its own `?token=` from `thumbnail_url`" if p.endswith("/thumbnail") else ""))
        w("")
        if o.get("description"):
            w(o["description"].strip())
            w("")
        params = o.get("parameters", [])
        if params:
            w("| Parameter | In | Type | Required | Notes |")
            w("|---|---|---|---|---|")
            for x in params:
                s = x.get("schema", {})
                t = s.get("type") or " or ".join(filter(None, (i.get("type") for i in s.get("anyOf", []))))
                w(f"| `{x['name']}` | {x['in']} | {t} | {'yes' if x.get('required') else 'no'} | "
                  f"{(x.get('description') or s.get('description') or '').replace('|', '/')} |")
            w("")
        rb = o.get("requestBody", {}).get("content", {})
        for ctype, cont in rb.items():
            rows = body_fields(spec, cont.get("schema"))
            w(f"**Request body** (`{ctype}`)" + (":" if rows else ""))
            w("")
            if rows:
                w("| Field | Type | Required | Notes |")
                w("|---|---|---|---|")
                L.extend(rows)
                w("")
        call = calls.get((m, p))
        if call:
            w("**Example**")
            w("")
            req = call["req"]
            line = f"{m.upper()} {call['url']}"
            if call["files"]:
                line += "\nContent-Type: multipart/form-data\n" + "\n".join(f"{k}={v}" for k, v in (req or {}).items()) \
                        + "\nfile=@derby.mp4 (video/mp4)"
            elif req is not None:
                line += "\n" + json.dumps(req, indent=2)
            w("```http\n" + line + "\n```")
            w("")
            note = (" (the stub clip has no thumbnail; with ffmpeg/OpenCV and a real clip this is `200 image/jpeg`)"
                    if p.endswith("/thumbnail") and call["status"] == 404 else "")
            w(f"Response **{call['status']}**{note}" + (":" if call["body"] is not None else " (no body)"))
            w("")
            if call["body"] is not None:
                body = call["body"]
                w("```json\n" + (json.dumps(body, indent=2) if not isinstance(body, str) else body) + "\n```")
                w("")
        codes = sorted(set(o["responses"]) - {"422"})
        errs = ERRORS.get((m, p), [])
        w("**Status codes:** " + ", ".join(f"`{c}`" for c in codes)
          + ("; errors: " + "; ".join(errs) if errs else "")
          + ("" if any(e.startswith("422") for e in errs) or "422" not in o["responses"] else "; `422` invalid parameters"))
        w("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
