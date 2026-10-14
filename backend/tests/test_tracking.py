"""v0.5.0: player tracking, public "tracks" contract (detections, tracks, frames, annotated.mp4 with HTTP Range,
video source_url, media tokens, real-mode adapter with a fake CV package). Everything runs in the temp dirs from
conftest (SQLite, stub by default)."""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import jwt
from sqlalchemy import select
import pytest

from config import settings
from conftest import FAKE_MP4, register_and_login
from database import SessionLocal
from models import MatchVideo, Player, PlayerMatchStat, PlayerTrack, Team, TrackingDetection
from security import create_access_token, create_media_token, create_thumbnail_token
import tracking as trk

W, H, FPS, SECONDS = 320, 240, 10, 4
N = SECONDS * FPS

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="ffmpeg/ffprobe needed for the tracking stub")


def make_clip(tmp_root: Path, name: str, seconds=SECONDS) -> bytes:
    out = tmp_root / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size={W}x{H}:rate={FPS}", "-pix_fmt", "yuv420p", str(out)],
                   check=True)
    return out.read_bytes()


def upload(client, h, body, home="Track H", away="Track A"):
    r = client.post("/api/videos", headers=h, data={"match_date": "2026-09-01", "home_team": home, "away_team": away},
                    files={"file": ("clip.mp4", body, "video/mp4")})
    assert r.status_code == 202, r.text
    v = client.get(f"/api/videos/{r.json()['id']}", headers=h).json()
    assert v["status"] == "done", v
    return v


@pytest.fixture(scope="module")
def coach(client):
    return register_and_login(client, "tracker@example.com", first="Tia", last="Tracker")


@pytest.fixture(scope="module")
def rival(client):
    return register_and_login(client, "rival-tracker@example.com", first="Rex", last="Rival")


@pytest.fixture(scope="module")
def clip(tmp_root):
    return make_clip(tmp_root, "track_clip.mp4")


@pytest.fixture(scope="module")
def video(client, coach, clip):
    return upload(client, coach, clip)


def user_id(client, h):
    return client.get("/api/auth/me", headers=h).json()["user_id"]


BOX = [0.3125, 0.3333, 0.0938, 0.2917]   # ~ [100, 80, 130, 150] px in 320x240


def track_bbox(client, h, vid, frame=10, bbox=BOX, **extra):
    r = client.post(f"/api/videos/{vid}/tracks", headers=h, json={"frame": frame, "bbox": list(bbox), **extra})
    assert r.status_code == 202, r.text
    return r.json()


