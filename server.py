"""Web local: python server.py  ->  http://localhost:8001"""
import datetime as dt
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import fuentes as F
import historial as H
import main as P

app = FastAPI(title="Fútbol Parley Lab")
CACHE = {}
LOCK = threading.Lock()


def _fecha(f):
    return dt.date.fromisoformat(f) if f else dt.datetime.now(F.VET).date()


def _correr(fecha):
    with LOCK:
        res, path = P.generar(fecha, log=lambda *_: None)
        CACHE[str(fecha)] = dict(res=res, path=str(path), hora=dt.datetime.now(F.VET).strftime("%I:%M %p"))
        return CACHE[str(fecha)]


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/jornada")
def jornada(fecha: str = None, refrescar: bool = False):
    f = _fecha(fecha)
    d = CACHE.get(str(f)) if not refrescar else None
    d = d or _correr(f)
    return dict(actualizado=d["hora"], **d["res"])


@app.get("/api/cuotas")
def get_cuotas(fecha: str = None):
    return P.leer_cuotas(_fecha(fecha))


@app.post("/api/cuotas")
def post_cuotas(fecha: str = None, datos: dict = Body(...)):
    f = _fecha(fecha)
    P.guardar_cuotas(f, datos)
    d = _correr(f)
    return dict(ok=True, actualizado=d["hora"])


@app.get("/api/historial")
def api_historial(verificar: bool = True, solo_limpios: bool = False):
    if verificar:
        H.verificar_resultados()
    return H.resumen(solo_limpios=solo_limpios)


@app.get("/api/tickets")
def api_get_tickets():
    return H.listar_tickets()


@app.post("/api/tickets")
def api_post_ticket(datos: dict = Body(...)):
    return dict(ok=True, id=H.guardar_ticket(datos))


@app.patch("/api/tickets/{tid}")
def api_patch_ticket(tid: int, datos: dict = Body(...)):
    ok = H.estado_ticket(tid, datos.get("resultado", "PENDIENTE"), datos.get("notas"))
    if not ok:
        raise HTTPException(404, "Ticket no encontrado")
    return dict(ok=True)


@app.delete("/api/tickets/{tid}")
def api_del_ticket(tid: int):
    H.borrar_ticket(tid)
    return dict(ok=True)


@app.get("/api/excel")
def excel(fecha: str = None):
    f = _fecha(fecha)
    d = CACHE.get(str(f)) or _correr(f)
    if not Path(d["path"]).exists():
        raise HTTPException(404, "Sin partidos")
    return FileResponse(d["path"], filename=Path(d["path"]).name)


def programador():
    """Recalcula y captura cuotas de cierre cada 15 minutos."""
    while True:
        time.sleep(900)
        try:
            _correr(_fecha(None))
        except Exception as e:
            print("Error en actualización automática:", e)


if __name__ == "__main__":
    threading.Thread(target=programador, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8001)
