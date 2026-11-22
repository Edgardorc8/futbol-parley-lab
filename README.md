# Fútbol Parley Lab

Aplicación web local para análisis cuantitativo de Fútbol Europeo de Élite (**Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, UEFA Champions League y UEFA Europa League**).

## Motor Cuantitativo
- **Calibración 65/35**: Modelo Multiplicativo de temporada (`65%`) + Entorno real de Últimos 5 Juegos `L5` (`35%`).
- **Poisson + Corrección Dixon-Coles ($\rho = -0.11$)**: Matriz exacta de marcadores ajustada para empates y marcadores bajos (`0-0`, `1-0`, `0-1`, `1-1`).
- **Doble Escenario**: Escenario 1 (Calibrado `65/35`) vs. Escenario 2 (Entorno `L5`) con selección conservadora (`min(P1, P2)`).
- **Gestión de Riesgo**: Candado de línea baja ($\le 2.25$ goles), penalización por fatiga europea ($\le 72\text{h}$), Devigging 3-way (`1X2`), Pago Anticipado (`2 Goles de Ventaja`), Historial SQLite y reporte Excel.

## Cómo ejecutar
Haz doble clic en **`iniciar.bat`** o ejecuta `python server.py` y abre `http://localhost:8001`.