def get_track(client, h, track_id):
    r = client.get(f"/api/tracks/{track_id}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def frames_of(client, tr, **params):
    extra = "".join(f"&{k}={v}" for k, v in params.items())   # keep the ?token= (httpx params would replace it)
    r = client.get(tr["frames_url"] + extra)
    assert r.status_code == 200, r.text
    return r.json()


def probe(path: Path, count=False) -> dict:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames", "-of", "json", str(path)]
    if count:
        cmd.insert(1, "-count_frames")
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["streams"][0]


TRACK_KEYS = {"track_id", "video_id", "status", "stage", "progress", "error_message", "error_code", "target", "fps",
              "frame_count", "width", "height", "annotated_url", "frames_url", "source", "summary", "stats",
              "warnings", "created_at", "updated_at", "finished_at"}


# ------------------------------------------------------------------ full flow (stub)
def test_full_flow_detections_track_frames_annotated_delete(client, coach, video, tmp_root):
    vid = video["id"]
    # detections: normalised [x, y, w, h], cached per (video, frame)
    r = client.get(f"/api/videos/{vid}/detections?frame=10", headers=coach)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"frame", "t", "width", "height", "frame_url", "source", "players"}
    assert (d["frame"], d["t"], d["width"], d["height"], d["source"]) == (10, 1.0, W, H, "stub")
    assert d["players"]
    for p in d["players"]:
        assert {"player_id", "jersey_number", "team", "class", "bbox", "conf"} <= set(p)
        assert {"bbox_xyxy", "x_center", "y_center", "bbox_width", "bbox_height"} <= set(p)
        x, y, w, h = p["bbox"]
        assert 0 <= x and 0 <= y and w > 0 and h > 0 and x + w <= 1.0001 and y + h <= 1.0001
        assert p["team"] in ("A", "B", None) and p["class"] in ("player", "goalkeeper", "referee")
        assert 0 <= p["conf"] <= 1
    again = client.get(f"/api/videos/{vid}/detections?t=1.0", headers=coach).json()   # cached; same frame via t
    assert (again["frame"], again["players"]) == (10, d["players"])
    # frame_url works without a bearer (token in the URL) and is a real JPEG of the clip's size
    assert d["frame_url"].startswith(f"/api/videos/{vid}/frame?frame=10&token=")
    img = client.get(d["frame_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.content[:2] == b"\xff\xd8"
    (tmp_root / "f.jpg").write_bytes(img.content)
    assert (probe(tmp_root / "f.jpg")["width"], probe(tmp_root / "f.jpg")["height"]) == (W, H)
    assert client.get(f"/api/videos/{vid}/frame?frame=10", headers=coach).status_code == 200
    assert client.get(f"/api/videos/{vid}/frame?t=1").status_code == 401

    # POST /tracks with a box -> 202 with the FULL track object
    box = d["players"][0]["bbox"]
    tr = track_bbox(client, coach, vid, frame=d["frame"], bbox=box)
    assert set(tr) == TRACK_KEYS
    assert tr["status"] == "queued" and tr["annotated_url"] is None and tr["source"] is None
    assert tr["frames_url"].startswith(f"/api/tracks/{tr['track_id']}/frames?token=")
    assert (tr["fps"], tr["frame_count"], tr["width"], tr["height"]) == (10.0, N, W, H)
    assert tr["target"]["mode"] == "bbox" and tr["target"]["frame"] == 10 and tr["target"]["t"] == 1.0
    assert tr["target"]["bbox"] == pytest.approx(box, abs=1e-4)
    early = client.get(f"/api/tracks/{tr['track_id']}/frames", headers=coach)
    done = get_track(client, coach, tr["track_id"])
    assert done["status"] == "done" and done["stage"] == "done" and done["progress"] == 100, done
    assert done["source"] == "stub" and any("STUB" in w for w in done["warnings"])
    assert done["annotated_url"].startswith(f"/api/tracks/{tr['track_id']}/annotated.mp4?token=")
    assert done["target"]["jersey_number"] is not None and done["target"]["team"] in ("A", "B")  # filled from CV
    s = done["summary"]
    assert s["tracked_frames"] + s["occluded_frames"] + s["lost_frames"] == N
    assert s["lost_frames"] > 0 and s["occluded_frames"] > 0 and 0 < s["coverage_pct"] < 100
    assert 0.5 < s["avg_conf"] < 1 and s["player_uid"] and s["track_ids"] == [1] and s["lost_segments"]
    assert isinstance(done["stats"], dict) and done["stats"]["distance_per_min_m"] is None  # < 0.1 min
    listed = client.get(f"/api/videos/{vid}/tracks", headers=coach).json()
    assert listed[0]["track_id"] == tr["track_id"] and set(listed[0]) == TRACK_KEYS

    # frames: dense, normalised, states tracked|occluded|lost; token or bearer; ?start&end inclusive
    t = frames_of(client, done)
    assert set(t) == {"track_id", "source", "fps", "width", "height", "frame_count", "start", "end", "frames"}
    assert (t["fps"], t["width"], t["height"], t["frame_count"], t["start"], t["end"], t["source"]) == \
        (10.0, W, H, N, 0, N - 1, "stub")
    assert [f["f"] for f in t["frames"]] == list(range(N))
    for f in t["frames"]:
        assert set(f) == {"f", "t", "bbox", "conf", "state", "pitch_x", "pitch_y"}
        assert f["t"] == round(f["f"] / 10, 3) and f["state"] in ("tracked", "occluded", "lost")
        assert (f["bbox"] is None) == (f["state"] == "lost")
        if f["state"] == "lost":
            assert f["conf"] == 0
    f10 = t["frames"][10]
    assert f10["state"] == "tracked" and f10["bbox"] == pytest.approx(box, abs=0.002)
    assert {f["state"] for f in t["frames"]} == {"tracked", "occluded", "lost"}
    win = frames_of(client, done, start=5, end=7)
    assert [f["f"] for f in win["frames"]] == [5, 6, 7] and (win["start"], win["end"]) == (5, 7)
    assert [f["f"] for f in frames_of(client, done, start=N - 2, end=N + 50)["frames"]] == [N - 2, N - 1]
    assert client.get(done["frames_url"] + "&start=7&end=5").status_code == 422
    assert client.get(f"/api/tracks/{tr['track_id']}/frames", headers=coach).status_code == 200      # bearer
    assert client.get(f"/api/tracks/{tr['track_id']}/frames").status_code == 401

    # the annotated video: H.264 yuv420p, faststart, same fps + frame count as the source, box where frames say
    url = done["annotated_url"]
    full = client.get(url)
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-type"] == "video/mp4"
    size = len(full.content)
    assert int(full.headers["content-length"]) == size > 1000
    mp4 = tmp_root / "annotated.mp4"
    mp4.write_bytes(full.content)
    st = probe(mp4, count=True)
    assert (st["codec_name"], st["pix_fmt"], st["width"], st["height"]) == ("h264", "yuv420p", W, H)
    assert st["avg_frame_rate"] == "10/1" and int(st["nb_read_frames"]) == N
    assert full.content.find(b"moov") < full.content.find(b"mdat")  # +faststart
    tracked = next(f for f in t["frames"][15:] if f["state"] == "tracked")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"select=eq(n\\,{tracked['f']})",
                          "-fps_mode", "passthrough", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    x, y, w, h = tracked["bbox"]
    x1, cy = x * W, int((y + h / 2) * H)
    band = [raw[(cy * W + px) * 3:(cy * W + px) * 3 + 3] for px in range(max(0, int(x1) - 2), int(x1) + 6)]
    assert any(p[1] > 180 and p[0] < 120 and p[2] < 120 for p in band), band  # lime outline at the left edge

    # HTTP Range
    r = client.get(url, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100 and r.content == full.content[:100]
    assert r.headers["content-range"] == f"bytes 0-99/{size}" and r.headers["content-length"] == "100"
    r = client.get(url, headers={"Range": "bytes=-50"})
    assert r.status_code == 206 and r.content == full.content[-50:]
    assert r.headers["content-range"] == f"bytes {size - 50}-{size - 1}/{size}"
    r = client.get(url, headers={"Range": f"bytes=100-{size + 500}"})
    assert r.status_code == 206 and r.content == full.content[100:]
    r = client.get(url, headers={"Range": f"bytes={size}-"})
    assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{size}"
    assert client.get(url, headers={"Range": "bytes=50-10"}).status_code == 416
    assert client.get(url, headers={"Range": "bytes=-0"}).status_code == 416
    assert client.get(url, headers={"Range": "lines=1-2"}).status_code == 200            # malformed: ignored
    assert client.get(url, headers={"Range": "bytes=0-1,5-6"}).status_code == 200        # multi-range: ignored
    etag = full.headers["etag"]
    assert client.get(url, headers={"Range": "bytes=0-9", "If-Range": etag}).status_code == 206
    assert client.get(url, headers={"Range": "bytes=0-9", "If-Range": '"stale"'}).status_code == 200
    hd = client.head(url, headers={"Range": "bytes=0-9"})
    assert hd.status_code == 206 and hd.headers["content-length"] == "10" and hd.content == b""
    assert client.get(f"/api/tracks/{tr['track_id']}/annotated.mp4", headers=coach).status_code == 200  # bearer

    # DELETE -> 204 and the files are gone
    out_dir = trk.job_dir(tr["track_id"])
    assert (out_dir / "replay.mp4").is_file() and (out_dir / trk.FRAMES_API_FILE).is_file()
    assert client.delete(f"/api/tracks/{tr['track_id']}", headers=coach).status_code == 204
    assert not out_dir.exists()
    assert client.get(f"/api/tracks/{tr['track_id']}", headers=coach).status_code == 404
    assert client.get(url).status_code == 404
    assert client.delete(f"/api/tracks/{tr['track_id']}", headers=coach).status_code == 404
    assert early.status_code in (200, 409)


def test_old_routes_are_gone(client, coach, video):
    vid = video["id"]
    tr = track_bbox(client, coach, vid)
    tid = tr["track_id"]
    for method, url in [("get", f"/api/videos/{vid}/candidates?frame=0"), ("post", f"/api/videos/{vid}/track-player"),
                        ("get", f"/api/videos/{vid}/track-jobs"), ("get", f"/api/track-jobs/{tid}"),
                        ("delete", f"/api/track-jobs/{tid}"), ("get", f"/api/track-jobs/{tid}/track"),
                        ("get", f"/api/track-jobs/{tid}/replay.mp4"), ("get", f"/api/tracks/{tid}/track"),
                        ("get", f"/api/tracks/{tid}/replay.mp4")]:
        r = getattr(client, method)(url, headers=coach)
        assert r.status_code in (404, 405) and r.json()["detail"] in ("Not Found", "Method Not Allowed"), url
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "track-" in p or "candidates" in p or "replay" in p]
    for p in ("/api/videos/{video_id}/detections", "/api/videos/{video_id}/tracks", "/api/tracks/{track_id}",
              "/api/tracks/{track_id}/frames", "/api/tracks/{track_id}/annotated.mp4", "/api/videos/{video_id}/source",
              "/api/videos/{video_id}/frame"):
        assert p in paths, p
    client.delete(f"/api/tracks/{tid}", headers=coach)


def test_video_source_url_and_range(client, coach, rival, video, clip):
    vid = video["id"]
    for v in (video, client.get("/api/videos", headers=coach).json()[0]):
        assert v["source_url"].startswith(f"/api/videos/{v['id']}/source?token=")
    url = video["source_url"]
    full = client.get(url)
    assert full.status_code == 200 and full.content == clip and full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes" and int(full.headers["content-length"]) == len(clip)
    r = client.get(url, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == clip[10:20] and r.headers["content-range"] == f"bytes 10-19/{len(clip)}"
    assert client.get(url, headers={"Range": f"bytes={len(clip)}-"}).status_code == 416
    assert client.head(url).headers["content-length"] == str(len(clip))
    assert client.get(f"/api/videos/{vid}/source", headers=coach).status_code == 200            # bearer
    assert client.get(f"/api/videos/{vid}/source").status_code == 401
    uid = user_id(client, coach)
    for bad in (create_media_token(uid, f"source:{vid + 1}"), create_media_token(uid, f"frame:{vid}"),
                create_media_token(uid, f"source:{vid}", minutes=-1), create_thumbnail_token(uid, vid),
                create_access_token(uid)):
        assert client.get(f"/api/videos/{vid}/source?token={bad}").status_code == 401
    rid = user_id(client, rival)
    assert client.get(f"/api/videos/{vid}/source?token={create_media_token(rid, f'source:{vid}')}").status_code == 404
    assert client.get(f"/api/videos/{vid}/source", headers=rival).status_code == 404
    # file gone -> source_url null, /source 404
    db = SessionLocal()
    try:
        v = db.get(MatchVideo, vid)
        real_path = v.file_path
        v.file_path = "uploads/does-not-exist.mp4"
        db.commit()
        assert client.get(f"/api/videos/{vid}", headers=coach).json()["source_url"] is None
        assert client.get(f"/api/videos/{vid}/source", headers=coach).status_code == 404
        v.file_path = real_path
        db.commit()
    finally:
        db.close()


def test_media_tokens_expired_forged_and_wrong_scope(client, coach, video):
    vid = video["id"]
    tr = track_bbox(client, coach, vid)
    tid = tr["track_id"]
    uid = user_id(client, coach)
    good = create_media_token(uid, f"track:{tid}")
    for base in (f"/api/tracks/{tid}/annotated.mp4", f"/api/tracks/{tid}/frames"):
        assert client.get(f"{base}?token={good}").status_code == 200
        expired = create_media_token(uid, f"track:{tid}", minutes=-1)
        assert client.get(f"{base}?token={expired}").status_code == 401
        head, payload, sig = good.split(".")
        assert client.get(f"{base}?token={head}.{payload}.{sig[:-4]}AAAA").status_code == 401
        evil = jwt.encode({"sub": str(uid), "scope": f"track:{tid}", "type": "media"},
                          "not-the-secret-key-0123456789abcdef", algorithm="HS256")
        assert client.get(f"{base}?token={evil}").status_code == 401
        assert client.get(f"{base}?token={create_media_token(uid, f'track:{tid + 1000}')}").status_code == 401
        assert client.get(f"{base}?token={create_media_token(uid, f'frame:{vid}')}").status_code == 401
        assert client.get(f"{base}?token={create_media_token(uid, f'source:{vid}')}").status_code == 401
        assert client.get(f"{base}?token={create_thumbnail_token(uid, vid)}").status_code == 401
        assert client.get(f"{base}?token={create_access_token(uid)}").status_code == 401   # no access token in URL
    # a media token is not a login
    assert client.get("/api/videos", headers={"Authorization": f"Bearer {good}"}).status_code == 401
    assert client.get(f"/api/tracks/{tid}", headers={"Authorization": f"Bearer {good}"}).status_code == 401
    # frame tokens are per video
    frame_tok = create_media_token(uid, f"frame:{vid}")
    assert client.get(f"/api/videos/{vid}/frame?frame=0&token={frame_tok}").status_code == 200
    assert client.get(f"/api/videos/{vid}/frame?frame=0&token={create_media_token(uid, f'frame:{vid + 1}')}"
                      ).status_code == 401
    assert client.get(f"/api/videos/{vid}/frame?frame=0&token={create_media_token(uid, f'frame:{vid}', minutes=-1)}"
                      ).status_code == 401
    client.delete(f"/api/tracks/{tid}", headers=coach)


def test_jersey_mode_team_optional(client, coach, video):
    r = client.post(f"/api/videos/{video['id']}/tracks", headers=coach, json={"jersey_number": 10})
    assert r.status_code == 202, r.text
    tr = r.json()
    assert tr["target"] == {"mode": "jersey", "player_id": None, "jersey_number": 10, "team": None, "frame": None,
                            "t": None, "bbox": None}
    done = get_track(client, coach, tr["track_id"])
    assert done["status"] == "done", done
    assert done["target"]["jersey_number"] == 10 and done["target"]["team"] in ("A", "B")   # team from the tracker
    assert done["stats"]["jersey_number"] == 10
    assert any(f["state"] == "tracked" for f in frames_of(client, done)["frames"])
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)
    r = client.post(f"/api/videos/{video['id']}/tracks", headers=coach, json={"jersey_number": 7, "team": "b"})
    assert r.status_code == 202 and r.json()["target"]["team"] == "B"
    assert get_track(client, coach, r.json()["track_id"])["target"]["team"] == "B"
    client.delete(f"/api/tracks/{r.json()['track_id']}", headers=coach)


@pytest.fixture()
def roster_player(client, coach, video):
    """A player of the coach's home team with two stored detections in the 320x240 test clip (frames 12 and 30)."""
    db = SessionLocal()
    try:
        team = db.scalar(select(Team).where(Team.team_name == "Track H", Team.user_id == user_id(client, coach)))
        p = Player(team_id=team.team_id, first_name="Pia", last_name="Picked", jersey_number=21)
        db.add(p)
        db.flush()
        for f, x in ((12, 40.0), (30, 60.0)):
            db.add(TrackingDetection(video_id=video["id"], player_id=p.player_id, track_id=900, frame_number=f,
                                     object_class="player", jersey_number=None, bbox_x1=x, bbox_y1=50.0,
                                     bbox_x2=x + 32, bbox_y2=122.0, confidence=0.88))
        db.commit()
        pid = p.player_id
    finally:
        db.close()
    yield pid
    db = SessionLocal()
    try:
        db.query(TrackingDetection).filter(TrackingDetection.player_id == pid).delete()
        db.query(PlayerMatchStat).filter(PlayerMatchStat.player_id == pid).delete()
        db.query(Player).filter(Player.player_id == pid).delete()
        db.commit()
    finally:
        db.close()


def test_detections_carry_player_id_and_track_by_player_id(client, coach, rival, video, roster_player):
    vid, pid = video["id"], roster_player
    shutil.rmtree(trk.frames_dir(vid), ignore_errors=True)   # drop cached detections from other tests
    d = client.get(f"/api/videos/{vid}/detections?frame=12", headers=coach).json()
    mine = [p for p in d["players"] if p["player_id"] == pid]
    assert mine and mine[0]["bbox"] == [0.125, 0.2083, 0.1, 0.3] and mine[0]["jersey_number"] == 21
    assert mine[0]["conf"] == 0.88
    # player_id alone -> first stored detection (frame 12), jersey from the roster
    r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"player_id": pid})
    assert r.status_code == 202, r.text
    tgt = r.json()["target"]
    assert tgt == {"mode": "player", "player_id": pid, "jersey_number": 21, "team": None, "frame": 12, "t": 1.2,
                   "bbox": [0.125, 0.2083, 0.1, 0.3]}
    done = get_track(client, coach, r.json()["track_id"])
    assert done["status"] == "done" and frames_of(client, done)["frames"][12]["bbox"] == \
        pytest.approx([0.125, 0.2083, 0.1, 0.3], abs=0.002)
    client.delete(f"/api/tracks/{done['track_id']}", headers=coach)
    # player_id + frame -> nearest stored detection
    r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"player_id": pid, "frame": 28, "team": "A"})
    assert r.status_code == 202 and r.json()["target"]["frame"] == 30 and r.json()["target"]["team"] == "A"
    client.delete(f"/api/tracks/{r.json()['track_id']}", headers=coach)
    # box + labels from the clicked detection: the box is the target, labels are kept
    tr = track_bbox(client, coach, vid, frame=12, bbox=mine[0]["bbox"], player_id=pid, jersey_number=21, team="B",
                    conf=0.88, **{"class": "player"})
    assert tr["target"]["mode"] == "bbox" and tr["target"]["player_id"] == pid and tr["target"]["team"] == "B"
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)
    # unknown / foreign / absent players -> 422
    for bad in (999999,):
        assert client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"player_id": bad}).status_code == 422
    db = SessionLocal()
    try:
        team = db.scalar(select(Team).where(Team.team_name == "Track A", Team.user_id == user_id(client, coach)))
        lonely = Player(team_id=team.team_id, first_name="No", last_name="Show", jersey_number=None)
        db.add(lonely)
        db.commit()
        lonely_id = lonely.player_id
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"player_id": lonely_id})
        assert r.status_code == 422 and "does not appear" in r.json()["detail"]
        # in the video's stats but no stored detection -> shirt-number tracking; no number -> 422
        db.add(PlayerMatchStat(player_id=lonely_id, match_id=db.get(MatchVideo, vid).match_id, video_id=vid))
        db.commit()
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"player_id": lonely_id})
        assert r.status_code == 422 and "pick a box" in r.json()["detail"]
        db.get(Player, lonely_id).jersey_number = 44
        db.commit()
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"player_id": lonely_id})
        assert r.status_code == 202 and r.json()["target"]["frame"] is None and r.json()["target"]["jersey_number"] == 44
        assert get_track(client, coach, r.json()["track_id"])["stats"]["jersey_number"] == 44
        client.delete(f"/api/tracks/{r.json()['track_id']}", headers=coach)
        db.query(PlayerMatchStat).filter(PlayerMatchStat.player_id == lonely_id).delete()
        db.query(Player).filter(Player.player_id == lonely_id).delete()
        db.commit()
    finally:
        db.close()
    # the rival can't target the coach's player (or video)
    rival_video = upload(client, rival, FAKE_MP4, home="Riv H", away="Riv A")
    r = client.post(f"/api/videos/{rival_video['id']}/tracks", headers=rival, json={"player_id": pid})
    assert r.status_code == 422 and "not found" in r.json()["detail"]
    tr = track_bbox(client, rival, rival_video["id"], frame=0, bbox=[0.1, 0.1, 0.1, 0.2], player_id=pid)
    assert tr["target"]["player_id"] is None   # foreign label dropped
    client.delete(f"/api/tracks/{tr['track_id']}", headers=rival)
    client.delete(f"/api/videos/{rival_video['id']}", headers=rival)


