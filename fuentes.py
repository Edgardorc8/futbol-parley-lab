"""Fuentes gratuitas: ESPN Soccer API (7 ligas europeas de élite: partidos, tablas, L5 y cuotas)."""
import datetime as dt
import json
import re
import time
import urllib.request
from pathlib import Path

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (uso personal; Futbol Parley Lab)"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_V2 = "https://site.api.espn.com/apis/v2/sports/soccer"
VET = dt.timezone(dt.timedelta(hours=-4))

LIGAS = {
    "eng.1": ("Premier League", 1.60, 1.30),
    "esp.1": ("LaLiga", 1.45, 1.12),
    "ita.1": ("Serie A", 1.46, 1.16),
    "ger.1": ("Bundesliga", 1.72, 1.36),
    "fra.1": ("Ligue 1", 1.50, 1.18),
    "uefa.champions": ("Champions League", 1.65, 1.25),
    "uefa.europa": ("Europa League", 1.58, 1.22),
}


def http(url, ttl=1800):
    """GET con caché en disco, reintentos y pausa cortés."""
    key = CACHE / (re.sub(r"\W", "_", url)[-150:] + ".cache")
    if key.exists() and time.time() - key.stat().st_mtime < ttl:
        txt = key.read_text(encoding="utf-8")
    else:
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers=UA)
                txt = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
                break
            except Exception:
                if i == 2:
                    raise
                time.sleep(2)
        key.write_text(txt, encoding="utf-8")
    return json.loads(txt)


