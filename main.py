"""Fútbol Parley Lab: descarga partidos europeos, analiza con Dixon-Coles 65/35 y genera Excel.
Uso:  python main.py            (hoy, hora Venezuela)
      python main.py 2026-11-22
"""
import csv
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fuentes as F
import historial as H
import motor as M
from excel import generar_excel

BASE = Path(__file__).parent
ENTRADA = BASE / "entrada"
REPORTES = BASE / "reportes"
CAMPOS = ["partido", "ml_local", "dc_1x", "dc_x2", "under35", "over15"]


def archivo_cuotas(fecha):
    ENTRADA.mkdir(exist_ok=True)
    return ENTRADA / f"cuotas_{fecha:%Y%m%d}.csv"


def leer_cuotas(fecha, juegos=None):
    f = archivo_cuotas(fecha)
    if not f.exists():
        guardar_cuotas(fecha, {g["partido"]: {} for g in (juegos or [])})
        return {}
    res = {}
    with f.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            res[r["partido"].strip()] = {
                k: float(str(v).replace(",", "."))
                for k, v in r.items()
                if k != "partido" and v and str(v).strip()
            }
    return res


def guardar_cuotas(fecha, datos):
    with archivo_cuotas(fecha).open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(CAMPOS)
        for p, d in datos.items():
            w.writerow([p] + [d.get(k, "") for k in CAMPOS[1:]])


def analizar(fecha, log=print):
    juegos = F.partidos(fecha)
    if not juegos:
        return dict(fecha=str(fecha), partidos=[], top_parley=[])
    casa = leer_cuotas(fecha, juegos)
    tablas = {}

    # Guardar/restaurar cuotas pre-partido para que ESPN no borre líneas al iniciar
    odds_file = F.CACHE / f"odds_{fecha:%Y%m%d}.json"
    saved_odds = json.loads(odds_file.read_text(encoding="utf-8")) if odds_file.exists() else {}
    changed_odds = False
    for g in juegos:
        gid = g["id"]
        if g["dk"].get("ml_home") is not None:
            saved_odds[gid] = g["dk"]
            changed_odds = True
        elif gid in saved_odds:
            g["dk"] = saved_odds[gid]
    if changed_odds:
        odds_file.write_text(json.dumps(saved_odds), encoding="utf-8")

    # Descargar tablas y L5 en paralelo para carga rápida (~3s)
    ligas_unicas = list({g["liga"] for g in juegos})
    pares_l5 = list({(g["liga"], g[s]["id"]) for g in juegos for s in ("home", "away")})
    with ThreadPoolExecutor(max_workers=10) as ex:
        fut_tab = {slug: ex.submit(F.tabla_liga, slug) for slug in ligas_unicas}
        fut_l5 = {par: ex.submit(F.ultimos5, par[0], par[1]) for par in pares_l5}
        fut_pl = {par: ex.submit(F.plantilla, par[0], par[1]) for par in pares_l5}
        tablas = {slug: f.result() for slug, f in fut_tab.items()}
        l5_map = {par: f.result() for par, f in fut_l5.items()}
        pl_map = {par: f.result() for par, f in fut_pl.items()}

    analisis = []
    for g in juegos:
        slug = g["liga"]
        eq_map, lg = tablas[slug]
        sh = eq_map.get(g["home"]["id"], {})
        sa = eq_map.get(g["away"]["id"], {})
        l5h = l5_map.get((slug, g["home"]["id"]), [])
        l5a = l5_map.get((slug, g["away"]["id"]), [])
        pl_h = pl_map.get((slug, g["home"]["id"]), [])
        pl_a = pl_map.get((slug, g["away"]["id"]), [])
        dh, fat_h = M.dias_descanso(l5h, fecha)
        da, fat_a = M.dias_descanso(l5a, fecha)

        proy = M.proyectar(sh, sa, l5h, l5a, lg, fat_h=fat_h, fat_a=fat_a)
        cc = casa.get(g["partido"], {})
        sel, p1, p2 = M.evaluar_partido(g, proy, cc)
        props = M.sugerir_props(g, proy, pl_h, pl_a, lg)

        analisis.append(dict(
            g=g, sh=sh, sa=sa, lg=lg, l5h=l5h, l5a=l5a,
            dias_h=dh, dias_a=da, proy=proy, sel=sel, props=props,
            p1=p1, p2=p2, casa=cc,
        ))

    # Top Parley corto de élite (máx. 4 patas, 1 por partido, SOLO partidos aún por jugar)
    eleg = []
    for a in analisis:
        est_g = (a["g"].get("estado") or "").lower()
        if any(k in est_g for k in ("full time", "final", "ft", "halftime", "in progress")):
            continue
        for s in a["sel"]:
            if not M.bloqueado(s["estado"]):
                eleg.append(dict(
                    partido=a["g"]["partido"], liga=a["g"]["liga_nombre"], hora=a["g"]["hora"],
                    mercado=s["tipo"], seleccion=s["seleccion"], cuota=s["cuota"],
                    prob=s["prob"], ventaja=s["ventaja"], estado=s["estado"],
                ))
    eleg.sort(key=lambda x: -x["prob"])
    vistos, top = set(), []
    for x in eleg:
        if x["partido"] not in vistos:
            vistos.add(x["partido"])
            top.append(x)
        if len(top) == 4:
            break

    return dict(fecha=str(fecha), partidos=analisis, top_parley=top)


def generar(fecha, log=print):
    res = analizar(fecha, log=log)
    REPORTES.mkdir(exist_ok=True)
    path = REPORTES / f"futbol_{fecha:%Y%m%d}.xlsx"
    if res["partidos"]:
        generar_excel(res["partidos"], fecha, path)
        H.registrar_jornada(fecha, res["partidos"])
    return res, path


if __name__ == "__main__":
    f = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(F.VET).date()
    res, path = generar(f)
    print(f"Fútbol Parley Lab | {f} | {len(res['partidos'])} partidos analizados | Excel: {path}")
    for x in res["top_parley"]:
        print(f"  ★ [{x['liga']}] {x['partido']} -> {x['seleccion']} @ {x['cuota']:.2f} ({x['prob']*100:.1f}%)")