def test_isolation_other_user_gets_404(client, coach, rival, video):
    vid = video["id"]
    tr = track_bbox(client, coach, vid)
    tid = tr["track_id"]
    for method, url in [("get", f"/api/tracks/{tid}"), ("delete", f"/api/tracks/{tid}"),
                        ("get", f"/api/tracks/{tid}/frames"), ("get", f"/api/tracks/{tid}/annotated.mp4"),
                        ("get", f"/api/videos/{vid}/tracks"), ("get", f"/api/videos/{vid}/detections?frame=0"),
                        ("get", f"/api/videos/{vid}/frame?frame=0")]:
        assert getattr(client, method)(url, headers=rival).status_code == 404, url
    r = client.post(f"/api/videos/{vid}/tracks", headers=rival, json={"frame": 0, "bbox": [0.1, 0.1, 0.1, 0.2]})
    assert r.status_code == 404
    rid = user_id(client, rival)
    for ep in ("annotated.mp4", "frames"):
        assert client.get(f"/api/tracks/{tid}/{ep}?token={create_media_token(rid, f'track:{tid}')}").status_code == 404
    assert client.get(f"/api/videos/{vid}/frame?frame=0&token={create_media_token(rid, f'frame:{vid}')}"
                      ).status_code == 404
    assert get_track(client, coach, tid)["status"] == "done"   # untouched
    assert client.get(f"/api/tracks/{tid}").status_code == 401
    client.delete(f"/api/tracks/{tid}", headers=coach)


