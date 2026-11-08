#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proyecto Fenix - Lanzador de demos para la presentacion.

Uso:
  python demo.py            menu interactivo
  python demo.py 3          ejecuta solo la demo 3
  python demo.py todo       ejecuta las demos 1 a 5 con pausa entre cada una
  python demo.py migracion  ejecuta la migracion real (requiere las planillas en datos/)
  python demo.py benchmark  ejecuta el benchmark completo (requiere las planillas en datos/)
"""
import glob, os, subprocess, sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
DEMOS = {
    "1": ("Modelo rediseñado (11 tablas en 3FN, reglas en el motor)", "demos/d1_modelo.py"),
    "2": ("Calidad de datos: antes y después", "demos/d2_calidad.py"),
    "3": ("Conciliación origen–destino e integridad", "demos/d3_conciliacion.py"),
    "4": ("Lo que revela la nueva base", "demos/d4_hallazgos.py"),
    "5": ("Optimización y rendimiento", "demos/d5_rendimiento.py"),
}
PIPELINE = {
    "migracion": ("Migración real (Excel -> SQLite 3FN)", "scripts/migracion_fenix.py"),
    "benchmark": ("Benchmark completo (planillas vs. base)", "scripts/benchmark_fenix.py"),
}


def correr(ruta):
    r = subprocess.run([sys.executable, os.path.join(RAIZ, ruta)], cwd=RAIZ)
    if r.returncode:
        print(f"\n[el script termino con codigo {r.returncode}]")


def hay_planillas():
    return bool(glob.glob(os.path.join(RAIZ, "datos", "Encabezado_*.xls*")))


def menu():
    while True:
        print("\nPROYECTO FÉNIX · demos")
        for k, (t, _) in DEMOS.items():
            print(f"  {k}) {t}")
        estado = "planillas encontradas" if hay_planillas() else "faltan las planillas en datos/"
        print(f"  m) {PIPELINE['migracion'][0]}   [{estado}]")
        print(f"  b) {PIPELINE['benchmark'][0]}")
        print("  t) Todas las demos (1 a 5)")
        print("  q) Salir")
        op = input("> ").strip().lower()
        if op in ("q", ""):
            return
        ejecutar(op)


def ejecutar(op):
    op = {"m": "migracion", "b": "benchmark", "t": "todo"}.get(op, op)
    if op in DEMOS:
        correr(DEMOS[op][1])
    elif op in PIPELINE:
        correr(PIPELINE[op][1])
    elif op == "todo":
        for k, (_, ruta) in DEMOS.items():
            correr(ruta)
            if k != list(DEMOS)[-1] and sys.stdin.isatty():
                input("\n[Enter para continuar]")
    else:
        print(f"Opcion no valida: {op}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ejecutar(sys.argv[1].lower())
    else:
        menu()
