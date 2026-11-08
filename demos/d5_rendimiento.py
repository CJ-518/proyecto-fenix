# -*- coding: utf-8 -*-
"""Demo 5 - Rendimiento: efecto de los indices (en vivo) y comparacion con las planillas (benchmark.json)."""
import statistics, time
import sqlite3

from comun import conectar, cargar_json, n, titulo, seccion, tabla

con = conectar()
bench = cargar_json("benchmark.json")
titulo("DEMO 5 · OPTIMIZACIÓN Y RENDIMIENTO",
       "Mediana de 15 ejecuciones en SQLite con ~11 mil filas: sirve para comparar estructuras, no para predecir produccion")


def medir(c, consulta, args=(), reps=15):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        c.execute(consulta, args).fetchall()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


def plan(c, consulta, args=()):
    return " | ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + consulta, args).fetchall())


cod = bench["establecimiento_ejemplo"]
Q3 = ("""SELECT i.categoria, e.monto_adjudicado FROM entrega e JOIN item i USING(id_item)
         JOIN establecimiento es USING(id_establecimiento) WHERE es.codigo = ?""", (cod,))
Q4 = ("""SELECT i.descripcion, SUM(e.cantidad) FROM entrega e JOIN item i USING(id_item)
         WHERE i.categoria='MOBILIARIO' GROUP BY i.descripcion""", ())

seccion("EN VIVO: la misma consulta con y sin indices secundarios")
sin = sqlite3.connect(":memory:")
con.backup(sin)
for (nm,) in sin.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'").fetchall():
    sin.execute(f"DROP INDEX {nm}")
filas = []
for nombre, (qs, qa) in [("Q3 Entregas de un establecimiento", Q3), ("Q4 Cantidad por tipo de mobiliario", Q4)]:
    a, b = medir(sin, qs, qa), medir(con, qs, qa)
    filas.append((nombre, f"{a:.3f}", f"{b:.3f}", f"{a / b:.0f}x"))
tabla(["consulta", "sin indices (ms)", "con indices (ms)", "mejora"], filas, "lrrr")
print("\n  Plan de Q3 SIN indices:", plan(sin, *Q3))
print("  Plan de Q3 CON indices:", plan(con, *Q3))

seccion("Planillas legacy vs. base normalizada (medido al construir el informe)")
filas = []
for k, v in bench["consultas"].items():
    filas.append((k[:52], f"{v['legacy_ms']:.3f}", f"{v['normalizado_sin_indices_ms']:.3f}",
                  f"{v['normalizado_con_indices_ms']:.3f}"))
tabla(["consulta", "legacy (ms)", "normalizada s/ind. (ms)", "normalizada c/ind. (ms)"], filas, "lrrr")
print("\n  Lectura honesta: las consultas globales NO mejoran con este volumen (Q1 igual, Q2 incluso es mas lenta);")
print("  la busqueda puntual (Q3) si mejora, y Q4 solo es rapida gracias a los indices.")

seccion("Almacenamiento y calidad")
k = bench["tamano_kb"]
print(f"  Legacy      : {n(k['legacy'])} KB")
print(f"  Normalizada : {n(k['normalizado'])} KB   ({n(100 * (k['normalizado'] / k['legacy'] - 1), 1)} %)")
q1 = next(v for k, v in bench["consultas"].items() if k.startswith("Q1"))
print(f"  Empresas    : la consulta Q1 devolvia {q1['filas_legacy']} grupos en las planillas (variantes de nombre) -> {q1['filas_normalizado']} empresas reales")
print("\n  Para repetir la comparacion con las planillas originales (requiere datos/):")
print("      python scripts/benchmark_fenix.py")