def test_one_active_track_per_video_and_409_when_not_processed(client, coach, video):
    vid = video["id"]
    db = SessionLocal()
    try:
        active = PlayerTrack(video_id=vid, user_id=user_id(client, coach), target_mode="jersey", jersey_number=4,
                             status="processing", stage="tracking", progress=40, fps=10.0, frame_count=N, width=W,
                             height=H)
        db.add(active)
        db.commit()
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"jersey_number": 5})
        assert r.status_code == 409, r.text
        assert r.json() == {"detail": "A track is already running for this video", "track_id": active.track_id,
                            "status": "processing", "progress": 40}
        tr = get_track(client, coach, active.track_id)
        assert (tr["status"], tr["stage"], tr["progress"], tr["annotated_url"], tr["summary"]) == \
            ("processing", "tracking", 40, None, None)
        assert tr["frames_url"].startswith(f"/api/tracks/{active.track_id}/frames?token=")
        r409 = client.get(tr["frames_url"])
        assert r409.status_code == 409 and r409.json()["detail"] == "Tracking not finished yet"
        assert client.get(f"/api/tracks/{active.track_id}/annotated.mp4", headers=coach).status_code == 409
        active.status = "failed"
        db.commit()
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"jersey_number": 5})
        assert r.status_code == 202   # failed tracks don't block
        client.delete(f"/api/tracks/{r.json()['track_id']}", headers=coach)
        client.delete(f"/api/tracks/{active.track_id}", headers=coach)
        v = db.get(MatchVideo, vid)
        v.processing_status, v.stage = "processing", "detect"
        db.commit()
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"jersey_number": 5})
        assert r.status_code == 409 and r.json()["detail"] == "Video not processed yet"
    finally:
        v = db.get(MatchVideo, vid)
        v.processing_status, v.stage = "done", "done"
        db.commit()
        db.close()


@pytest.mark.parametrize("body", [
    {}, {"t": 1}, {"frame": 3}, {"team": "A"}, {"bbox": [0.1, 0.1, 0.2, 0.2]},
    {"t": 1, "frame": 2, "bbox": [0.1, 0.1, 0.2, 0.2]}, {"frame": 1, "bbox": [0.1, 0.1, 0, 0.2]},
    {"frame": 1, "bbox": [0.1, 0.1, 0.2]}, {"frame": 1, "bbox": "0.1,0.1,0.2,0.2"},
    {"frame": 1, "bbox": [100, 80, 130, 150]}, {"frame": 1, "bbox": [0.9, 0.1, 0.2, 0.2]},
    {"frame": 1, "bbox": [-0.1, 0.1, 0.2, 0.2]}, {"jersey_number": 100}, {"jersey_number": 7, "team": "C"},
    {"jersey_number": "7"}, {"player_id": 0}, {"player_id": "3"}, {"t": -1, "bbox": [0.1, 0.1, 0.2, 0.2]},
    {"frame": 1.5, "bbox": [0.1, 0.1, 0.2, 0.2]}, {"frame": -1, "jersey_number": 3},
])
def test_create_track_422_bad_body(client, coach, video, body):
    r = client.post(f"/api/videos/{video['id']}/tracks", headers=coach, json=body)
    assert r.status_code == 422, (body, r.text)


def test_create_track_422_outside_clip_and_404(client, coach, video):
    vid = video["id"]
    for body in ({"t": SECONDS + 5, "bbox": [0.1, 0.1, 0.2, 0.2]}, {"frame": N + 3, "bbox": [0.1, 0.1, 0.2, 0.2]},
                 {"frame": 0, "bbox": [0.5, 0.5, 0.003, 0.003]}, {"frame": N + 3, "jersey_number": 4}):
        r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json=body)
        assert r.status_code == 422, (body, r.text)
    for q in ("t=99", "frame=999", "t=1&frame=2", "t=-1", "t=abc"):
        assert client.get(f"/api/videos/{vid}/detections?{q}", headers=coach).status_code == 422, q
    assert client.get(f"/api/videos/{vid}/detections", headers=coach).json()["frame"] == 0   # default frame 0
    assert client.get("/api/videos/999999/detections?frame=0", headers=coach).status_code == 404
    r = client.post("/api/videos/999999/tracks", headers=coach, json={"jersey_number": 1})
    assert r.status_code == 404 and r.json() == {"detail": "Video not found"}
    assert client.get("/api/tracks/999999", headers=coach).json() == {"detail": "Track not found"}


