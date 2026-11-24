"""Auditoría matemática interna de Fútbol Parley Lab.
Uso: python diagnostico.py [YYYY-MM-DD]
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fuentes as F
import main as P


def generar_diagnostico(fecha):
    res = P.analizar(fecha, log=lambda *_: None)
    filas = []
    for a in res["partidos"]:
        g = a["g"]
        n_m = min((a.get("sh") or {}).get("pj", 4) or 4, (a.get("sa") or {}).get("pj", 4) or 4)
        for s in a["sel"]:
            p_orig = round(min(s.get("p1", s["prob"]), s.get("p2", s["prob"])), 4)
            cuota = float(s["cuota"])
            p_imp = round(1.0 / cuota, 4) if cuota > 0 else 0.0
            p_nv = s.get("prob_novig")
            w = s.get("w_mod")
            p_fin = round(float(s["prob"]), 4)
            ev = round(p_fin * cuota - 1.0, 4)
            kelly_full = round(max(0.0, ev / (cuota - 1.0)), 4) if (ev > 0 and cuota > 1.0) else 0.0
            stake_025 = round(min(0.05, kelly_full * 0.25) * 100, 2)
            filas.append(dict(
                partido=g["partido"],
                liga=g["liga"],
                mercado=s["tipo"],
                seleccion=s["seleccion"],
                cuota=cuota,
                cuota_est=bool(s.get("cuota_est", False)),
                prob_modelo_orig=p_orig,
                prob_implicita=p_imp,
                prob_mercado_devig=p_nv,
                n_muestra=n_m,
                w_modelo=w,
                prob_final=p_fin,
                ev_real=ev,
                kelly_full_pct=round(kelly_full * 100, 2),
                stake_025_pct=stake_025,
                estado=s["estado"],
            ))
    return dict(fecha=str(fecha), total_picks=len(filas), picks=filas)


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
