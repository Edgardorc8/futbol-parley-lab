"""Motor cuantitativo Fútbol Europeo: 65/35 + Poisson Dixon-Coles + Devigging 3-way + Gestión de Riesgo."""
import datetime as dt
import math

RHO_DC = -0.11       # Correlación Dixon-Coles para marcadores bajos (0-0, 1-0, 0-1, 1-1)
LOW_LINE = 2.25      # Candado de línea baja de goles
DISC_TOTAL = 0.50    # Alerta si modelo difiere > 0.50 goles de la línea de mercado
ADJ_CAP = 0.03       # Ajuste situacional acotado a ±3%
ODDS_MIN, ODDS_MAX = 1.22, 2.45
FATIGA_LOCAL = 0.92  # -8% ofensivo si jugó hace <= 3 días
FATIGA_VISITA = 0.88 # -12% ofensivo si jugó hace <= 3 días


def _avg(lst, k):
    return sum(x[k] for x in lst) / len(lst) if lst else 0.0


def dias_descanso(l5, fecha):
    """Días desde el último partido y bandera de fatiga europea (<= 3 días)."""
    if not l5:
        return None, False
    fechas = [dt.date.fromisoformat(x["fecha"]) for x in l5]
    dias = (fecha - fechas[-1]).days
    return dias, (0 < dias <= 3)


def proyectar(sh, sa, l5h, l5a, lg, fat_h=False, fat_a=False):
    """Calcula lambdas calibrados 65/35 (Modelo Multiplicativo + Entorno L5)."""
    lh_lg, la_lg = lg["lg_home"], lg["lg_away"]

    # Fallback si un equipo aún no tiene suficientes PJ en tabla (ej. inicio de Champions)
    gf_h = sh["gf_pg"] if sh and sh.get("pj", 0) >= 2 else (_avg(l5h, "pf") or lh_lg)
    gc_h = sh["gc_pg"] if sh and sh.get("pj", 0) >= 2 else (_avg(l5h, "pa") or la_lg)
    gf_a = sa["gf_pg"] if sa and sa.get("pj", 0) >= 2 else (_avg(l5a, "pf") or la_lg)
    gc_a = sa["gc_pg"] if sa and sa.get("pj", 0) >= 2 else (_avg(l5a, "pa") or lh_lg)

    # 1. Modelo Multiplicativo (65%) con regresión del 20% a la media de liga (evita sobreconfianza)
    avg_lg = max(0.5, (lh_lg + la_lg) / 2)
    atk_h = gf_h / avg_lg
    def_a = gc_a / avg_lg
    atk_a = gf_a / avg_lg
    def_h = gc_h / avg_lg

    raw_h = atk_h * def_a * lh_lg
    raw_a = atk_a * def_h * la_lg
    mult_h = max(0.35, min(2.85, 0.80 * raw_h + 0.20 * lh_lg))
    mult_a = max(0.25, min(2.45, 0.80 * raw_a + 0.20 * la_lg))

    # 2. Entorno Real L5 (35%)
    l5_h = (_avg(l5h, "pf") + _avg(l5a, "pa")) / 2 if (l5h and l5a) else mult_h
    l5_a = (_avg(l5a, "pf") + _avg(l5h, "pa")) / 2 if (l5h and l5a) else mult_a

    # 3. Calibración Final 65/35 + Fatiga (<72h) + topes realistas
    cal_h = min(2.85, 0.65 * mult_h + 0.35 * l5_h)
    cal_a = min(2.45, 0.65 * mult_a + 0.35 * l5_a)
    if fat_h:
        cal_h *= FATIGA_LOCAL
    if fat_a:
        cal_a *= FATIGA_VISITA

    r = dict(
        mult_h=mult_h, mult_a=mult_a, mult_total=mult_h + mult_a,
        l5_h=l5_h, l5_a=l5_a, l5_total=l5_h + l5_a,
        cal_h=cal_h, cal_a=cal_a, total=cal_h + cal_a,
        fat_h=fat_h, fat_a=fat_a,
    )
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()}