def test_unreadable_upload_uses_synthetic_canvas(client, coach):
    """Fake bytes (the other tests' FAKE_MP4): stub still produces a JPEG and a playable video, with a warning."""
    v = upload(client, coach, FAKE_MP4, home="Fake H", away="Fake A")
    d = client.get(f"/api/videos/{v['id']}/detections?frame=0", headers=coach).json()
    assert (d["width"], d["height"]) == (1920, 1080)       # from the stub's pipeline_meta
    assert client.get(d["frame_url"]).content[:2] == b"\xff\xd8"
    tr = track_bbox(client, coach, v["id"], frame=5, bbox=d["players"][-1]["bbox"])
    done = get_track(client, coach, tr["track_id"])
    assert done["status"] == "done", done
    assert any("could not be decoded" in w for w in done["warnings"])
    body = client.get(done["annotated_url"]).content
    assert body.find(b"ftyp") == 4
    assert len(frames_of(client, done)["frames"]) == done["frame_count"]


def test_video_delete_removes_tracks_and_cached_frames(client, coach, clip):
    v = upload(client, coach, clip, home="Del H", away="Del A")
    client.get(f"/api/videos/{v['id']}/detections?t=0.5", headers=coach)
    tr = track_bbox(client, coach, v["id"])
    assert trk.job_dir(tr["track_id"]).is_dir() and trk.frames_dir(v["id"]).is_dir()
    assert client.delete(f"/api/videos/{v['id']}", headers=coach).status_code == 204
    assert not trk.job_dir(tr["track_id"]).exists() and not trk.frames_dir(v["id"]).exists()
    assert client.get(f"/api/tracks/{tr['track_id']}", headers=coach).status_code == 404
    db = SessionLocal()
    try:
        assert db.get(PlayerTrack, tr["track_id"]) is None
    finally:
        db.close()


def test_track_deleted_while_running_stops_cleanly(client, coach, video, monkeypatch):
    calls = []

    def fake_stub(video_, geo, target, out_dir, progress):
        calls.append(1)
        db = SessionLocal()
        db.query(PlayerTrack).filter(PlayerTrack.video_id == video_.video_id,
                                     PlayerTrack.status == "processing").delete()
        db.commit()
        db.close()
        progress("tracking", 50)   # -> JobDeleted
    monkeypatch.setattr(trk, "_stub_track", fake_stub)
    tr = track_bbox(client, coach, video["id"])
    assert calls and client.get(f"/api/tracks/{tr['track_id']}", headers=coach).status_code == 404
    assert not trk.job_dir(tr["track_id"]).exists()


def test_interrupted_tracks_are_failed_on_startup(client, coach, video):
    db = SessionLocal()
    try:
        tr = PlayerTrack(video_id=video["id"], user_id=user_id(client, coach), target_mode="jersey",
                         jersey_number=3, status="queued")
        db.add(tr)
        db.commit()
        assert trk.fail_interrupted_tracks() >= 1
        out = get_track(client, coach, tr.track_id)
        assert out["status"] == "failed" and out["stage"] == "failed" and out["error_code"] == "interrupted"
        client.delete(f"/api/tracks/{tr.track_id}", headers=coach)
    finally:
        db.close()


def test_503_before_migration_008(client, coach, video, monkeypatch):
    monkeypatch.setattr(trk, "has_track_table", lambda db: False)
    r = client.post(f"/api/videos/{video['id']}/tracks", headers=coach, json={"jersey_number": 1})
    assert r.status_code == 503 and "008" in r.json()["detail"]
    assert client.get(f"/api/videos/{video['id']}/tracks", headers=coach).status_code == 503
    assert client.get("/api/tracks/1", headers=coach).status_code == 503
    assert client.get(f"/api/videos/{video['id']}/detections?frame=0", headers=coach).status_code == 200  # no table
    assert client.get(f"/api/videos/{video['id']}/stats", headers=coach).status_code == 200
    assert client.get(f"/api/videos/{video['id']}", headers=coach).json()["source_url"]


def test_stage_names(client, coach, video, monkeypatch):
    seen = []
    orig = trk.set_track_progress
    monkeypatch.setattr(trk, "set_track_progress", lambda j, s, p: seen.append(s) or orig(j, s, p))
    tr = track_bbox(client, coach, video["id"])
    assert get_track(client, coach, tr["track_id"])["stage"] == "done"
    stages = [s for i, s in enumerate(seen) if i == 0 or seen[i - 1] != s]
    assert stages == ["tracking", "rendering"], seen
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)


def test_track_mode_never_silently_stubs(client, coach, video, tmp_root, monkeypatch):
    """auto/real never fall back to fake tracks: missing CV modules -> cv_unavailable. Only explicit stub fakes."""
    root = tmp_root / "cv-main-without-tracking"
    (root / "cv").mkdir(parents=True, exist_ok=True)
    (root / "cv" / "run_pipeline.py").write_text("")
    monkeypatch.setattr(settings, "CV_PIPELINE_PATH", root / "cv" / "run_pipeline.py")
    monkeypatch.setattr(settings, "CV_PIPELINE_MODE", "real")
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", True)
    for m in ("auto", "real", "", "AUTO"):
        monkeypatch.setattr(settings, "TRACK_PIPELINE_MODE", m)
        assert trk.track_mode("track_player") == "real" and trk.track_mode("detect_frame") == "real"
    monkeypatch.setattr(settings, "TRACK_PIPELINE_MODE", "auto")
    r = client.get(f"/api/videos/{video['id']}/detections?t=2.5", headers=coach)
    assert r.status_code == 503
    monkeypatch.setattr(settings, "TRACK_PIPELINE_MODE", "stub")
    assert trk.track_mode("track_player") == "stub"
    r = client.get(f"/api/videos/{video['id']}/detections?t=2.5", headers=coach)
    assert r.status_code == 200 and r.json()["source"] == "stub"


# ------------------------------------------------------------------ real mode (fake CV package)
def test_real_mode_command_building(monkeypatch, tmp_root):
    monkeypatch.setattr(settings, "CV_PYTHON", "/opt/cv/bin/python")
    monkeypatch.setattr(settings, "CV_DEVICE", "mps")
    monkeypatch.setattr(settings, "CV_MODEL", "yolov8m.pt")
    monkeypatch.setattr(settings, "CV_CALIBRATION_PATH", tmp_root / "cal.json")
    v, out = tmp_root / "v.mp4", tmp_root / "o"
    assert trk.build_detect_frame_cmd(v, 1.25, out) == [
        "/opt/cv/bin/python", "-m", "cv.detect_frame", "--video", str(v.resolve()), "--t", "1.250",
        "--out", str(out.resolve()), "--device", "mps", "--model", "yolov8m.pt"]
    base = ["/opt/cv/bin/python", "-m", "cv.track_player", "--video", str(v.resolve()), "--out", str(out.resolve()),
            "--device", "mps"]
    tail = ["--model", "yolov8m.pt", "--calibration", str((tmp_root / "cal.json").resolve())]
    assert trk.build_track_player_cmd(v, out, trk.Target("bbox", 12, (10.0, 20.5, 40.25, 99.999))) == \
        base + ["--frame", "12", "--bbox", "10,20.5,40.25,100"] + tail
    assert trk.build_track_player_cmd(v, out, trk.Target("jersey", jersey_number=7, team="B")) == \
        base + ["--jersey", "7", "--team", "B"] + tail
    monkeypatch.setattr(settings, "CV_MODEL", "")
    monkeypatch.setattr(settings, "CV_CALIBRATION_PATH", None)
    assert trk.build_track_player_cmd(v, out, trk.Target("jersey", jersey_number=7, team="B")) == \
        base + ["--jersey", "7", "--team", "B"]
    assert trk.build_track_player_cmd(v, out, trk.Target("jersey", jersey_number=7)) == base + ["--jersey", "7"]


