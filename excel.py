"""Generación de reporte Excel estilizado para Fútbol Parley Lab."""
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

import motor as M

NAVY, SUB, ZEBRA = "0F3D2E", "166534", "F0FDF4"
F_T = Font(size=14, bold=True, color="FFFFFF")
F_H = Font(size=10, bold=True, color="FFFFFF")
F_C = Font(size=10, color="0F172A")
FILL = lambda c: PatternFill(start_color=c, end_color=c, fill_type="solid")
BORDER = Border(*(Side(style="thin", color="CBD5E1"),) * 4)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
COLOR_ESTADO = {"LUZ ": "D1FAE5", "AVIS": "FEF3C7", "BLOQ": "FEE2E2", "EN C": "FEE2E2"}


def hoja(wb, nombre, titulo, headers, filas, anchos, pct=(), dec=()):
    ws = wb.create_sheet(nombre)
    n = len(headers)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    c = ws.cell(1, 1, titulo); c.font = F_T; c.fill = FILL(NAVY)
    ws.row_dimensions[1].height = 28
    for i, h in enumerate(headers, 1):
        c = ws.cell(3, i, h); c.font = F_H; c.fill = FILL(SUB); c.alignment = CENTER; c.border = BORDER
    for r, fila in enumerate(filas, 4):
        for i, v in enumerate(fila, 1):
            c = ws.cell(r, i, v); c.font = F_C; c.border = BORDER; c.alignment = CENTER
            if r % 2 == 0: c.fill = FILL(ZEBRA)
            if i in pct: c.number_format = "0.0%"
            elif i in dec: c.number_format = "0.00"
            if isinstance(v, str) and v[:4] in COLOR_ESTADO:
                c.fill = FILL(COLOR_ESTADO[v[:4]])
    for i, w in enumerate(anchos, 1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)].width = w
    ws.freeze_panes = "A4"
    if filas:
        ws.auto_filter.ref = f"A3:{chr(64 + n)}{3 + len(filas)}"
    return ws


def generar_excel(analisis, fecha, path):
    wb = Workbook(); wb.remove(wb.active)
    todas = [(a, s) for a in analisis for s in a["sel"]]
    eleg = sorted([x for x in todas if not M.bloqueado(x[1]["estado"])], key=lambda x: -x[1]["prob"])

    vistos, filas = set(), []
    for a, s in eleg:
        top = "★ TOP (1 por partido)" if a["g"]["partido"] not in vistos else ""
        vistos.add(a["g"]["partido"])
        filas.append([a["g"]["hora"], a["g"]["liga_nombre"], a["g"]["partido"], s["tipo"], s["seleccion"],
                      s["cuota"], s["prob"], s["implicita"], s["ventaja"], top, s["estado"]])
    hoja(wb, "Resumen", f"FÚTBOL PARLEY LAB — SELECCIONES ELEGIBLES {fecha} (VET) | Dixon-Coles ρ={M.RHO_DC}",
         ["Hora VET", "Liga", "Partido", "Mercado", "Selección", "Cuota", "Prob. Real", "Implícita",
          "Ventaja", "Combinado", "Estado"],
         filas, [10, 16, 14, 18, 28, 8, 11, 11, 10, 20, 42], pct=(7, 8, 9), dec=(6,))

    filas = []
    for a in analisis:
        g, p, dk = a["g"], a["proy"], a["g"]["dk"]
        filas.append([g["hora"], g["liga_nombre"], g["partido"], dk["ml_home"], dk["ml_draw"], dk["ml_away"],
                      dk["total"], p["mult_h"], p["mult_a"], p["l5_h"], p["l5_a"], p["cal_h"], p["cal_a"],
                      p["total"], p["l5_total"], "Sí" if p["fat_h"] else "No", "Sí" if p["fat_a"] else "No"])
    hoja(wb, "Ficha_Modelo", "FICHA TÉCNICA + MOTOR 65/35 (λ calibrado, fuente única)",
         ["Hora", "Liga", "Partido", "1", "X", "2", "Línea O/U", "Mult Loc", "Mult Vis", "L5 Loc", "L5 Vis",
          "λ Loc", "λ Vis", "Λ Calibrado", "Λ L5", "Fatiga Loc", "Fatiga Vis"],
         filas, [9, 16, 14, 7, 7, 7, 9, 9, 9, 9, 9, 9, 9, 11, 9, 10, 10], dec=tuple(range(4, 16)))

    filas = []
    for a in analisis:
        for s in a["sel"]:
            if not s["tipo"].startswith("Total"):
                continue
            filas.append([a["g"]["liga_nombre"], a["g"]["partido"], a["g"]["dk"]["total"], s["seleccion"],
                          a["proy"]["total"], a["proy"]["l5_total"], s["base1"], s["base2"], s["adj"],
                          s["motivo"], s["p1"], s["p2"], f"{s['cuota']}{' (est.)' if s['cuota_est'] else ''}",
                          s["implicita"], s["ventaja"], s["estado"]])
    ws = hoja(wb, "Poisson_DobleEscenario", "TOTALES PROTEGIDOS — POISSON DIXON-COLES DOBLE ESCENARIO",
              ["Liga", "Partido", "Línea", "Selección", "Λ 65/35", "Λ L5", "P1 Base", "P2 Base", "Ajuste",
               "Motivo", "Prob. Esc.1", "Prob. Esc.2", "Cuota", "Implícita", "Ventaja", "Estado"],
              filas, [15, 14, 8, 16, 9, 9, 9, 9, 8, 24, 10, 10, 10, 9, 9, 40],
              pct=(7, 8, 9, 11, 12, 14, 15), dec=(3, 5, 6))
    if filas:
        ws.conditional_formatting.add(f"K4:L{3 + len(filas)}", ColorScaleRule(
            start_type="num", start_value=0.60, start_color="FEE2E2", mid_type="num", mid_value=0.75,
            mid_color="FEF3C7", end_type="num", end_value=0.85, end_color="D1FAE5"))

    filas = []
    for a in analisis:
        for lado, l5 in (("home", a["l5h"]), ("away", a["l5a"])):
            for x in l5:
                filas.append([a["g"]["liga_nombre"], a["g"]["partido"], a["g"][lado]["abbr"], x["fecha"],
                              x["cond"], x["rival"], f"{int(x['pf'])}-{int(x['pa'])}", int(x["pf"] + x["pa"])])
    hoja(wb, "L5_Marcadores", "ÚLTIMOS 5 PARTIDOS OFICIALES (L5)",
         ["Liga", "Partido", "Equipo", "Fecha", "Cond.", "Rival", "Marcador", "Total"],
         filas, [16, 14, 8, 11, 8, 8, 10, 8])

    wb.save(path)
