"""Historial y Backtesting automático en SQLite para Fútbol Parley Lab."""
import datetime as dt
import math
import shutil
import sqlite3
from pathlib import Path

import fuentes as F
import motor as M

DB = Path(__file__).parent / "historial.db"
BACKUPS = Path(__file__).parent / "backups"
MODEL_VERSION = "fut_v2_ev_nb2"


def _backup_diario(fecha):
    """Copia de seguridad automática diaria de historial.db (mantiene últimos 14 días)."""
    if not DB.exists():
        return
    BACKUPS.mkdir(exist_ok=True)
    dst = BACKUPS / f"historial_{fecha:%Y%m%d}.db"
    if not dst.exists():
        shutil.copy2(DB, dst)
        viejos = sorted(BACKUPS.glob("historial_*.db"))[:-14]
        for v in viejos:
            v.unlink(missing_ok=True)


def _conn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT, game_id TEXT, liga TEXT, partido TEXT, hora TEXT,
        mercado TEXT, seleccion TEXT, cuota REAL, prob_real REAL,
        linea_alt REAL, home_nombre TEXT, away_nombre TEXT,
        estado TEXT, resultado TEXT DEFAULT 'PENDIENTE', marcador TEXT DEFAULT '',
        model_version TEXT DEFAULT 'v1',
        UNIQUE(fecha, game_id, mercado)
    )""")
    cols = {r[1] for r in c.execute("PRAGMA table_info(picks)").fetchall()}
    if "model_version" not in cols:
        c.execute("ALTER TABLE picks ADD COLUMN model_version TEXT DEFAULT 'v1'")
    c.execute("""CREATE TABLE IF NOT EXISTS odds_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT, game_id TEXT, liga TEXT, partido TEXT, captured_at TEXT,
        ml_home REAL, ml_draw REAL, ml_away REAL, total_line REAL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_picks_fecha ON picks(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_odds_game ON odds_snapshots(game_id)")
    return c


def registrar_jornada(fecha, partidos):
    _backup_diario(fecha)
    ahora = dt.datetime.now(F.VET).isoformat(timespec="seconds")
    with _conn() as c:
        for a in partidos:
            g = a["g"]
            dk = g.get("dk") or {}
            if dk.get("total") is not None:
                c.execute("""INSERT INTO odds_snapshots
                    (fecha, game_id, liga, partido, captured_at, ml_home, ml_draw, ml_away, total_line)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (str(fecha), g["id"], g["liga"], g["partido"], ahora,
                     dk.get("ml_home"), dk.get("ml_draw"), dk.get("ml_away"), dk.get("total")))
            for s in a["sel"]:
                if M.bloqueado(s["estado"]):
                    continue
                c.execute("""INSERT INTO picks
                    (fecha, game_id, liga, partido, hora, mercado, seleccion, cuota, prob_real,
                     linea_alt, home_nombre, away_nombre, estado, model_version)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fecha, game_id, mercado) DO UPDATE SET
                      seleccion=excluded.seleccion, cuota=excluded.cuota,
                      prob_real=excluded.prob_real, estado=excluded.estado,
                      model_version=excluded.model_version
                    WHERE resultado='PENDIENTE'""",
                    (str(fecha), g["id"], g["liga"], g["partido"], g["hora"], s["tipo"], s["seleccion"],
                     s["cuota"], s["prob"], s.get("linea_alt"), g["home"]["nombre"],
                     g["away"]["nombre"], s["estado"], MODEL_VERSION))


def verificar_resultados():
    liquidados = 0
    with _conn() as c:
        pares = [(r["fecha"], r["liga"]) for r in c.execute("SELECT DISTINCT fecha, liga FROM picks WHERE resultado='PENDIENTE'")]
        for f_str, liga in pares:
            f = dt.date.fromisoformat(f_str)
            try:
                sb = F.http(f"{F.ESPN}/{liga}/scoreboard?dates={f:%Y%m%d}", ttl=300)
            except Exception:
                continue
            finales = {}
            for e in sb.get("events", []):
                comp = e["competitions"][0]
                if not comp["status"]["type"].get("completed"):
                    continue
                teams = {x["homeAway"]: x for x in comp["competitors"]}
                sh = int(float(teams["home"]["score"]))
                sa = int(float(teams["away"]["score"]))
                finales[e["id"]] = (sh, sa, sh + sa)
            if not finales:
                continue
            for r in c.execute("SELECT * FROM picks WHERE fecha=? AND liga=? AND resultado='PENDIENTE'", (f_str, liga)).fetchall():
                if r["game_id"] not in finales:
                    continue
                sh, sa, tot = finales[r["game_id"]]
                marc = f"{sh}-{sa} ({tot})"
                res = "PENDIENTE"
                if r["mercado"] == "Doble Oportunidad":
                    if "(1X)" in r["seleccion"]:
                        res = "GANADA" if sh >= sa else "PERDIDA"
                    else:
                        res = "GANADA" if sa >= sh else "PERDIDA"
                elif r["mercado"] == "Ganador (2 Goles)":
                    eligio_home = r["home_nombre"] in r["seleccion"]
                    res = "GANADA" if ((sh > sa) if eligio_home else (sa > sh)) else "PERDIDA"
                elif r["mercado"].startswith("Total UNDER") and r["linea_alt"] is not None:
                    res = "GANADA" if tot < r["linea_alt"] else "PERDIDA"
                elif r["mercado"].startswith("Total OVER") and r["linea_alt"] is not None:
                    res = "GANADA" if tot > r["linea_alt"] else "PERDIDA"
                elif r["mercado"] == "Ambos Marcan":
                    ambos = (sh >= 1 and sa >= 1)
                    eligio_si = "SÍ" in r["seleccion"]
                    res = "GANADA" if (ambos if eligio_si else not ambos) else "PERDIDA"
                elif r["mercado"] == "Hándicap +1.5":
                    eligio_home = r["home_nombre"] in r["seleccion"]
                    diff = (sh - sa) if eligio_home else (sa - sh)
                    res = "GANADA" if (diff + 1.5) > 0 else "PERDIDA"
                c.execute("UPDATE picks SET resultado=?, marcador=? WHERE id=?", (res, marc, r["id"]))
                liquidados += 1
    return liquidados


def resumen():
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM picks ORDER BY fecha DESC, hora ASC, prob_real DESC")]
    gan = sum(1 for r in rows if r["resultado"] == "GANADA")
    per = sum(1 for r in rows if r["resultado"] == "PERDIDA")
    pen = sum(1 for r in rows if r["resultado"] == "PENDIENTE")
    decididas = gan + per
    beneficio = sum((r["cuota"] - 1) for r in rows if r["resultado"] == "GANADA") - per

    por_fecha = {}
    por_mercado = {}
    tramos = {"<60%": [0, 0, 0.0], "60-70%": [0, 0, 0.0], "70-80%": [0, 0, 0.0], "80%+": [0, 0, 0.0]}
    brier_sum, logloss_sum, brier_n = 0.0, 0.0, 0
    for r in rows:
        d = por_fecha.setdefault(r["fecha"], dict(ganadas=0, perdidas=0, pendientes=0, beneficio_u=0.0))
        m = por_mercado.setdefault(r["mercado"], dict(mercado=r["mercado"], ganadas=0, perdidas=0, pendientes=0, prob_sum=0.0, dec=0, beneficio_u=0.0))
        p_cl = max(0.01, min(0.99, float(r["prob_real"] or 0.5)))
        tk = "<60%" if p_cl < 0.60 else ("60-70%" if p_cl < 0.70 else ("70-80%" if p_cl < 0.80 else "80%+"))
        if r["resultado"] == "GANADA":
            d["ganadas"] += 1
            d["beneficio_u"] = round(d["beneficio_u"] + (r["cuota"] - 1), 2)
            m["ganadas"] += 1; m["dec"] += 1; m["prob_sum"] += p_cl
            m["beneficio_u"] = round(m["beneficio_u"] + (r["cuota"] - 1), 2)
            brier_sum += (p_cl - 1.0) ** 2; logloss_sum += -math.log(p_cl); brier_n += 1
            tramos[tk][0] += 1; tramos[tk][1] += 1; tramos[tk][2] += p_cl
        elif r["resultado"] == "PERDIDA":
            d["perdidas"] += 1
            d["beneficio_u"] = round(d["beneficio_u"] - 1, 2)
            m["perdidas"] += 1; m["dec"] += 1; m["prob_sum"] += p_cl
            m["beneficio_u"] = round(m["beneficio_u"] - 1, 2)
            brier_sum += (p_cl - 0.0) ** 2; logloss_sum += -math.log(1.0 - p_cl); brier_n += 1
            tramos[tk][1] += 1; tramos[tk][2] += p_cl
        elif r["resultado"] == "PENDIENTE":
            d["pendientes"] += 1
            m["pendientes"] += 1

    # Drawdown máximo histórico (en unidades, orden cronológico)
    eq, peak, max_dd = 0.0, 0.0, 0.0
    for r in reversed(rows):
        if r["resultado"] == "GANADA":
            eq += (r["cuota"] - 1)
        elif r["resultado"] == "PERDIDA":
            eq -= 1.0
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    diag_mercados = []
    for m in por_mercado.values():
        dec = m["dec"]
        ac = round(m["ganadas"] / dec, 4) if dec else None
        pe = round(m["prob_sum"] / dec, 4) if dec else None
        muestra = "Confiable (100+)" if dec >= 100 else ("Tendencia (30-99)" if dec >= 30 else f"Muestra baja ({dec})")
        diag_mercados.append(dict(
            mercado=m["mercado"], ganadas=m["ganadas"], perdidas=m["perdidas"], pendientes=m["pendientes"],
            dec=dec, muestra=muestra,
            acierto=ac, prob_esperada=pe, sesgo=round(ac - pe, 4) if (ac is not None and pe is not None) else None,
            roi=round(m["beneficio_u"] / dec, 4) if dec else None, beneficio_u=m["beneficio_u"],
        ))
    diag_mercados.sort(key=lambda x: -(x["ganadas"] + x["perdidas"] + x["pendientes"]))
    calibracion = [
        dict(tramo=k, n=v[1], acierto=round(v[0] / v[1], 4) if v[1] else None,
             esperada=round(v[2] / v[1], 4) if v[1] else None)
        for k, v in tramos.items() if v[1] > 0
    ]

    return dict(
        total=len(rows), ganadas=gan, perdidas=per, pendientes=pen,
        acierto=round(gan / decididas, 4) if decididas else None,
        roi=round(beneficio / decididas, 4) if decididas else None,
        beneficio_u=round(beneficio, 2),
        max_dd_u=round(max_dd, 2),
        brier=round(brier_sum / brier_n, 4) if brier_n else None,
        log_loss=round(logloss_sum / brier_n, 4) if brier_n else None,
        por_fecha=por_fecha,
        por_mercado=diag_mercados,
        calibracion=calibracion,
        picks=rows[:500],
    )