FAKE_DETECT = '''
import argparse, json, pathlib, shutil, subprocess
p = argparse.ArgumentParser()
for a in ("--video", "--t", "--out", "--device", "--model"):
    p.add_argument(a)
a = p.parse_args()
out = pathlib.Path(a.out)
(out / "args.json").write_text(json.dumps(vars(a)))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", a.t, "-i", a.video, "-frames:v", "1", str(out / "frame.jpg")],
               check=True)
frame = int(round(float(a.t) * 10))
json.dump({"frame": frame, "t": float(a.t), "width": 320, "height": 240, "candidates": [
    {"bbox": [10, 20, 40, 100], "confidence": 0.91, "team": "A", "jersey_number": 9, "class": "player"},
    {"bbox_x1": 50, "bbox_y1": 60, "bbox_x2": 80, "bbox_y2": 140, "confidence": 0.5, "team": 1,
     "jersey_number": None, "class": "goalkeeper"},
    {"bbox": [5, 5, 1, 1], "confidence": 0.9},
    {"bbox": [100, 20, 130, 90], "confidence": 1.7, "team": "x", "jersey_number": 123}]}, open(out / "candidates.json", "w"))
'''

FAKE_TRACK = '''
import argparse, json, pathlib, shutil, sys
p = argparse.ArgumentParser()
for a in ("--video", "--out", "--device", "--frame", "--bbox", "--jersey", "--team", "--model", "--calibration"):
    p.add_argument(a)
a = p.parse_args()
out = pathlib.Path(a.out)
(out / "args.json").write_text(json.dumps(vars(a)))
if a.jersey == "99":
    print("target not found", flush=True)
    sys.exit(3)
if a.jersey == "98":
    print("boom: CUDA out of memory", flush=True)
    sys.exit(1)
for pct in (0, 50, 100):
    print(f"Processing frames: {pct}%", flush=True)
frames = [
    {"frame": 0, "t": 0.0, "bbox": [10, 20, 40, 100], "confidence": 0.9, "status": "tracked", "state": "tracked",
     "pitch_x": 10.123, "pitch_y": 20.456},
    {"frame": 1, "t": 0.1, "bbox": [11, 20, 41, 100], "confidence": 0.8, "status": "interpolated", "state": "occluded"},
    {"frame": 2, "t": 0.2, "bbox": [12, 20, 42, 100], "confidence": 0.7, "status": "tracked", "state": "lost"},
    {"frame": 3, "t": 0.3, "bbox": None, "confidence": None, "status": "lost", "state": "occluded"},
    {"frame": 4, "t": 0.4, "bbox": [14, 20, 44, 100], "confidence": 0.85, "status": "lost", "state": "reacquired"},
    {"frame": 5, "t": 0.5, "bbox": [15, 20, 45, 100], "confidence": 0.8, "status": "interpolated"},
    {"frame": 6, "t": 0.6, "bbox": [16, 20, 46, 100], "confidence": 0.8, "status": "lost"},
    {"frame": 7, "bbox": [17, 20, 47, 100], "confidence": 0.8, "status": "weird", "state": "dancing"},
    {"t": 0.8, "bbox": [1, 2, 3, 4]},
]
json.dump({"schema_version": "1.0", "fps": 10, "width": 320, "height": 240, "total_frames": 40,
           "target": {"jersey_number": int(a.jersey) if a.jersey else 9, "team": a.team or "A",
                      "init_frame": int(a.frame or 0), "player_uid": "p-42", "track_ids": [3, 17]},
           "frames": frames}, open(out / "track.json", "w"))
json.dump({"pipeline_version": "2.1.0", "tracker": "botsort+reid", "coverage_pct": 62.5, "lost_frames": 2,
           "warnings": ["low light"], "reacquisition_count": 1, "lost_segments": [[2, 3]]}, open(out / "meta.json", "w"))
json.dump({"jersey_number": 9, "distance_km": 0.031, "top_speed_kmh": 24.1, "minutes_played_s": 4.0,
           "player_uid": "p-42", "contributing_track_ids": [3, 17]}, open(out / "target_stats.json", "w"))
shutil.copy(a.video, out / "replay.mp4")
'''


@pytest.fixture()
def fake_cv(tmp_root, monkeypatch):
    root = tmp_root / "fake-cv-repo"
    (root / "cv").mkdir(parents=True, exist_ok=True)
    (root / "cv" / "__init__.py").write_text("")
    (root / "cv" / "detect_frame.py").write_text(textwrap.dedent(FAKE_DETECT))
    (root / "cv" / "track_player.py").write_text(textwrap.dedent(FAKE_TRACK))
    monkeypatch.setattr(settings, "CV_PIPELINE_PATH", root / "cv" / "run_pipeline.py")
    monkeypatch.setattr(settings, "TRACK_PIPELINE_MODE", "auto")
    monkeypatch.setattr(settings, "CV_PYTHON", sys.executable)
    monkeypatch.setattr(settings, "CV_DEVICE", "cpu")
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)   # irrelevant: auto picks real because both modules exist
    return root


FAKE_DETECT = '''
import argparse, json, pathlib, shutil, subprocess
p = argparse.ArgumentParser()
for a in ("--video", "--t", "--out", "--device", "--model"):
    p.add_argument(a)
a = p.parse_args()
out = pathlib.Path(a.out)
(out / "args.json").write_text(json.dumps(vars(a)))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", a.t, "-i", a.video, "-frames:v", "1", str(out / "frame.jpg")],
               check=True)
frame = int(round(float(a.t) * 10))
json.dump({"frame": frame, "t": float(a.t), "width": 320, "height": 240, "candidates": [
    {"bbox": [10, 20, 40, 100], "confidence": 0.91, "team": "A", "jersey_number": 9, "class": "player"},
    {"bbox_x1": 50, "bbox_y1": 60, "bbox_x2": 80, "bbox_y2": 140, "confidence": 0.5, "team": 1,
     "jersey_number": None, "class": "goalkeeper"},
    {"bbox": [5, 5, 1, 1], "confidence": 0.9},
    {"bbox": [100, 20, 130, 90], "confidence": 1.7, "team": "x", "jersey_number": 123}]}, open(out / "candidates.json", "w"))
'''