def _pois(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def matriz_dixon_coles(lam_h, lam_a, rho=RHO_DC, max_g=8):
    """Matriz de probabilidades de marcador exacto con corrección Dixon-Coles."""
    m = [[_pois(i, lam_h) * _pois(j, lam_a) for j in range(max_g + 1)] for i in range(max_g + 1)]
    # Corrección Dixon-Coles en marcadores bajos
    m[0][0] *= max(0.01, 1.0 - lam_h * lam_a * rho)
    m[1][0] *= max(0.01, 1.0 + lam_a * rho)
    m[0][1] *= max(0.01, 1.0 + lam_h * rho)
    m[1][1] *= max(0.01, 1.0 - rho)
    tot = sum(sum(row) for row in m)
    return [[v / tot for v in row] for row in m]


def probs_matriz(m):
    """Extrae probabilidades 1X2, Doble Oportunidad, Over 1.5/2.5, Under 2.5/3.5 y BTTS."""
    p_h = p_d = p_a = p_o15 = p_o25 = p_u25 = p_u35 = p_btts = 0.0
    n = len(m)
    for i in range(n):
        for j in range(n):
            p = m[i][j]
            if i > j:
                p_h += p
            elif i == j:
                p_d += p
            else:
                p_a += p
            if i + j >= 2:
                p_o15 += p
            if i + j >= 3:
                p_o25 += p
            if i + j <= 2:
                p_u25 += p
            if i + j <= 3:
                p_u35 += p
            if i >= 1 and j >= 1:
                p_btts += p
    return dict(
        p_home=p_h, p_draw=p_d, p_away=p_a,
        p_1x=p_h + p_d, p_x2=p_a + p_d,
        p_o15=p_o15, p_o25=p_o25, p_u25=p_u25, p_u35=p_u35, p_btts=p_btts,
        # Pago Anticipado (2 Goles de Ventaja): bonus conservador +3.5% si es favorito
        p_home_2g=min(0.92, p_h + (0.035 if p_h >= 0.50 else 0.015)),
        p_away_2g=min(0.92, p_a + (0.035 if p_a >= 0.50 else 0.015)),
    )


def devig_1x2(ml_h, ml_d, ml_a):
    """Power Method Devigging para 1X2: resuelve sum((1/O_i)^k) = 1 (corrige sesgo favorito-underdog)."""
    if not (ml_h and ml_d and ml_a) or min(ml_h, ml_d, ml_a) <= 1.0:
        return None, None, None, None
    ih, id_, ia = 1 / ml_h, 1 / ml_d, 1 / ml_a
    vig = round((ih + id_ + ia) - 1.0, 4)
    lo, hi = 1.0, 3.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if (ih ** mid + id_ ** mid + ia ** mid) > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2
    return round(ih ** k, 4), round(id_ ** k, 4), round(ia ** k, 4), vig


def nb2_over(k_min, mu, r=4.0):
    """Probabilidad P(X >= k_min) bajo Binomial Negativa NB2 (maneja sobredispersión Var = mu + mu^2/r)."""
    if mu <= 0:
        return 0.0
    p = r / (r + mu)
    cdf = 0.0
    for k in range(int(k_min)):
        log_pmf = math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p)
        cdf += math.exp(log_pmf)
    return max(0.01, min(0.95, 1.0 - cdf))


def ajuste_situacional(lado, proy, linea):
    """Ajuste situacional acotado a ±3%."""
    a, mot = 0.0, []
    if lado == "under":
        if proy["fat_h"] or proy["fat_a"]:
            a += 0.015; mot.append("fatiga <=72h")
        if linea <= 2.25:
            a += 0.015; mot.append("mercado espera partido cerrado")
    elif lado == "over":
        if proy["fat_h"] and proy["fat_a"]:
            a -= 0.02; mot.append("ambos con fatiga <=72h")
        if linea >= 3.0:
            a += 0.015; mot.append("mercado espera partido abierto")
    return max(-ADJ_CAP, min(ADJ_CAP, a)), ", ".join(mot) or "neutral"


