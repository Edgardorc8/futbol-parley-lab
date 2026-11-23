"""Fuentes gratuitas: ESPN Soccer API (7 ligas europeas de élite: partidos, tablas, L5 y cuotas)."""
import datetime as dt
import difflib
import json
import os
import re
import time
import unicodedata
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
                inicio_iso=e["date"],
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


# ---------------- The Odds API v4 (Cuotas Reales) ----------------
ODDS_SPORT_KEY = {
    "eng.1": "soccer_epl",
    "esp.1": "soccer_spain_la_liga",
    "ita.1": "soccer_italy_serie_a",
    "ger.1": "soccer_germany_bundesliga",
    "fra.1": "soccer_france_ligue_one",
    "uefa.champions": "soccer_uefa_champs_league",
    "uefa.europa": "soccer_uefa_europa_league",
}
ODDS_TTL = 6 * 3600  # 6 horas para cuidar los 500 créditos/mes
ALIAS_FILE = Path(__file__).parent / "alias_equipos.json"
CREDITS_FILE = CACHE / "oddsapi_credits.json"


def _odds_api_key():
    k = os.environ.get("ODDS_API_KEY", "").strip()
    if k:
        return k
    env_p = Path(__file__).parent / ".env"
    if env_p.exists():
        for ln in env_p.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("ODDS_API_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def normalizar_nombre(nombre):
    s = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"\b(fc|cf|sc|ac|as|sv|afc|rb|rc|ud|cd|ssc|ogc|vfb|vfl|tsg|fsv)\b", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def _cargar_alias():
    if ALIAS_FILE.exists():
        try:
            return json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _registrar_sin_match(espn_nom, candidatos):
    al = _cargar_alias()
    if espn_nom not in al:
        al[espn_nom] = {"sugerencias": candidatos[:3], "mapear_a": ""}
        try:
            ALIAS_FILE.write_text(json.dumps(al, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def _creditos_ok():
    if not CREDITS_FILE.exists():
        return True
    try:
        d = json.loads(CREDITS_FILE.read_text(encoding="utf-8"))
        if d.get("fecha") == str(dt.date.today()) and int(d.get("remaining", 999)) < 50:
            return False
    except Exception:
        pass
    return True


def _http_odds(url, cache_name, ttl=ODDS_TTL):
    key = CACHE / f"{cache_name}.json"
    if key.exists() and time.time() - key.stat().st_mtime < ttl:
        return json.loads(key.read_text(encoding="utf-8"))
    if not _creditos_ok():
        print("[The Odds API] Alerta: <50 créditos restantes hoy, usando caché/fallback.")
        return json.loads(key.read_text(encoding="utf-8")) if key.exists() else []
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            txt = resp.read().decode("utf-8")
            rem = resp.headers.get("x-requests-remaining")
            if rem is not None:
                CREDITS_FILE.write_text(json.dumps({"fecha": str(dt.date.today()), "remaining": int(float(rem))}), encoding="utf-8")
                if int(float(rem)) < 50:
                    print(f"[The Odds API] ALERTA: quedan solo {rem} créditos este mes.")
        key.write_text(txt, encoding="utf-8")
        return json.loads(txt)
    except Exception as e:
        print(f"[The Odds API] Fallback por error: {e}")
        return json.loads(key.read_text(encoding="utf-8")) if key.exists() else []


def _mejor_bookmaker(bms):
    for pref in ("pinnacle", "bet365", "betfair_ex_eu", "unibet_eu", "williamhill"):
        for b in bms:
            if b.get("key") == pref:
                return b
    return bms[0] if bms else None


def _match_evento(g, eventos, alias):
    h_espn = alias.get(g["home"]["nombre"], {}).get("mapear_a") or g["home"]["nombre"]
    a_espn = alias.get(g["away"]["nombre"], {}).get("mapear_a") or g["away"]["nombre"]
    nh, na = normalizar_nombre(h_espn), normalizar_nombre(a_espn)
    best, best_sc = None, 0.0
    for ev in eventos:
        eh, ea = normalizar_nombre(ev.get("home_team")), normalizar_nombre(ev.get("away_team"))
        sc = (difflib.SequenceMatcher(None, nh, eh).ratio() + difflib.SequenceMatcher(None, na, ea).ratio()) / 2
        if sc > best_sc:
            best, best_sc = ev, sc
    if best_sc >= 0.78:
        return best
    if eventos:
        _registrar_sin_match(g["home"]["nombre"], [ev.get("home_team") for ev in eventos[:5]])
    return None


def obtener_cuotas_reales(juegos):
    """Obtiene cuotas reales (h2h, totals 2.5, DO derivada de h2h, y btts en próximos) desde The Odds API v4."""
    api_key = _odds_api_key()
    if not api_key or not juegos:
        return {}
    alias = _cargar_alias()
    ligas = {g["liga"] for g in juegos if g["liga"] in ODDS_SPORT_KEY}
    por_liga = {}
    for slug in ligas:
        sk = ODDS_SPORT_KEY[slug]
        url = f"https://api.the-odds-api.com/v4/sports/{sk}/odds/?apiKey={api_key}&regions=eu&markets=h2h,totals&oddsFormat=decimal"
        por_liga[slug] = _http_odds(url, f"oddsapi_{sk}")

    ahora_utc = dt.datetime.now(dt.timezone.utc)
    out = {}
    for g in juegos:
        slug = g["liga"]
        evs = por_liga.get(slug) or []
        ev = _match_evento(g, evs, alias)
        if not ev:
            continue
        bm = _mejor_bookmaker(ev.get("bookmakers") or [])
        if not bm:
            continue
        cuo = {}
        for mkt in bm.get("markets", []):
            k = mkt.get("key")
            outs = mkt.get("outcomes", [])
            if k == "h2h":
                o1 = ox = o2 = None
                for o in outs:
                    nm = normalizar_nombre(o.get("name"))
                    if nm == "draw":
                        ox = float(o["price"])
                    elif difflib.SequenceMatcher(None, nm, normalizar_nombre(ev.get("home_team"))).ratio() >= 0.80:
                        o1 = float(o["price"])
                    else:
                        o2 = float(o["price"])
                if o1: cuo["ml_local"] = round(o1, 3)
                if ox: cuo["ml_empate"] = round(ox, 3)
                if o2: cuo["ml_visita"] = round(o2, 3)
                # Doble Oportunidad ejecutable derivada de h2h real: (O1*OX)/(O1+OX)
                if o1 and ox: cuo["dc_1x"] = round((o1 * ox) / (o1 + ox), 2)
                if o2 and ox: cuo["dc_x2"] = round((o2 * ox) / (o2 + ox), 2)
            elif k == "totals":
                for o in outs:
                    pt = o.get("point")
                    if pt == 2.5:
                        if o.get("name", "").lower() == "over":
                            cuo["over25"] = round(float(o["price"]), 2)
                        elif o.get("name", "").lower() == "under":
                            cuo["under25"] = round(float(o["price"]), 2)

        # BTTS por evento solo para partidos aún por jugar (caché 6h)
        ini_iso = g.get("inicio_iso")
        es_futuro = True
        if ini_iso:
            try:
                es_futuro = dt.datetime.fromisoformat(ini_iso.replace("Z", "+00:00")) > ahora_utc
            except Exception:
                pass
        if es_futuro and ev.get("id") and _creditos_ok():
            sk = ODDS_SPORT_KEY[slug]
            u_ev = f"https://api.the-odds-api.com/v4/sports/{sk}/events/{ev['id']}/odds?apiKey={api_key}&regions=eu&markets=btts&oddsFormat=decimal"
            ev_btts = _http_odds(u_ev, f"oddsapi_btts_{ev['id']}")
            bm_b = _mejor_bookmaker((ev_btts.get("bookmakers") if isinstance(ev_btts, dict) else []) or [])
            if bm_b:
                for mkt in bm_b.get("markets", []):
                    if mkt.get("key") == "btts":
                        for o in mkt.get("outcomes", []):
                            nm = o.get("name", "").lower()
                            if nm == "yes": cuo["btts_si"] = round(float(o["price"]), 2)
                            elif nm == "no": cuo["btts_no"] = round(float(o["price"]), 2)
        if cuo:
            out[g["partido"]] = cuo
    return out
