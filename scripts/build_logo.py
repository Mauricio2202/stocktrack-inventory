"""Genera el logo de StockTrack (SVG + PNG).

Uso:  python scripts/build_logo.py
Salida: stocktrack/static/img/{logo.svg, logo-white.svg, icon.svg, logo.png, icon.png}

El ícono es una caja isométrica (inventario) con una palomita (control) en su cara
izquierda, barras ascendentes (seguimiento) en la derecha y un punto ámbar (alerta).
Requiere `rsvg-convert` para los PNG; si no está instalado solo se generan los SVG.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "stocktrack" / "static" / "img"
FONT = "Inter, 'Helvetica Neue', Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif"

NAVY, TEAL, AMBER = "#0f2742", "#0e9aa7", "#f59e0b"


def icon_group() -> str:
    return f"""
  <rect width="120" height="120" rx="27" fill="{NAVY}"/>
  <polygon points="60,18 96,39 60,60 24,39" fill="#a5eef2"/>
  <polygon points="24,39 60,60 60,102 24,81" fill="#1fb5c3"/>
  <polygon points="60,60 96,39 96,81 60,102" fill="#0e8595"/>
  <g transform="matrix(1 0.5833 0 1 0 0)">
    <polyline points="33,46 40,53 52,38" fill="none" stroke="#ffffff" stroke-width="5.5"
              stroke-linecap="round" stroke-linejoin="round"/>
  </g>
  <g transform="matrix(1 -0.5833 0 1 0 0)" fill="#ffffff" fill-opacity="0.92">
    <rect x="66" y="122" width="6" height="9" rx="1"/>
    <rect x="76" y="114" width="6" height="17" rx="1"/>
    <rect x="86" y="105" width="6" height="26" rx="1"/>
  </g>
  <circle cx="98" cy="25" r="10.5" fill="{AMBER}" stroke="{NAVY}" stroke-width="4"/>
  <rect x="96.8" y="19.5" width="2.4" height="7" rx="1.2" fill="#ffffff"/>
  <circle cx="98" cy="29.2" r="1.4" fill="#ffffff"/>
"""


def horizontal(stock_fill: str, track_fill: str, tagline_fill: str, label: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 140" width="560" height="140" role="img" aria-label="{label}">
  <title>{label}</title>
  <g transform="translate(10 10)">{icon_group()}</g>
  <text x="152" y="84" font-family="{FONT}" font-size="60" font-weight="800" letter-spacing="-1.5">
    <tspan fill="{stock_fill}">Stock</tspan><tspan fill="{track_fill}">Track</tspan>
  </text>
  <text x="155" y="116" font-family="{FONT}" font-size="15.5" font-weight="600" letter-spacing="3.2"
        fill="{tagline_fill}">CONTROL TOTAL DE INVENTARIOS</text>
</svg>
"""


def icon_only() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120" role="img" aria-label="StockTrack">
  <title>StockTrack</title>{icon_group()}</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "logo.svg": horizontal(NAVY, TEAL, "#5b6b7e", "StockTrack - Control total de inventarios"),
        "logo-white.svg": horizontal("#ffffff", "#5eead4", "#b8c7d8", "StockTrack - Control total de inventarios"),
        "icon.svg": icon_only(),
    }
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")

    rsvg = shutil.which("rsvg-convert")
    if not rsvg:
        print("rsvg-convert no encontrado: solo se generaron los SVG")
        return
    subprocess.run([rsvg, "-w", "1120", str(OUT / "logo.svg"), "-o", str(OUT / "logo.png")], check=True)
    subprocess.run([rsvg, "-w", "512", "-h", "512", str(OUT / "icon.svg"), "-o", str(OUT / "icon.png")], check=True)
    print("Logo generado en", OUT)


if __name__ == "__main__":
    main()