def evaluar_partido(g, proy, cc, n_muestra=10):
    """Evalúa mercados con Dixon-Coles + Shrinkage Jerárquico w = n/(n+k) + EV real (p*O - 1)."""
    m1 = matriz_dixon_coles(proy["cal_h"], proy["cal_a"])
    m2 = matriz_dixon_coles(proy["l5_h"], proy["l5_a"])
    p1, p2 = probs_matriz(m1), probs_matriz(m2)
    linea = g["dk"]["total"] or 2.5
    disc = round(proy["total"] - linea, 2)
    alerta_tot = f"AVISO modelo difiere {disc:+.2f} goles de la línea" if abs(disc) > DISC_TOTAL else None

    nvh, nvd, nva, vig = devig_1x2(g["dk"]["ml_home"], g["dk"]["ml_draw"], g["dk"]["ml_away"])

    # Shrinkage jerárquico por tamaño de muestra: w = n / (n + k) — k=14 en UCL/UEL, k=8 en ligas domésticas
    n_eff = max(1, int(n_muestra or 4))
    k_liga = 14.0 if g.get("liga") in ("uefa.champions", "uefa.europa") else 8.0
    w_mod = round(n_eff / (n_eff + k_liga), 4)

    # Anclaje al mercado: matriz Dixon-Coles implícita en la línea oficial + 1X2 sin vig
    share_h = (nvh / (nvh + nva)) if (nvh and nva and (nvh + nva) > 0) else 0.55
    mkt_h = max(0.40, linea * share_h)
    mkt_a = max(0.35, linea * (1.0 - share_h))
    mm = matriz_dixon_coles(mkt_h, mkt_a)
    pm = probs_matriz(mm)
    vig_m = 1.055  # margen estándar de casa ~5.5%

    def _shrink(p_mod, p_mkt):
        return round(w_mod * p_mod + (1.0 - w_mod) * p_mkt, 4)

    def _ev(p_real, cuota):
        return round(p_real * cuota - 1.0, 4)

    sel = []

    # 1. Lado Protegido: Doble Oportunidad (1X o X2) o Ganador Pago Anticipado 2G
    fav_home = p1["p_home"] >= p1["p_away"]
    t_fav = g["home"]["nombre"] if fav_home else g["away"]["nombre"]
    if fav_home:
        pm_dc = round(nvh + nvd, 4) if (nvh and nvd) else pm["p_1x"]
        prob_dc = _shrink(min(p1["p_1x"], p2["p_1x"]), pm_dc)
        cuota_dc = cc.get("dc_1x") or round(max(1.12, 1 / min(0.89, pm_dc * vig_m)), 2)
        est_dc = "dc_1x" not in cc
        ev_dc = _ev(prob_dc, cuota_dc)
        sel.append(dict(
            tipo="Doble Oportunidad", seleccion=f"{t_fav} o Empate (1X)",
            p1=p1["p_1x"], p2=p2["p_1x"], prob=prob_dc, prob_novig=pm_dc,
            cuota=cuota_dc, cuota_est=est_dc, implicita=1 / cuota_dc,
            edge_pp=round(prob_dc - pm_dc, 4), ventaja=ev_dc, ev_ajustado=round(ev_dc * w_mod, 4), w_mod=w_mod,
            estado=estado_sel("lado", linea, cuota_dc, est_dc, ventaja=ev_dc, edge_pp=prob_dc - pm_dc), vig=vig,
        ))
        if p1["p_home_2g"] >= 0.68:
            pm_2g = nvh or pm["p_home"]
            cuota_ml = cc.get("ml_local") or g["dk"]["ml_home"] or 1.45
            est_ml = "ml_local" not in cc and not g["dk"]["ml_home"]
            prob_2g = _shrink(min(p1["p_home_2g"], p2["p_home_2g"]), min(0.92, pm_2g + 0.03))
            ev_2g = _ev(prob_2g, cuota_ml)
            sel.append(dict(
                tipo="Ganador (2 Goles)", seleccion=f"{t_fav} Ganador (Pago Ant. 2G)",
                p1=p1["p_home_2g"], p2=p2["p_home_2g"], prob=prob_2g, prob_novig=pm_2g,
                cuota=cuota_ml, cuota_est=est_ml, implicita=1 / cuota_ml,
                edge_pp=round(prob_2g - pm_2g, 4), ventaja=ev_2g, ev_ajustado=round(ev_2g * w_mod, 4), w_mod=w_mod,
                estado=estado_sel("lado", linea, cuota_ml, est_ml, ventaja=ev_2g, edge_pp=prob_2g - pm_2g), vig=vig,
            ))
    else:
        pm_dc = round(nva + nvd, 4) if (nva and nvd) else pm["p_x2"]
        prob_dc = _shrink(min(p1["p_x2"], p2["p_x2"]), pm_dc)
        cuota_dc = cc.get("dc_x2") or round(max(1.12, 1 / min(0.89, pm_dc * vig_m)), 2)
        est_dc = "dc_x2" not in cc
        ev_dc = _ev(prob_dc, cuota_dc)
        sel.append(dict(
            tipo="Doble Oportunidad", seleccion=f"{t_fav} o Empate (X2)",
            p1=p1["p_x2"], p2=p2["p_x2"], prob=prob_dc, prob_novig=pm_dc,
            cuota=cuota_dc, cuota_est=est_dc, implicita=1 / cuota_dc,
            edge_pp=round(prob_dc - pm_dc, 4), ventaja=ev_dc, ev_ajustado=round(ev_dc * w_mod, 4), w_mod=w_mod,
            estado=estado_sel("lado", linea, cuota_dc, est_dc, ventaja=ev_dc, edge_pp=prob_dc - pm_dc), vig=vig,
        ))

    # 2. Totales UNDER (Under 3.5 Protegido + Under 2.5 Estándar) — con shrinkage y EV real
    adj_u, mot_u = ajuste_situacional("under", proy, linea)
    for ln_u, key_u, tipo_u, lbl_u in (
        (3.5, "p_u35", "Total UNDER 3.5", "Under 3.5 Goles"),
        (2.5, "p_u25", "Total UNDER 2.5", "Under 2.5 Goles"),
    ):
        pu1, pu2 = min(0.92, p1[key_u] + adj_u), min(0.92, p2[key_u] + adj_u)
        pm_u = pm[key_u]
        prob_u = _shrink(min(pu1, pu2), pm_u)
        cuota_u = cc.get(f"under{int(ln_u*10)}") or round(max(1.12, 1 / min(0.90, max(0.20, pm_u) * vig_m)), 2)
        est_u = f"under{int(ln_u*10)}" not in cc
        ev_u = _ev(prob_u, cuota_u)
        sel.append(dict(
            tipo=tipo_u, seleccion=lbl_u, linea_alt=ln_u,
            base1=p1[key_u], base2=p2[key_u], adj=adj_u, motivo=mot_u,
            p1=pu1, p2=pu2, prob=prob_u, prob_novig=round(pm_u, 4), cuota=cuota_u, cuota_est=est_u,
            implicita=1 / cuota_u, edge_pp=round(prob_u - pm_u, 4), ventaja=ev_u,
            ev_ajustado=round(ev_u * w_mod, 4), w_mod=w_mod,
            estado=estado_sel("under", linea, cuota_u, est_u, disc=alerta_tot, ventaja=ev_u, edge_pp=prob_u - pm_u),
        ))

    # 3. Totales OVER (Over 1.5 Protegido + Over 2.5 Estándar) — con shrinkage y EV real
    adj_o, mot_o = ajuste_situacional("over", proy, linea)
    for ln_o, key_o, tipo_o, lbl_o in (
        (1.5, "p_o15", "Total OVER 1.5", "Over 1.5 Goles"),
        (2.5, "p_o25", "Total OVER 2.5", "Over 2.5 Goles"),
    ):
        po1, po2 = min(0.92, p1[key_o] + adj_o), min(0.92, p2[key_o] + adj_o)
        pm_o = pm[key_o]
        prob_o = _shrink(min(po1, po2), pm_o)
        cuota_o = cc.get(f"over{int(ln_o*10)}") or round(max(1.12, 1 / min(0.90, max(0.20, pm_o) * vig_m)), 2)
        est_o = f"over{int(ln_o*10)}" not in cc
        ev_o = _ev(prob_o, cuota_o)
        sel.append(dict(
            tipo=tipo_o, seleccion=lbl_o, linea_alt=ln_o,
            base1=p1[key_o], base2=p2[key_o], adj=adj_o, motivo=mot_o,
            p1=po1, p2=po2, prob=prob_o, prob_novig=round(pm_o, 4), cuota=cuota_o, cuota_est=est_o,
            implicita=1 / cuota_o, edge_pp=round(prob_o - pm_o, 4), ventaja=ev_o,
            ev_ajustado=round(ev_o * w_mod, 4), w_mod=w_mod,
            estado=estado_sel("over", linea, cuota_o, est_o, disc=alerta_tot, ventaja=ev_o, edge_pp=prob_o - pm_o),
        ))

    # 4. Ambos Marcan (BTTS Sí / No) — usa cuota real de The Odds API / CSV si existe
    btts_si = p1["p_btts"] >= 0.50
    pb1 = p1["p_btts"] if btts_si else (1.0 - p1["p_btts"])
    pb2 = p2["p_btts"] if btts_si else (1.0 - p2["p_btts"])
    pm_btts = pm["p_btts"] if btts_si else (1.0 - pm["p_btts"])
    prob_btts = _shrink(min(pb1, pb2), pm_btts)
    k_btts = "btts_si" if btts_si else "btts_no"
    cuota_btts = cc.get(k_btts) or round(max(1.20, 1 / min(0.86, max(0.20, pm_btts) * vig_m)), 2)
    est_btts = k_btts not in cc
    ev_btts = _ev(prob_btts, cuota_btts)
    sel.append(dict(
        tipo="Ambos Marcan", seleccion="Ambos Marcan — SÍ" if btts_si else "Ambos Marcan — NO",
        p1=pb1, p2=pb2, prob=prob_btts, prob_novig=round(pm_btts, 4), cuota=cuota_btts, cuota_est=est_btts,
        implicita=1 / cuota_btts, edge_pp=round(prob_btts - pm_btts, 4),
        ventaja=ev_btts, ev_ajustado=round(ev_btts * w_mod, 4), w_mod=w_mod,
        estado=estado_sel("btts", linea, cuota_btts, est_btts, ventaja=ev_btts, edge_pp=prob_btts - pm_btts),
    ))

    # 5. Hándicap Protegido (+1.5 al underdog) — con shrinkage y EV real
    p_dog1 = sum(m1[i][j] for i in range(len(m1)) for j in range(len(m1)) if ((j - i) >= -1 if fav_home else (i - j) >= -1))
    p_dog2 = sum(m2[i][j] for i in range(len(m2)) for j in range(len(m2)) if ((j - i) >= -1 if fav_home else (i - j) >= -1))
    pm_dog = sum(mm[i][j] for i in range(len(mm)) for j in range(len(mm)) if ((j - i) >= -1 if fav_home else (i - j) >= -1))
    dog_nom = g["away"]["nombre"] if fav_home else g["home"]["nombre"]
    prob_ah = _shrink(min(p_dog1, p_dog2), pm_dog)
    cuota_ah = round(max(1.18, 1 / min(0.86, max(0.20, pm_dog) * vig_m)), 2)
    ev_ah = _ev(prob_ah, cuota_ah)
    sel.append(dict(
        tipo="Hándicap +1.5", seleccion=f"{dog_nom} +1.5 Goles",
        p1=p_dog1, p2=p_dog2, prob=prob_ah, prob_novig=round(pm_dog, 4), cuota=cuota_ah, cuota_est=True,
        implicita=1 / cuota_ah, edge_pp=round(prob_ah - pm_dog, 4),
        ventaja=ev_ah, ev_ajustado=round(ev_ah * w_mod, 4), w_mod=w_mod,
        estado=estado_sel("ah", linea, cuota_ah, True, ventaja=ev_ah, edge_pp=prob_ah - pm_dog),
    ))

    return sel, p1, p2


