#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proyecto Fenix - Benchmark de optimizacion (Fase 3)
Compara consultas sobre las planillas legacy cargadas "tal cual" (sin indices ni tipos)
contra el esquema normalizado con indices. Requiere haber corrido migracion_fenix.py.
Uso: python3 scripts/benchmark_fenix.py [carpeta_datos] [carpeta_salida]
     (por defecto: ./datos y ./salida, relativas a la raiz del repositorio)
"""
import sys, os, re, glob, json, time, sqlite3, statistics, warnings
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "datos")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "salida")
NORM = os.path.join(OUT, "fenix_normalizada.db")
LEG = os.path.join(OUT, "fenix_legacy_benchmark.db")

def slug(c):
    c = c.split("\n")[0]
    return re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_")

def build_legacy():
    if not glob.glob(os.path.join(DATA, "Encabezado_*.xls*")):
        sys.exit(f"No se encontraron las planillas Encabezado_*.xls* en '{DATA}'.\n"
                 "Copielas en la carpeta datos/ (ver datos/LEEME.md) o pase la ruta como primer argumento.")
    if os.path.exists(LEG):
        os.remove(LEG)
    con = sqlite3.connect(LEG)
    p = pd.read_excel(os.path.join(DATA, "Encabezado_PARQUES_EXPANSION_UV.xlsx"))
    m = pd.read_excel(glob.glob(os.path.join(DATA, "Encabezado_MATERIALES*"))[0], sheet_name=0)
    b = pd.read_excel(glob.glob(os.path.join(DATA, "Encabezado_MOBILIARIO*"))[0])
    t = pd.read_excel(glob.glob(os.path.join(DATA, "Encabezado_DOTAC*"))[0])
    for name, df in [("leg_parques", p), ("leg_materiales", m), ("leg_mobiliario", b), ("leg_tic", t)]:
        df = df.copy()
        df.columns = [slug(c) for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        for c in df.columns:  # fechas a texto como en una planilla
            if str(df[c].dtype).startswith("datetime"):
                df[c] = df[c].astype(str)
        df.to_sql(name, con, index=False)
    con.commit()
    return con

def timeit(con, sql, args=(), reps=15):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        rows = con.execute(sql, args).fetchall()
        ts.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(ts), 3), len(rows), rows

def plan(con, sql, args=()):
    return [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, args).fetchall()]

def nf(x, dec=0):
    """Numero con punto de miles y coma decimal."""
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_resumen(res):
    """Resumen legible del benchmark (el detalle y los planes quedan en benchmark.json)."""
    print("\n" + "=" * 78)
    print("  BENCHMARK COMPLETADO  (mediana de 15 ejecuciones, en milisegundos)")
    print("=" * 78)
    print(f"\n{'consulta':<52}{'legacy':>8}{'s/indices':>11}{'c/indices':>11}")
    for k, v in res["consultas"].items():
        print(f"{k[:51]:<52}{v['legacy_ms']:>8.3f}{v['normalizado_sin_indices_ms']:>11.3f}{v['normalizado_con_indices_ms']:>11.3f}")
    t = res["tamano_kb"]
    print(f"\nTamano en disco: legacy {nf(t['legacy'])} KB -> normalizada {nf(t['normalizado'])} KB "
          f"({nf(100 * (t['normalizado'] / t['legacy'] - 1), 1)} %)")
    print(f"Formatos distintos de latitud en el origen: {res['formatos_latitud_origen']}; "
          f"latitudes no decimales en el destino: {res['latitud_no_decimal_destino']}")
    print("\nDetalle y planes de ejecucion en salida/benchmark.json")


def main():
    leg = build_legacy()
    nor = sqlite3.connect(NORM)
    cod_ej = nor.execute("""SELECT es.codigo FROM entrega e JOIN establecimiento es USING(id_establecimiento)
                            GROUP BY es.codigo ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()[0]
    cod_int = int(cod_ej)
    res = {"establecimiento_ejemplo": cod_ej}

    Q = {}
    Q["Q1 Monto adjudicado por empresa (4 categorias)"] = (
        """SELECT empresa1, SUM(monto_adjudicado1) FROM (
             SELECT empresa1, monto_adjudicado1 FROM leg_parques UNION ALL
             SELECT empresa1, monto_adjudicado1 FROM leg_materiales UNION ALL
             SELECT empresa1, monto_adjudicado1 FROM leg_mobiliario UNION ALL
             SELECT empresa1, monto_adjudicado1 FROM leg_tic) GROUP BY empresa1""", (),
        "SELECT empresa, SUM(monto_adjudicado) FROM v_entregas_detalle GROUP BY empresa", ())
    Q["Q2 Establecimientos que recibieron las 4 categorias"] = (
        """SELECT COUNT(*) FROM (
             SELECT codigoestablecimiento FROM leg_parques INTERSECT
             SELECT codigoestablecimiento FROM leg_materiales INTERSECT
             SELECT codigoestablecimiento FROM leg_mobiliario INTERSECT
             SELECT codigoestablecimiento FROM leg_tic)""", (),
        "SELECT COUNT(*) FROM v_cobertura_establecimiento WHERE categorias_recibidas = 4", ())
    Q["Q3 Todas las entregas de un establecimiento"] = (
        """SELECT 'P', monto_adjudicado1 FROM leg_parques WHERE codigoestablecimiento = ? UNION ALL
           SELECT 'M', monto_adjudicado1 FROM leg_materiales WHERE codigoestablecimiento = ? UNION ALL
           SELECT 'B', monto_adjudicado1 FROM leg_mobiliario WHERE codigoestablecimiento = ? UNION ALL
           SELECT 'T', monto_adjudicado1 FROM leg_tic WHERE codigoestablecimiento = ?""", (cod_int,) * 4,
        """SELECT i.categoria, e.monto_adjudicado FROM entrega e JOIN item i USING(id_item)
           JOIN establecimiento es USING(id_establecimiento) WHERE es.codigo = ?""", (cod_ej,))
    Q["Q4 Cantidad total entregada por tipo de mobiliario"] = (
        "SELECT mobiliario, SUM(cantidad) FROM leg_mobiliario GROUP BY mobiliario", (),
        """SELECT i.descripcion, SUM(e.cantidad) FROM entrega e JOIN item i USING(id_item)
           WHERE i.categoria='MOBILIARIO' GROUP BY i.descripcion""", ())
    res["consultas"] = {}
    for k, (sl, al, sn, an) in Q.items():
        t_leg, n_leg, r_leg = timeit(leg, sl, al)
        t_sin, n_sin, _ = timeit(nor, sn, an)
        # normalizado SIN indices secundarios (para aislar el efecto del indice)
        tmp = sqlite3.connect(":memory:"); nor.backup(tmp)
        for (nm,) in tmp.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'").fetchall():
            tmp.execute(f"DROP INDEX {nm}")
        t_noidx, _, _ = timeit(tmp, sn, an)
        res["consultas"][k] = {"legacy_ms": t_leg, "filas_legacy": n_leg, "normalizado_sin_indices_ms": t_noidx,
                               "normalizado_con_indices_ms": t_sin, "filas_normalizado": n_sin,
                               "plan_legacy": plan(leg, sl, al)[:3], "plan_normalizado": plan(nor, sn, an)[:4]}
        tmp.close()
    # tamano
    res["tamano_kb"] = {"legacy": round(os.path.getsize(LEG) / 1024), "normalizado": round(os.path.getsize(NORM) / 1024)}
    # calidad antes/despues
    shapes = set()
    for tb in ["leg_parques", "leg_materiales", "leg_mobiliario", "leg_tic"]:
        for (v,) in leg.execute(f"SELECT DISTINCT latitud FROM {tb} WHERE latitud IS NOT NULL").fetchall():
            shapes.add(re.sub(r"\d+", "9", str(v)))
    res["formatos_latitud_origen"] = len(shapes)
    res["latitud_no_decimal_destino"] = nor.execute("SELECT COUNT(*) FROM establecimiento WHERE typeof(latitud) NOT IN ('real','null')").fetchone()[0]
    res["empresa_variantes_legacy"] = leg.execute("""SELECT COUNT(DISTINCT e) FROM (
        SELECT empresa1 e FROM leg_parques UNION SELECT empresa1 FROM leg_materiales UNION
        SELECT empresa1 FROM leg_mobiliario UNION SELECT empresa1 FROM leg_tic)""").fetchone()[0]
    with open(os.path.join(OUT, "benchmark.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    imprimir_resumen(res)

if __name__ == "__main__":
    main()
