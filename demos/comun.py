"""Utilidades compartidas por las demos (solo biblioteca estandar)."""
import json
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "salida")
DB = os.path.join(SALIDA, "fenix_normalizada.db")

_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure:
    _reconfigure(encoding="utf-8")


def conectar():
    if not os.path.exists(DB):
        sys.exit(f"No existe {DB}. Ejecute scripts/migracion_fenix.py o restaure la base incluida.")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def cargar_json(nombre):
    with open(os.path.join(SALIDA, nombre), encoding="utf-8") as f:
        return json.load(f)


def n(x, dec=0):
    """Formato con punto de miles y coma decimal (estilo es-PY)."""
    if x is None:
        return "-"
    if round(x, dec) == 0:
        x = 0.0  # evita "-0"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def titulo(texto, sub=None):
    print()
    print("=" * 78)
    print(f"  {texto}")
    if sub:
        print(f"  {sub}")
    print("=" * 78)


def seccion(texto):
    print(f"\n--- {texto}")


def tabla(cabecera, filas, alinear=None):
    """Imprime una tabla de texto. alinear: cadena con 'l'/'r' por columna."""
    filas = [[("-" if c is None else str(c)) for c in f] for f in filas]
    anchos = [max(len(str(h)), *(len(f[i]) for f in filas)) if filas else len(str(h))
              for i, h in enumerate(cabecera)]
    alinear = alinear or "l" * len(cabecera)

    def fila(vals):
        return "  ".join(v.rjust(anchos[i]) if alinear[i] == "r" else v.ljust(anchos[i])
                         for i, v in enumerate(vals))
    print(fila([str(h) for h in cabecera]))
    print("  ".join("-" * a for a in anchos))
    for f in filas:
        print(fila(f))


def sql(con, consulta, mostrar=True):
    """Muestra la consulta SQL (para que la audiencia vea que es real) y devuelve filas."""
    if mostrar:
        print("\n  SQL> " + " ".join(consulta.split()))
    return con.execute(consulta).fetchall()
