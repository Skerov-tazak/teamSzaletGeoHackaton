"""
python manage.py engine_mock_api [--port 8001]

DEVELOPMENT ONLY: a stand-in for the platform API (Jan + Szymek) so the map can be built before the real
endpoints exist. It serves exactly the URLs and response shapes agreed in docs/interfaces.md ("Platform API"),
including the general rules (no data after today + 7, `{"detail": ...}` errors), from the real database:

    GET  /api/health/                     {status, database}
    GET  /api/clock/                      {today, forecast_days}
    PUT  /api/clock/  {"today"}           saves the Clock, then engine.clock_moved(old, new); same shape as GET
    GET  /api/threats/                    [{code, name, crop: {code, name}, category}]
    GET  /api/fields/                     GeoJSON FeatureCollection
    GET  /api/fields/{id}/                details, crop history, soil
    GET  /api/risks/?date=                {date, risks: [{field_id, threat_code, score}]}
    GET  /api/fields/{id}/risks/?from=&to=          {field_id, from, to, threats: [{threat_code, points}]}
    GET  /api/fields/{id}/risks/{date}/   {field_id, date, risks: [{threat, score, explanation}]}

Plus the map's development page at / (frontend/src/map/dev/index.html) and /static/frontend/... from
frontend/static/frontend. It is not wired into Django's URLs and never runs in the demo: once the platform
API exists, the same page and map run against it unchanged. Where interfaces.md leaves a default open, this
follows docs/implementation-plan.md (feature-frontend): default `from` = 1 September of the year before the
demo year; any valid date is accepted by PUT /api/clock/; a missing Clock row is a 503.
"""

from __future__ import annotations

import json
import mimetypes
import re
from collections import Counter
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core import clock
from core.models import Clock, Field, Risk, Threat

FRONTEND = Path(settings.BASE_DIR) / "frontend"
DEV_PAGE = FRONTEND / "src" / "map" / "dev" / "index.html"
STATIC_ROOT = FRONTEND / "static" / "frontend"
SOIL_KEYS = ("ph", "clay", "sand", "silt", "om", "cec", "bulk_density")


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _today() -> date:
    try:
        return clock.today()
    except clock.ClockNotSetError:
        raise ApiError(503, "The demo date is not set: set it in /admin/ or run the seed.") from None


def _horizon() -> date:
    return _today() + timedelta(days=clock.FORECAST_DAYS)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: str, name: str) -> date:
    """Exactly YYYY-MM-DD (implementation plan A0), else 400."""
    try:
        if not DATE_RE.match(value or ""):
            raise ValueError(value)
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be YYYY-MM-DD") from None


def _single_date(value: str | None) -> date:
    d = _parse_date(value, "date") if value else _today()
    if d > _horizon():
        raise ApiError(400, "date is after today + 7")
    return d


def _field(pk: str) -> Field:
    try:
        return Field.objects.select_related("crop").get(pk=int(pk))
    except (Field.DoesNotExist, ValueError):
        raise ApiError(404, "Not found.") from None


def _crop(c) -> dict | None:
    return {"code": c.code, "name": c.name} if c else None


# --- endpoints ------------------------------------------------------------------------------------

def health(_q, _b):
    return {"status": "ok", "database": True}


def clock_get(_q, _b):
    return {"today": _today().isoformat(), "forecast_days": clock.FORECAST_DAYS}


def clock_put(_q, body):
    from engine import clock_moved

    if not isinstance(body, dict) or "today" not in body:
        raise ApiError(400, "today: this field is required")
    new = _parse_date(body.get("today"), "today")
    row = Clock.objects.filter(pk=1).first()
    old = row.today if row else None
    row = row or Clock(pk=1)
    row.today = new
    row.save()
    if old and old != new:
        clock_moved(old, new)  # the platform's PUT does the same (engine/README.md: "When and how to run it")
    return clock_get(None, None)


def threats(_q, _b):
    rows = Threat.objects.select_related("crop").order_by("crop_id", "code")
    return [{"code": t.code, "name": t.name, "crop": _crop(t.crop), "category": t.category} for t in rows]


def fields(_q, _b):
    feats = []
    for f in Field.objects.select_related("crop").order_by("id"):
        feats.append({"type": "Feature", "id": f.id, "geometry": f.geometry,
                      "properties": {"id": f.id, "name": f.name, "crop": _crop(f.crop), "area_ha": f.area_ha}})
    return {"type": "FeatureCollection", "features": feats}