def am2dec(s):
    try:
        a = float(str(s).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return round(1 + (a / 100 if a > 0 else 100 / -a), 3)


def _num(x):
    m = re.search(r"-?\d*\.?\d+", str(x or ""))
    return float(m.group()) if m else None


def partidos(fecha):
    """Descarga todos los partidos del día en las 7 competiciones europeas."""
    out = []
    for slug, (nombre_liga, _, _) in LIGAS.items():
        try:
            s = http(f"{ESPN}/{slug}/scoreboard?dates={fecha:%Y%m%d}", ttl=900)
        except Exception:
            continue
        for e in s.get("events", []):
            c = e["competitions"][0]
            teams = {x["homeAway"]: x for x in c["competitors"]}
            hora = dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(VET)
            g = dict(
                id=e["id"],
                liga=slug,
                liga_nombre=nombre_liga,
                hora=hora.strftime("%I:%M %p"),
                partido=f"{teams['home']['team'].get('abbreviation', '?')} vs {teams['away']['team'].get('abbreviation', '?')}",
                estado=c["status"]["type"]["description"],
            )
            for side in ("home", "away"):
                t = teams[side]["team"]
                rec = {r.get("name", r.get("type", "")).lower(): r.get("summary") for r in teams[side].get("records", [])}
                g[side] = dict(
                    id=str(t["id"]),
                    abbr=t.get("abbreviation", t["displayName"][:3].upper()),
                    nombre=t["displayName"],
                    logo=t.get("logo", ""),
                    record=rec.get("overall") or rec.get("total") or "",
                    forma=teams[side].get("form", ""),
                )
            o = ((c.get("odds") or [None])[0]) or {}
            ml = o.get("moneyline") or {}
            tot = o.get("total") or {}
            g["dk"] = dict(
                total=o.get("overUnder") or _num((tot.get("over") or {}).get("close", {}).get("line")) or 2.5,
                total_open=_num((tot.get("over") or {}).get("open", {}).get("line")),
                ml_home=am2dec((ml.get("home") or {}).get("close", {}).get("odds")) or am2dec((o.get("homeTeamOdds") or {}).get("moneyLine")),
                ml_away=am2dec((ml.get("away") or {}).get("close", {}).get("odds")) or am2dec((o.get("awayTeamOdds") or {}).get("moneyLine")),
                ml_draw=am2dec((ml.get("draw") or {}).get("close", {}).get("odds")) or am2dec((o.get("drawOdds") or {}).get("moneyLine")),
            )
            out.append(g)
    out.sort(key=lambda x: x["hora"])
    return out


def tabla_liga(slug):
    """Obtiene estadísticas de temporada (PJ, GF/G, GC/G, Pts) desde standings de ESPN."""
    _, def_h, def_a = LIGAS.get(slug, ("Liga", 1.55, 1.25))
    try:
        d = http(f"{ESPN_V2}/{slug}/standings", ttl=3600 * 6)
    except Exception:
        return {}, dict(lg_home=def_h, lg_away=def_a)

    equipos = {}
    tot_gf, tot_pj = 0.0, 0.0

    def _procesar(entries):
        nonlocal tot_gf, tot_pj
        for ent in entries:
            t = ent.get("team", {})
            tid = str(t.get("id", ""))
            st = {s["name"]: s.get("value", 0) for s in ent.get("stats", [])}
            pj = float(st.get("gamesPlayed", 0) or 0)
            gf = float(st.get("pointsFor", 0) or 0)
            gc = float(st.get("pointsAgainst", 0) or 0)
            pts = int(st.get("points", 0) or 0)
            rank = int(st.get("rank", 0) or 0)
            if pj > 0:
                equipos[tid] = dict(
                    pj=int(pj), gf=gf, gc=gc,
                    gf_pg=round(gf / pj, 2), gc_pg=round(gc / pj, 2),
                    pts=pts, rank=rank,
                )
                tot_gf += gf
                tot_pj += pj

    for child in d.get("children", [d]):
        _procesar(child.get("standings", {}).get("entries", []))

    if tot_pj > 0:
        avg_g = tot_gf / tot_pj
        lg = dict(lg_home=round(avg_g * 1.12, 2), lg_away=round(avg_g * 0.88, 2))
    else:
        lg = dict(lg_home=def_h, lg_away=def_a)
    return equipos, lg


def ultimos5(slug, team_id):
    """Últimos 5 partidos completados del equipo (para L5 y días de descanso)."""
    try:
        d = http(f"{ESPN}/{slug}/teams/{team_id}/schedule", ttl=3600)
    except Exception:
        return []
    hechos = [e for e in d.get("events", []) if e["competitions"][0]["status"]["type"].get("completed")]
    out = []
    for e in hechos[-5:]:
        c = e["competitions"][0]
        me = next((x for x in c["competitors"] if str(x["team"]["id"]) == str(team_id)), None)
        if not me:
            continue
        op = next((x for x in c["competitors"] if x is not me), None)
        if not op:
            continue
        try:
            pf = float(me["score"]["value"] if isinstance(me["score"], dict) else me["score"])
            pa = float(op["score"]["value"] if isinstance(op["score"], dict) else op["score"])
        except Exception:
            continue
        out.append(dict(
            fecha=e["date"][:10],
            rival=op["team"].get("abbreviation", op["team"]["displayName"][:3].upper()),
            cond="Local" if me["homeAway"] == "home" else "Visita",
            pf=pf,
            pa=pa,
        ))
    return out


def plantilla(slug, team_id):
    """Descarga estadísticas de remates y atajadas de porteros (appearances, totalShots, shotsOnTarget, saves)."""
    try:
        d = http(f"{ESPN}/{slug}/teams/{team_id}/roster", ttl=3600 * 6)
    except Exception:
        return []
    out = []
    for a in d.get("athletes", []):
        st = {}
        for cat in a.get("statistics", {}).get("splits", {}).get("categories", []):
            for s in cat.get("stats", []):
                if s["name"] in ("appearances", "totalShots", "shotsOnTarget", "totalGoals", "saves"):
                    st[s["name"]] = float(s.get("value", 0) or 0)
        pj = st.get("appearances", 0)
        sh = st.get("totalShots", 0)
        sot = st.get("shotsOnTarget", 0)
        sv = st.get("saves", 0)
        pos = (a.get("position") or {}).get("abbreviation", "")
        if pj >= 4 and (sh > 0 or sv > 0):
            out.append(dict(
                nombre=a.get("displayName", "?"),
                pos=pos,
                pj=int(pj),
                sh_pg=round(sh / pj, 2),
                sot_pg=round(sot / pj, 2),
                sv_pg=round(sv / pj, 2),
                goles=int(st.get("totalGoals", 0)),
            ))
    return out