FAKE_TRACK = '''
import argparse, json, pathlib, shutil, sys
p = argparse.ArgumentParser()
for a in ("--video", "--out", "--device", "--frame", "--bbox", "--jersey", "--team", "--model", "--calibration"):
    p.add_argument(a)
a = p.parse_args()
out = pathlib.Path(a.out)
(out / "args.json").write_text(json.dumps(vars(a)))
if a.jersey == "99":
    print("target not found", flush=True)
    sys.exit(3)
if a.jersey == "98":
    print("boom: CUDA out of memory", flush=True)
    sys.exit(1)
for pct in (0, 50, 100):
    print(f"Processing frames: {pct}%", flush=True)
frames = [
    {"frame": 0, "t": 0.0, "bbox": [10, 20, 40, 100], "confidence": 0.9, "status": "tracked", "state": "tracked",
     "pitch_x": 10.123, "pitch_y": 20.456},
    {"frame": 1, "t": 0.1, "bbox": [11, 20, 41, 100], "confidence": 0.8, "status": "interpolated", "state": "occluded"},
    {"frame": 2, "t": 0.2, "bbox": [12, 20, 42, 100], "confidence": 0.7, "status": "tracked", "state": "lost"},
    {"frame": 3, "t": 0.3, "bbox": None, "confidence": None, "status": "lost", "state": "occluded"},
    {"frame": 4, "t": 0.4, "bbox": [14, 20, 44, 100], "confidence": 0.85, "status": "lost", "state": "reacquired"},
    {"frame": 5, "t": 0.5, "bbox": [15, 20, 45, 100], "confidence": 0.8, "status": "interpolated"},
    {"frame": 6, "t": 0.6, "bbox": [16, 20, 46, 100], "confidence": 0.8, "status": "lost"},
    {"frame": 7, "bbox": [17, 20, 47, 100], "confidence": 0.8, "status": "weird", "state": "dancing"},
    {"t": 0.8, "bbox": [1, 2, 3, 4]},
]
json.dump({"schema_version": "1.0", "fps": 10, "width": 320, "height": 240, "total_frames": 40,
           "target": {"jersey_number": int(a.jersey) if a.jersey else 9, "team": a.team or "A",
                      "init_frame": int(a.frame or 0), "player_uid": "p-42", "track_ids": [3, 17]},
           "frames": frames}, open(out / "track.json", "w"))
json.dump({"pipeline_version": "2.1.0", "tracker": "botsort+reid", "coverage_pct": 62.5, "lost_frames": 2,
           "warnings": ["low light"], "reacquisition_count": 1, "lost_segments": [[2, 3]]}, open(out / "meta.json", "w"))
json.dump({"jersey_number": 9, "distance_km": 0.031, "top_speed_kmh": 24.1, "minutes_played_s": 4.0,
           "player_uid": "p-42", "contributing_track_ids": [3, 17]}, open(out / "target_stats.json", "w"))
shutil.copy(a.video, out / "replay.mp4")
'''


@pytest.fixture()
def fake_cv(tmp_root, monkeypatch):
    root = tmp_root / "fake-cv-repo"
    (root / "cv").mkdir(parents=True, exist_ok=True)
    (root / "cv" / "__init__.py").write_text("")
    (root / "cv" / "detect_frame.py").write_text(textwrap.dedent(FAKE_DETECT))
    (root / "cv" / "track_player.py").write_text(textwrap.dedent(FAKE_TRACK))
    monkeypatch.setattr(settings, "CV_PIPELINE_PATH", root / "cv" / "run_pipeline.py")
    monkeypatch.setattr(settings, "TRACK_PIPELINE_MODE", "auto")
    monkeypatch.setattr(settings, "CV_PYTHON", sys.executable)
    monkeypatch.setattr(settings, "CV_DEVICE", "cpu")
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)   # irrelevant: auto picks real because both modules exist
    return root


def test_real_mode_with_fake_cv_extras(client, coach, video, fake_cv):
    vid = video["id"]
    assert trk.track_mode("track_player") == "real" and trk.track_mode("detect_frame") == "real"
    d = client.get(f"/api/videos/{vid}/detections?t=3.3", headers=coach).json()
    assert (d["frame"], d["t"], d["source"]) == (33, 3.3, "real")
    args = json.loads((trk.frame_cache_dir(vid, 33) / "args.json").read_text())
    assert args["t"] == "3.300" and args["device"] == "cpu" and Path(args["video"]).is_absolute()
    n = lambda b: trk.px_to_norm(b, W, H)  # noqa: E731
    expected = [
        {"player_id": None, "jersey_number": 9, "team": "A", "class": "player", "bbox": n([10, 20, 40, 100]),
         "conf": 0.91},
        {"player_id": None, "jersey_number": None, "team": "B", "class": "goalkeeper", "bbox": n([50, 60, 80, 140]),
         "conf": 0.5},
        {"player_id": None, "jersey_number": None, "team": None, "class": "player", "bbox": n([100, 20, 130, 90]),
         "conf": 1.0}]
    assert len(d["players"]) == len(expected)
    for got, exp in zip(d["players"], expected):
        assert {k: got[k] for k in exp} == exp
        assert got["bbox_xyxy"] and got["x_center"] is not None
    assert client.get(d["frame_url"]).content[:2] == b"\xff\xd8"

    tr = track_bbox(client, coach, vid, frame=33, bbox=n([10, 20, 40, 100]))
    done = get_track(client, coach, tr["track_id"])
    assert done["status"] == "done" and done["source"] == "real", done
    args = json.loads((trk.job_dir(tr["track_id"]) / "args.json").read_text())
    assert (args["frame"], args["bbox"], args["jersey"], args["team"], args["device"]) == \
        ("33", "10,20,40,100", None, None, "cpu")
    assert done["stats"] == {"jersey_number": 9, "distance_km": 0.031, "top_speed_kmh": 24.1, "minutes_played_s": 4.0,
                             "player_uid": "p-42", "contributing_track_ids": [3, 17]}
    s = done["summary"]
    assert (s["tracked_frames"], s["occluded_frames"], s["lost_frames"], s["avg_conf"]) == (3, 2, 35, 0.85)
    assert (s["reacquisition_count"], s["lost_segments"], s["coverage_pct"], s["player_uid"], s["track_ids"],
            s["schema_version"], s["pipeline_version"], s["tracker"]) == \
        (1, [[2, 3]], 62.5, "p-42", [3, 17], "1.0", "2.1.0", "botsort+reid")
    assert done["warnings"] == ["low light"]
    assert (done["frame_count"], done["fps"], done["width"], done["height"]) == (40, 10.0, W, H)
    assert done["target"]["jersey_number"] == 9 and done["target"]["team"] == "A"
    t = frames_of(client, done)
    assert t["frame_count"] == 40 and [f["f"] for f in t["frames"]] == list(range(40))
    got = {f["f"]: (f["state"], f["bbox"] is not None) for f in t["frames"][:8]}
    assert got == {
        0: ("tracked", True),
        1: ("occluded", True),    # state occluded + bbox
        2: ("lost", False),       # state lost wins over status tracked; bbox dropped
        3: ("lost", False),       # occluded without bbox
        4: ("tracked", True),     # reacquired -> tracked
        5: ("occluded", True),    # no state: status interpolated -> occluded
        6: ("lost", False),       # status lost -> bbox null
        7: ("tracked", True),     # unknown status/state with a bbox -> tracked
    }
    assert all(f["state"] == "lost" and f["bbox"] is None for f in t["frames"][8:])   # missing -> lost (dense)
    f0 = t["frames"][0]
    assert (f0["pitch_x"], f0["pitch_y"], f0["conf"]) == (10.12, 20.46, 0.9) and f0["bbox"] == n([10, 20, 40, 100])
    assert t["frames"][2]["conf"] == 0 and t["frames"][7]["t"] == 0.7 and t["frames"][1]["conf"] == 0.8
    assert client.get(done["annotated_url"], headers={"Range": "bytes=0-9"}).status_code == 206
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)

    # jersey path args (team optional), exit code 3 -> target_not_found, other exit -> cv_failed with the log tail
    r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"jersey_number": 99})
    failed = get_track(client, coach, r.json()["track_id"])
    args = json.loads((trk.job_dir(failed["track_id"]) / "args.json").read_text())
    assert (args["jersey"], args["team"], args["frame"], args["bbox"]) == ("99", None, None, None)
    assert failed["status"] == "failed" and failed["error_code"] == "target_not_found", failed
    assert failed["error_message"].startswith("target_not_found: ") and failed["annotated_url"] is None
    t409 = client.get(failed["frames_url"])
    assert t409.status_code == 409 and t409.json()["error_code"] == "target_not_found"
    client.delete(f"/api/tracks/{failed['track_id']}", headers=coach)
    r = client.post(f"/api/videos/{vid}/tracks", headers=coach, json={"jersey_number": 98, "team": "A"})
    failed = get_track(client, coach, r.json()["track_id"])
    args = json.loads((trk.job_dir(failed["track_id"]) / "args.json").read_text())
    assert args["team"] == "A"
    assert failed["error_code"] == "cv_failed" and "CUDA out of memory" in failed["error_message"]
    client.delete(f"/api/tracks/{failed['track_id']}", headers=coach)