def estado_sel(tipo, linea, cuota, cuota_est=False, disc=None, ventaja=None, edge_pp=None):
    if tipo == "over" and linea <= LOW_LINE:
        return f"BLOQUEADO LÍNEA BAJA (≤{LOW_LINE} goles)"
    if cuota < ODDS_MIN or cuota > ODDS_MAX:
        return f"BLOQUEADO FUERA DE RANGO ({cuota:.2f})"
    av = []
    if disc:
        av.append(disc)
    if edge_pp is not None and abs(edge_pp) > 0.15:
        av.append(f"DISCREPANCIA EXTREMA ({edge_pp*100:+.1f} pp)")
    if ventaja is not None and ventaja <= 0:
        av.append(f"sin +EV ({ventaja*100:+.1f}%)")
    return ("AVISO: " + "; ".join(av)) if av else "LUZ VERDE"


def bloqueado(est):
    return est.startswith("BLOQUEADO") or est.startswith("EN CUARENTENA")


def sugerir_props(g, proy, pl_h, pl_a, lg):
    """Player Props de Fútbol con Binomial Negativa (NB2): Porteros (Atajadas), Remates Totales y A Puerta."""
    candidatos = []
    for side, pl, fat, lam_eq, lam_lg, lam_opp, lam_opp_lg in (
        ("home", pl_h, proy["fat_h"], proy["cal_h"], lg["lg_home"], proy["cal_a"], lg["lg_away"]),
        ("away", pl_a, proy["fat_a"], proy["cal_a"], lg["lg_away"], proy["cal_h"], lg["lg_home"]),
    ):
        mult_atk = max(0.75, min(1.35, lam_eq / max(0.8, lam_lg)))
        mult_def = max(0.75, min(1.40, lam_opp / max(0.7, lam_opp_lg)))
        eq = g[side]
        pen = 0.04 if fat else 0.0
        filtro = "⚠️ Fatiga ≤72h (riesgo rotación)" if fat else "Titular habitual (sin fatiga)"
        for p in pl:
            base = dict(
                partido=g["partido"], liga=g["liga_nombre"], liga_slug=g["liga"],
                hora=g["hora"], estado_g=g["estado"],
                equipo=eq["nombre"], logo=eq["logo"], jugador=p["nombre"],
                cuota=1.45, fatiga=fat, filtro=filtro,
            )
            # 1. Porteros: Atajadas (NB2 con r=3.0 por alta sobredispersión)
            sv = p.get("sv_pg", 0) * mult_def
            if sv >= 2.2:
                pr = max(0.05, min(0.92, nb2_over(2, sv, r=3.0) - pen))
                candidatos.append(dict(base, cat="PORTEROS", prop="Over 1.5 Atajadas", linea=1.5,
                                       promedio=f"{p['sv_pg']:.1f} Ataj/PJ ({p['pj']} PJ)", prob=round(pr, 4)))
            if sv >= 3.3:
                pr = max(0.05, min(0.92, nb2_over(3, sv, r=3.0) - pen))
                candidatos.append(dict(base, cat="PORTEROS", prop="Over 2.5 Atajadas", linea=2.5,
                                       promedio=f"{p['sv_pg']:.1f} Ataj/PJ ({p['pj']} PJ)", prob=round(pr, 4)))
            # 2. Remates Totales (NB2 con r=4.0)
            sh = p.get("sh_pg", 0) * mult_atk
            if sh >= 2.2:
                pr = max(0.05, min(0.92, nb2_over(2, sh, r=4.0) - pen))
                candidatos.append(dict(base, cat="REMATES", prop="Over 1.5 Remates", linea=1.5,
                                       promedio=f"{p['sh_pg']:.1f} Rem/PJ ({p['pj']} PJ)", prob=round(pr, 4)))
            if sh >= 3.4:
                pr = max(0.05, min(0.92, nb2_over(3, sh, r=4.0) - pen))
                candidatos.append(dict(base, cat="REMATES", prop="Over 2.5 Remates", linea=2.5,
                                       promedio=f"{p['sh_pg']:.1f} Rem/PJ ({p['pj']} PJ)", prob=round(pr, 4)))
            # 3. Remates a Puerta (NB2 con r=4.5)
            sot = p.get("sot_pg", 0) * mult_atk
            if sot >= 0.9:
                pr = max(0.05, min(0.92, nb2_over(1, sot, r=4.5) - pen))
                candidatos.append(dict(base, cat="A PUERTA", prop="Over 0.5 Remates a Puerta", linea=0.5,
                                       promedio=f"{p['sot_pg']:.1f} SoT/PJ ({p['pj']} PJ)", prob=round(pr, 4)))
            if sot >= 1.9:
                pr = max(0.05, min(0.92, nb2_over(2, sot, r=4.5) - pen))
                candidatos.append(dict(base, cat="A PUERTA", prop="Over 1.5 Remates a Puerta", linea=1.5,
                                       promedio=f"{p['sot_pg']:.1f} SoT/PJ ({p['pj']} PJ)", prob=round(pr, 4)))
    candidatos.sort(key=lambda x: -x["prob"])
    return candidatos
