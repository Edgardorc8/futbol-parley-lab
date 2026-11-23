"""Tests unitarios mínimos para el motor cuantitativo de Fútbol Parley Lab."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import motor as M


def test_dixon_coles_suma_uno():
    m = M.matriz_dixon_coles(1.6, 1.2)
    tot = sum(sum(r) for r in m)
    assert abs(tot - 1.0) < 1e-6


def test_power_devig_suma_uno():
    p1, px, p2, vig = M.devig_1x2(1.80, 3.60, 4.50)
    assert abs((p1 + px + p2) - 1.0) < 0.002
    assert vig > 0


def test_sanity_check_discrepancia_extrema():
    st = M.estado_sel("btts", 2.5, 2.26, False, ventaja=0.65, edge_pp=0.289)
    assert "DISCREPANCIA EXTREMA" in st


def test_nb2_over_valido():
    p = M.nb2_over(2, 3.0, r=4.0)
    assert 0.50 < p < 0.90


if __name__ == "__main__":
    test_dixon_coles_suma_uno()
    test_power_devig_suma_uno()
    test_sanity_check_discrepancia_extrema()
    test_nb2_over_valido()
    print("ALL TESTS PASSED")