def test_real_mode_explicit_without_modules_fails_clearly(client, coach, video, tmp_root, monkeypatch):
    monkeypatch.setattr(settings, "TRACK_PIPELINE_MODE", "real")
    monkeypatch.setattr(settings, "CV_PIPELINE_PATH", tmp_root / "empty-repo" / "cv" / "run_pipeline.py")
    tr = track_bbox(client, coach, video["id"])
    done = get_track(client, coach, tr["track_id"])
    assert done["error_code"] == "cv_unavailable" and "cv.track_player" in done["error_message"]
    assert client.get(f"/api/videos/{video['id']}/detections?t=3.9", headers=coach).status_code == 503
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)


def test_progress_parsing_from_cv_output(client, coach, video, fake_cv, monkeypatch):
    seen = []
    orig = trk.set_track_progress
    monkeypatch.setattr(trk, "set_track_progress", lambda j, s, p: seen.append((s, p)) or orig(j, s, p))
    slow = FAKE_TRACK.replace('for pct in (0, 50, 100):\n    print(f"Processing frames: {pct}%", flush=True)',
                              'import time\nfor pct in (0, 50, 100):\n    print(f"Processing frames: {pct}%", flush=True)\n'
                              '    time.sleep(1.2)')
    (fake_cv / "cv" / "track_player.py").write_text(textwrap.dedent(slow))
    tr = track_bbox(client, coach, video["id"])
    assert get_track(client, coach, tr["track_id"])["status"] == "done"
    pcts = [p for s, p in seen if s == "tracking"]
    assert pcts and max(pcts) >= 50 and pcts == sorted(pcts)
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)


# ------------------------------------------------------------------ v0.5.1: re-acquisitions are events, not frames
def _run_reader(tmp_root, name, states, meta=None, total=None):
    out = tmp_root / f"reacq-{name}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    frames = [{"frame": i, "bbox": None if s == "lost" else [10, 10, 40, 90], "confidence": 0.8, "state": s}
              for i, s in enumerate(states)]
    (out / "track.json").write_text(json.dumps({"fps": 10, "width": W, "height": H,
                                                "total_frames": total or len(states), "frames": frames}))
    (out / "replay.mp4").write_bytes(b"x")
    if meta is not None:
        (out / "meta.json").write_text(json.dumps(meta))
    geo = trk.Geometry(W, H, 10.0, len(states) / 10, len(states), True)
    api, meta_out, _ = trk.read_track_output(out, geo, 1, 1, "stub")
    return api["summary"]


T, O, L = "tracked", "occluded", "lost"


@pytest.mark.parametrize("states, events, segments", [
    ([T] * 20, 0, []),                                                   # no lost segment -> 0
    ([T] * 5 + [L] * 134 + [T] * 5, 1, [[5, 138]]),                      # the bug report: 1 segment -> 1, not 134
    ([T] * 5 + [O] * 2 + [L] * 10 + [O] * 2 + [T] * 5, 1, [[7, 16]]),    # lost/occluded gap -> 1
    ([T] * 5 + [L] * 10, 0, [[5, 14]]),                                  # trailing lost, never recovered -> 0
    ([L] * 3 + [T] * 5, 1, [[0, 2]]),                                    # starts lost, then found -> 1
    ([T] * 3 + [L] * 3 + [T] * 3 + [L] * 3 + [T] * 3, 2, [[3, 5], [9, 11]]),
    ([T] * 3 + [L] * 3 + [T] * 3 + [L] * 3, 1, [[3, 5], [9, 11]]),       # 2 segments, only the first recovers
    ([T] * 3 + [L] * 2 + [O] + [L] * 2 + [T] * 3, 1, [[3, 4], [6, 7]]),  # one gap, two lost runs -> 1 event
    ([T] * 3 + [O] * 4 + [T] * 3, 0, []),                                # occluded only: no re-acquisition
    ([T] * 3 + [L] * 3 + ["reacquired"] + [T] * 3, 1, [[3, 5]]),         # CV 'reacquired' state = tracked
])
def test_reacquisition_counts_events_not_frames(tmp_root, states, events, segments):
    s = _run_reader(tmp_root, f"{len(states)}-{events}", states)
    assert s["reacquisition_count"] == events and s["lost_segments"] == segments
    assert trk.reacquisition_events(states) == events
    n_lost = sum(st == L for st in states)
    assert s["lost_frames"] == n_lost and s["tracked_frames"] + s["occluded_frames"] + s["lost_frames"] == len(states)
    assert s["coverage_pct"] == round((len(states) - n_lost) / len(states) * 100, 1)


def test_cv_meta_reacquisition_count_and_segments_win_when_valid(tmp_root):
    states = [T] * 5 + [L] * 10 + [T] * 5
    s = _run_reader(tmp_root, "meta", states, meta={"reacquisition_count": 3, "lost_segments": [[5, 14]]})
    assert (s["reacquisition_count"], s["lost_segments"]) == (3, [[5, 14]])
    s = _run_reader(tmp_root, "meta0", states, meta={"reacquisition_count": 0})
    assert s["reacquisition_count"] == 0
    for bad in ([[5, 99]], [[9, 5]], [[-1, 3]], [["a", 3]], [[1, 2, 3]], "5-14"):   # unusable -> computed
        s = _run_reader(tmp_root, "badseg", states, meta={"reacquisition_count": -2, "lost_segments": bad})
        assert (s["reacquisition_count"], s["lost_segments"]) == (1, [[5, 14]]), bad
    # missing frames are filled in as lost (dense), so a CV that stops early has a trailing unrecovered segment
    s = _run_reader(tmp_root, "short", [T] * 5, total=8)
    assert (s["lost_frames"], s["lost_segments"], s["reacquisition_count"], s["coverage_pct"]) == (3, [[5, 7]], 0, 62.5)


def test_stub_track_reacquisitions_match_recovered_segments(client, coach, video):
    tr = track_bbox(client, coach, video["id"])
    done = get_track(client, coach, tr["track_id"])
    s = done["summary"]
    frames = frames_of(client, done)["frames"]
    recovered = sum(1 for a, b in s["lost_segments"] if any(f["state"] == "tracked" for f in frames[b + 1:]))
    assert s["lost_segments"] and s["reacquisition_count"] == recovered <= len(s["lost_segments"])
    raw = json.loads((trk.job_dir(tr["track_id"]) / "track.json").read_text())
    assert sum(f["state"] == "reacquired" for f in raw["frames"]) == recovered     # one flagged frame per event
    assert json.loads((trk.job_dir(tr["track_id"]) / "meta.json").read_text())["reacquisition_count"] == recovered
    client.delete(f"/api/tracks/{tr['track_id']}", headers=coach)