def field_detail(_q, _b, pk):
    f = _field(pk)
    years: dict[int, list] = {}
    for y in f.crop_years.select_related("crop_class").order_by("year", "-share"):
        years.setdefault(y.year, []).append({"code": y.crop_class.code, "name": y.crop_class.name, "share": y.share})
    cells = list(f.soil_cells().values(*SOIL_KEYS, "soil_texture"))
    soil = None
    if cells:
        soil = {}
        for k in SOIL_KEYS:
            vals = [c[k] for c in cells if c[k] is not None]
            soil[k] = sum(vals) / len(vals) if vals else None
        textures = Counter(c["soil_texture"] for c in cells if c["soil_texture"])
        soil["soil_texture"] = textures.most_common(1)[0][0] if textures else None
    return {"id": f.id, "name": f.name, "crop": _crop(f.crop), "area_ha": f.area_ha,
            "centroid": {"lat": f.centroid_lat, "lon": f.centroid_lon}, "weather_grid_id": f.weather_grid_id,
            "crop_history": [{"year": y, "classes": c} for y, c in sorted(years.items())], "soil": soil}


def risks_day(q, _b):
    d = _single_date(q.get("date"))
    rows = Risk.objects.filter(date=d).order_by("field_id", "threat__code").values_list("field_id", "threat__code", "score")
    return {"date": d.isoformat(), "risks": [{"field_id": f, "threat_code": c, "score": s} for f, c, s in rows]}


def field_risks(q, _b, pk):
    f = _field(pk)
    today, horizon = _today(), _horizon()
    start = _parse_date(q["from"], "from") if q.get("from") else date(today.year - 1, 9, 1)
    end = min(_parse_date(q["to"], "to") if q.get("to") else horizon, horizon)
    if start > end:
        raise ApiError(400, "from is after to")
    series: dict[str, list] = {}
    for code, d, s in (Risk.objects.filter(field=f, date__range=(start, end))
                       .order_by("threat__code", "date").values_list("threat__code", "date", "score")):
        series.setdefault(code, []).append({"date": d.isoformat(), "score": s})
    return {"field_id": f.id, "from": start.isoformat(), "to": end.isoformat(),
            "threats": [{"threat_code": c, "points": p} for c, p in series.items()]}


def field_day(_q, _b, pk, day):
    f = _field(pk)
    d = _single_date(day)
    rows = Risk.objects.filter(field=f, date=d).select_related("threat").order_by("-score", "threat__code")
    return {"field_id": f.id, "date": d.isoformat(),
            "risks": [{"threat": {"code": r.threat.code, "name": r.threat.name, "category": r.threat.category},
                       "score": r.score, "explanation": r.explanation} for r in rows]}


ROUTES = [
    ("GET", r"^/api/health/$", health),
    ("GET", r"^/api/clock/$", clock_get),
    ("PUT", r"^/api/clock/$", clock_put),
    ("GET", r"^/api/threats/$", threats),
    ("GET", r"^/api/fields/$", fields),
    ("GET", r"^/api/fields/(\d+)/$", field_detail),
    ("GET", r"^/api/risks/$", risks_day),
    ("GET", r"^/api/fields/(\d+)/risks/$", field_risks),
    ("GET", r"^/api/fields/(\d+)/risks/([^/]+)/$", field_day),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "engine-mock-api"

    def log_message(self, fmt, *args):
        self.server.log(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    def _send(self, status: int, payload: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _api(self, method: str):
        close_old_connections()
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = None
        if method == "PUT":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"null")
            except json.JSONDecodeError:
                return self._json(400, {"detail": "JSON parse error"})
        allowed = False
        for m, pattern, fn in ROUTES:
            match = re.match(pattern, url.path)
            if not match:
                continue
            allowed = True
            if m != method:
                continue
            try:
                return self._json(200, fn(q, body, *match.groups()))
            except ApiError as e:
                return self._json(e.status, {"detail": e.detail})
            except Exception as e:  # never drop the connection: DRF-style 500 with a detail
                self.server.log(f"500 {type(e).__name__}: {e}")
                return self._json(500, {"detail": "A server error occurred."})
        if allowed:
            return self._json(405, {"detail": f'Method "{method}" not allowed.'})
        return self._json(404, {"detail": "Not found."})

    def _static(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            target = DEV_PAGE
        elif path.startswith("/static/frontend/"):
            target = (STATIC_ROOT / path[len("/static/frontend/"):]).resolve()
            if STATIC_ROOT.resolve() not in target.parents:
                return self._json(404, {"detail": "Not found."})
        else:
            return self._json(404, {"detail": "Not found."})
        if not target.is_file():
            return self._json(404, {"detail": "Not found."})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        return self._static()

    def do_PUT(self):
        return self._api("PUT")

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._api("POST")
        return self._json(404, {"detail": "Not found."})


class Command(BaseCommand):
    help = "Development only: the platform API's agreed endpoints from the database, plus the map's dev page."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=8001)
        parser.add_argument("--host", default="127.0.0.1")

    def handle(self, *args, port=8001, host="127.0.0.1", **opts):
        server = HTTPServer((host, port), Handler)
        server.log = lambda line: self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(f"Mock platform API + map dev page on http://{host}:{port}/ (Ctrl+C to stop)"))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
