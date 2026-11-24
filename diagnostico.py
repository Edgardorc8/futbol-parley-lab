"""Auditoría matemática interna de Fútbol Parley Lab.
Uso: python diagnostico.py [YYYY-MM-DD]
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fuentes as F
import main as P
import motor as M


def generar_diagnostico(fecha):
    res = P.analizar(fecha, log=lambda *_: None)
    filas = []
    for a in res["partidos"]:
        g = a["g"]
        n_m = min((a.get("sh") or {}).get("pj", 4) or 4, (a.get("sa") or {}).get("pj", 4) or 4)
        for s in a["sel"]:
            p_orig = round(min(s.get("p1", s["prob"]), s.get("p2", s["prob"])), 4)
            cuota = float(s["cuota"])
            es_est = bool(s.get("cuota_est", False))
            p_imp = round(1.0 / cuota, 4) if cuota > 0 else 0.0
            p_nv = s.get("prob_novig")
            w = s.get("w_mod")
            p_fin = round(float(s["prob"]), 4)
            ev = round(p_fin * cuota - 1.0, 4)
            # Tarea 1 y 2: cuota_est=True o EV < MIN_EV (2%) -> Kelly y Stake forzados a 0.00%
            est_txt = s["estado"]
            if es_est or ev < M.MIN_EV or cuota <= 1.0:
                kelly_full, stake_raw = 0.0, 0.0
                if not es_est and 0 < ev < M.MIN_EV:
                    est_txt = "DESCARTADO_POR_EV_BAJO"
            else:
                kelly_full = round(ev / (cuota - 1.0), 4)
                stake_raw = round(min(0.05, kelly_full * 0.25) * 100, 2)
            filas.append(dict(
                partido=g["partido"],
                liga=g["liga"],
                mercado=s["tipo"],
                seleccion=s["seleccion"],
                cuota=cuota,
                cuota_est=es_est,
                prob_modelo_orig=p_orig,
                prob_implicita=p_imp,
                prob_mercado_devig=p_nv,
                n_muestra=n_m,
                w_modelo=w,
                prob_final=p_fin,
                ev_real=ev,
                kelly_full_pct=round(kelly_full * 100, 2),
                stake_025_pct=stake_raw,
                estado=est_txt,
            ))

    # Filtro estricto de correlación: máximo 1 pick con stake por partido (conserva el de mayor EV)
    mejor_por_partido = {}
    for idx, r in enumerate(filas):
        if r["stake_025_pct"] > 0:
            p_key = r["partido"]
            if p_key not in mejor_por_partido or r["ev_real"] > filas[mejor_por_partido[p_key]]["ev_real"]:
                if p_key in mejor_por_partido:
                    prev = filas[mejor_por_partido[p_key]]
                    prev["stake_025_pct"] = 0.0
                    prev["kelly_full_pct"] = 0.0
                    prev["estado"] = "DESCARTADO_CORRELACION_PARTIDO"
                mejor_por_partido[p_key] = idx
            else:
                r["stake_025_pct"] = 0.0
                r["kelly_full_pct"] = 0.0
                r["estado"] = "DESCARTADO_CORRELACION_PARTIDO"

    # Cap diario global del 5.00% de la banca sobre la suma de todos los stakes activos
    tot_stk = sum(r["stake_025_pct"] for r in filas)
    if tot_stk > 5.0:
        escala = 5.0 / tot_stk
        for r in filas:
            if r["stake_025_pct"] > 0:
                r["stake_025_pct"] = round(r["stake_025_pct"] * escala, 2)
    return dict(fecha=str(fecha), total_picks=len(filas), suma_stake_pct=round(sum(r["stake_025_pct"] for r in filas), 2), picks=filas)


if __name__ == "__main__":
    f = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(F.VET).date()
    d = generar_diagnostico(f)
    print(f"=== DIAGNÓSTICO MATEMÁTICO FÚTBOL PARLEY LAB | {d['fecha']} | {d['total_picks']} picks ===")
    hdr = f"{'Partido':<12} | {'Selección':<28} | {'Cuota':>5} | {'Est':>3} | {'P.Orig':>6} | {'P.Imp':>6} | {'P.Devig':>7} | {'N':>2} | {'w':>5} | {'P.Fin':>6} | {'EV%':>7} | {'K%':>6} | {'Stk%':>5}"
    print(hdr)
    print("-" * len(hdr))
    for r in d["picks"]:
        pnv = f"{r['prob_mercado_devig']*100:6.1f}%" if r["prob_mercado_devig"] is not None else "    —  "
        w_s = f"{r['w_modelo']:.2f}" if r["w_modelo"] is not None else "  —  "
        print(
            f"{r['partido']:<12} | {r['seleccion'][:28]:<28} | {r['cuota']:5.2f} | "
            f"{'Sí' if r['cuota_est'] else 'No':>3} | {r['prob_modelo_orig']*100:5.1f}% | "
            f"{r['prob_implicita']*100:5.1f}% | {pnv} | {r['n_muestra']:2d} | {w_s:>5} | "
            f"{r['prob_final']*100:5.1f}% | {r['ev_real']*100:+6.1f}% | {r['kelly_full_pct']:5.1f}% | {r['stake_025_pct']:4.2f}%"
        )
