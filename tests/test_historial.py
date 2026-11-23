"""Tests unitarios de integridad de historial.db y migración legacy."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import historial as H


def test_migracion_legacy_conserva_filas():
    db = ROOT / "historial.db"
    if not db.exists():
        return
    c0 = sqlite3.connect(db)
    antes = c0.execute("SELECT COUNT(*) FROM picks").fetchone()[0]
    c0.close()

    with H._conn() as c:
        despues = c.execute("SELECT COUNT(*) FROM picks").fetchone()[0]
        cols = {r[1] for r in c.execute("PRAGMA table_info(picks)").fetchall()}
        leg = c.execute("SELECT COUNT(*) FROM picks WHERE is_legacy=1").fetchone()[0]
        sin_nv = c.execute("SELECT COUNT(*) FROM picks WHERE prob_mercado_novig IS NULL").fetchone()[0]

    assert antes == despues, f"Filas cambiaron: {antes} != {despues}"
    for req in ("is_legacy", "n_muestra", "cuota_apertura", "cuota_cierre", "prob_mercado_novig", "cuota_es_real"):
        assert req in cols, f"Falta columna {req}"
    assert leg == sin_nv, f"Legacy ({leg}) != sin_novig ({sin_nv})"
    print(f"HISTORIAL OK: total={despues}, legacy={leg}, nuevos_con_novig={despues - leg}")


if __name__ == "__main__":
    test_migracion_legacy_conserva_filas()
