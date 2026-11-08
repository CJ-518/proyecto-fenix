"""
Proyecto Fenix - Carga de la base normalizada en Oracle (para explorarla con DBeaver).

Origen : salida/fenix_normalizada.db (SQLite, generada por migracion_fenix.py)
Destino: esquema de Oracle (por defecto usuario FENIX en localhost:1521/FREEPDB1)

Crea las 13 tablas, los indices y las 5 vistas, copia todos los datos y verifica
que las filas coincidan con el origen. Es idempotente: borra y reconstruye los objetos.

Requisitos: python -m pip install oracledb   (modo "thin": no necesita Oracle Client)
Antes de la primera vez, cree el usuario con scripts/oracle_crear_usuario.sql

Uso:
  python scripts/cargar_oracle.py
  python scripts/cargar_oracle.py --usuario FENIX --dsn localhost:1521/FREEPDB1
  python scripts/cargar_oracle.py --sqlite ruta/a/otra.db

La clave se lee de la variable FENIX_ORA_PASSWORD o, si no existe, se pide por teclado.
"""
import argparse
import getpass
import os
import sqlite3
import sys
from datetime import date

try:
    import oracledb
except ImportError:
    sys.exit("Falta el paquete oracledb. Instalelo con:  python -m pip install oracledb")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_POR_DEFECTO = os.path.join(ROOT, "salida", "fenix_normalizada.db")
LOTE = 5000

# Tablas en orden de dependencia (padres primero). Las columnas DATE de SQLite son texto ISO.
TABLAS = {
    "departamento": """
        CREATE TABLE departamento(
          id_departamento NUMBER(10) PRIMARY KEY,
          nombre VARCHAR2(200) NOT NULL UNIQUE)""",
    "distrito": """
        CREATE TABLE distrito(
          id_distrito NUMBER(10) PRIMARY KEY,
          id_departamento NUMBER(10) NOT NULL REFERENCES departamento(id_departamento),
          cod_distrito NUMBER(10),
          nombre VARCHAR2(200))""",
    "establecimiento": """
        CREATE TABLE establecimiento(
          id_establecimiento NUMBER(10) PRIMARY KEY,
          codigo VARCHAR2(20) UNIQUE CHECK(codigo IS NULL OR LENGTH(codigo) = 7),
          nombre VARCHAR2(300) NOT NULL,
          id_distrito NUMBER(10) REFERENCES distrito(id_distrito),
          latitud NUMBER CHECK(latitud IS NULL OR latitud BETWEEN -28 AND -19),
          longitud NUMBER CHECK(longitud IS NULL OR longitud BETWEEN -63 AND -54),
          tipo_zona VARCHAR2(20) CHECK(tipo_zona IS NULL OR tipo_zona IN ('Urbana','Rural')),
          sector VARCHAR2(20) CHECK(sector IS NULL OR sector IN ('Oficial','Priv. Subv.')),
          cai NUMBER(1) CHECK(cai IS NULL OR cai IN (0,1)),
          indigena NUMBER(1) CHECK(indigena IS NULL OR indigena IN (0,1)))""",
    "institucion": """
        CREATE TABLE institucion(
          cod_institucion NUMBER(10) PRIMARY KEY,
          nombre VARCHAR2(300) NOT NULL,
          id_establecimiento NUMBER(10) NOT NULL REFERENCES establecimiento(id_establecimiento))""",
    "empresa": """
        CREATE TABLE empresa(
          id_empresa NUMBER(10) PRIMARY KEY,
          nombre VARCHAR2(300) NOT NULL UNIQUE)""",
    "llamado": """
        CREATE TABLE llamado(
          id_llamado NUMBER(10) PRIMARY KEY,
          codigo_licitacion VARCHAR2(100) NOT NULL)""",
    "contrato": """
        CREATE TABLE contrato(
          id_contrato NUMBER(10) PRIMARY KEY,
          id_llamado NUMBER(10) NOT NULL REFERENCES llamado(id_llamado),
          nro_lote NUMBER(10) NOT NULL,
          id_empresa NUMBER(10) NOT NULL REFERENCES empresa(id_empresa),
          fecha_contrato DATE,
          fecha_adenda DATE,
          UNIQUE(id_llamado, nro_lote, id_empresa))""",
    "item": """
        CREATE TABLE item(
          id_item NUMBER(10) PRIMARY KEY,
          categoria VARCHAR2(30) NOT NULL
            CHECK(categoria IN ('PARQUE','MATERIAL_DIDACTICO','MOBILIARIO','TIC')),
          descripcion VARCHAR2(500) NOT NULL,
          tipologia VARCHAR2(200),
          UNIQUE(categoria, descripcion))""",
    "entrega": """
        CREATE TABLE entrega(
          id_entrega NUMBER(10) PRIMARY KEY,
          id_establecimiento NUMBER(10) NOT NULL REFERENCES establecimiento(id_establecimiento),
          cod_institucion NUMBER(10) REFERENCES institucion(cod_institucion),
          id_contrato NUMBER(10) NOT NULL REFERENCES contrato(id_contrato),
          id_item NUMBER(10) NOT NULL REFERENCES item(id_item),
          cantidad NUMBER CHECK(cantidad IS NULL OR cantidad > 0),
          monto_adjudicado NUMBER CHECK(monto_adjudicado IS NULL OR monto_adjudicado >= 0),
          multa NUMBER DEFAULT 0 NOT NULL CHECK(multa >= 0),
          tiene_adenda NUMBER(1) CHECK(tiene_adenda IS NULL OR tiene_adenda IN (0,1)),
          fecha_acta DATE,
          fecha_acta_texto VARCHAR2(50),
          inscripta_patrimonio NUMBER(1) CHECK(inscripta_patrimonio IS NULL OR inscripta_patrimonio IN (0,1)),
          fecha_inscripcion DATE,
          tiene_seguro NUMBER(1) CHECK(tiene_seguro IS NULL OR tiene_seguro IN (0,1)),
          observacion VARCHAR2(1000),
          hoja_origen VARCHAR2(50) NOT NULL,
          fila_origen NUMBER(10) NOT NULL,
          UNIQUE(hoja_origen, fila_origen))""",
    "concepto_pago": """
        CREATE TABLE concepto_pago(
          id_concepto NUMBER(10) PRIMARY KEY,
          nombre VARCHAR2(200) NOT NULL UNIQUE)""",
    "pago": """
        CREATE TABLE pago(
          id_pago NUMBER(10) PRIMARY KEY,
          id_entrega NUMBER(10) NOT NULL REFERENCES entrega(id_entrega) ON DELETE CASCADE,
          id_concepto NUMBER(10) NOT NULL REFERENCES concepto_pago(id_concepto),
          monto NUMBER NOT NULL CHECK(monto >= 0),
          UNIQUE(id_entrega, id_concepto))""",
    "rechazo_migracion": """
        CREATE TABLE rechazo_migracion(
          hoja VARCHAR2(50) NOT NULL,
          fila NUMBER(10) NOT NULL,
          motivo VARCHAR2(100) NOT NULL,
          detalle VARCHAR2(1000))""",
    "log_migracion": """
        CREATE TABLE log_migracion(
          etapa VARCHAR2(100) NOT NULL,
          descripcion VARCHAR2(500) NOT NULL,
          filas NUMBER(10))""",
}

# Indices secundarios. Los dos unicos "parciales" de SQLite (WHERE ...) se expresan en Oracle
# con una expresion CASE: cuando la condicion no se cumple la clave queda NULL y no cuenta.
INDICES = [
    "CREATE UNIQUE INDEX ux_distrito_cod ON distrito(CASE WHEN cod_distrito IS NOT NULL THEN id_departamento END, cod_distrito)",
    "CREATE UNIQUE INDEX ux_estab_nombre_sin_codigo ON establecimiento(CASE WHEN codigo IS NULL THEN nombre END)",
    "CREATE INDEX ix_estab_distrito ON establecimiento(id_distrito)",
    "CREATE INDEX ix_inst_estab ON institucion(id_establecimiento)",
    "CREATE INDEX ix_contrato_empresa ON contrato(id_empresa)",
    "CREATE INDEX ix_contrato_llamado ON contrato(id_llamado)",
    "CREATE INDEX ix_entrega_estab ON entrega(id_establecimiento)",
    "CREATE INDEX ix_entrega_contrato ON entrega(id_contrato)",
    "CREATE INDEX ix_entrega_item ON entrega(id_item)",
    "CREATE INDEX ix_entrega_fecha ON entrega(fecha_acta)",
    "CREATE INDEX ix_pago_entrega ON pago(id_entrega)",
]

# Vistas en orden de dependencia. Diferencias con SQLite: GROUP_CONCAT -> LISTAGG y
# Oracle exige listar en GROUP BY todas las columnas no agregadas.
VISTAS = {
    "v_entregas_detalle": """
        CREATE VIEW v_entregas_detalle AS
        SELECT e.id_entrega, i.categoria, i.descripcion AS item, es.codigo AS cod_establecimiento,
               es.nombre AS establecimiento, d.nombre AS departamento, es.tipo_zona,
               l.codigo_licitacion, emp.nombre AS empresa, c.nro_lote, e.cantidad, e.monto_adjudicado,
               e.multa, e.fecha_acta
        FROM entrega e
        JOIN item i ON i.id_item = e.id_item
        JOIN establecimiento es ON es.id_establecimiento = e.id_establecimiento
        LEFT JOIN distrito di ON di.id_distrito = es.id_distrito
        LEFT JOIN departamento d ON d.id_departamento = di.id_departamento
        JOIN contrato c ON c.id_contrato = e.id_contrato
        JOIN llamado l ON l.id_llamado = c.id_llamado
        JOIN empresa emp ON emp.id_empresa = c.id_empresa""",
    "v_resumen_departamento": """
        CREATE VIEW v_resumen_departamento AS
        SELECT departamento, categoria, COUNT(DISTINCT cod_establecimiento) AS establecimientos,
               COUNT(*) AS entregas, SUM(monto_adjudicado) AS monto_total
        FROM v_entregas_detalle GROUP BY departamento, categoria""",
    "v_resumen_empresa": """
        CREATE VIEW v_resumen_empresa AS
        SELECT empresa, COUNT(DISTINCT categoria) AS categorias, COUNT(*) AS entregas,
               SUM(monto_adjudicado) AS monto_total
        FROM v_entregas_detalle GROUP BY empresa""",
    "v_cobertura_establecimiento": """
        CREATE VIEW v_cobertura_establecimiento AS
        SELECT es.codigo, es.nombre,
               COUNT(DISTINCT i.categoria) AS categorias_recibidas,
               LISTAGG(DISTINCT i.categoria, ',') WITHIN GROUP (ORDER BY i.categoria) AS categorias
        FROM establecimiento es
        LEFT JOIN entrega e ON e.id_establecimiento = es.id_establecimiento
        LEFT JOIN item i ON i.id_item = e.id_item
        GROUP BY es.id_establecimiento, es.codigo, es.nombre""",
    "v_conciliacion_pagos": """
        CREATE VIEW v_conciliacion_pagos AS
        SELECT e.id_entrega, e.hoja_origen, e.fila_origen, e.monto_adjudicado,
               NVL(SUM(p.monto), 0) AS pagado, e.multa,
               ROUND(e.monto_adjudicado - NVL(SUM(p.monto), 0) - e.multa, 2) AS diferencia
        FROM entrega e LEFT JOIN pago p ON p.id_entrega = e.id_entrega
        GROUP BY e.id_entrega, e.hoja_origen, e.fila_origen, e.monto_adjudicado, e.multa""",
}


def ejecutar_ignorando(cur, sentencia, codigos):
    """Ejecuta una sentencia y no falla si el error de Oracle esta en 'codigos' (ej. 942 = no existe)."""
    try:
        cur.execute(sentencia)
    except oracledb.DatabaseError as exc:
        err = exc.args[0]
        if getattr(err, "code", None) not in codigos:
            raise


def reconstruir_esquema(cur):
    """Borra los objetos anteriores (si existen) y crea tablas, indices y vistas."""
    for v in reversed(list(VISTAS)):
        ejecutar_ignorando(cur, f"DROP VIEW {v}", {942})
    for t in reversed(list(TABLAS)):
        ejecutar_ignorando(cur, f"DROP TABLE {t} CASCADE CONSTRAINTS PURGE", {942})
    for ddl in TABLAS.values():
        cur.execute(ddl)
    for ddl in INDICES:
        cur.execute(ddl)
    for ddl in VISTAS.values():
        cur.execute(ddl)


def convertir_fila(fila, es_fecha):
    """SQLite guarda las fechas como texto ISO (AAAA-MM-DD): se pasan como date a Oracle."""
    return tuple(date.fromisoformat(v) if (f and v) else v for v, f in zip(fila, es_fecha))


def copiar_tabla(origen, cur, tabla):
    cols = origen.execute(f"PRAGMA table_info({tabla})").fetchall()
    nombres = [c[1] for c in cols]
    es_fecha = [(c[2] or "").upper() == "DATE" for c in cols]
    insert = (f"INSERT INTO {tabla} ({', '.join(nombres)}) "
              f"VALUES ({', '.join(f':{i}' for i in range(1, len(nombres) + 1))})")
    total = 0
    consulta = origen.execute(f"SELECT {', '.join(nombres)} FROM {tabla} ORDER BY rowid")
    while True:
        lote = consulta.fetchmany(LOTE)
        if not lote:
            break
        cur.executemany(insert, [convertir_fila(f, es_fecha) for f in lote])
        total += len(lote)
    return total


def verificar(origen, cur):
    """Compara filas SQLite vs Oracle por tabla. Devuelve True si todo cuadra."""
    print(f"\n{'tabla':<22}{'SQLite':>9}{'Oracle':>9}  estado")
    todo_ok = True
    for t in TABLAS:
        a = origen.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        b = cur.fetchone()[0]
        ok = a == b
        todo_ok = todo_ok and ok
        print(f"{t:<22}{a:>9}{b:>9}  {'OK' if ok else 'REVISAR'}")
    for v in VISTAS:  # las vistas deben poder consultarse (valida la traduccion del SQL)
        cur.execute(f"SELECT COUNT(*) FROM {v}")
        print(f"vista {v:<30}{cur.fetchone()[0]:>6} filas")
    return todo_ok


def main():
    ap = argparse.ArgumentParser(description="Carga fenix_normalizada.db en Oracle.")
    ap.add_argument("--sqlite", default=SQLITE_POR_DEFECTO, help="ruta de la base SQLite de origen")
    ap.add_argument("--usuario", default=os.environ.get("FENIX_ORA_USER", "FENIX"))
    ap.add_argument("--dsn", default=os.environ.get("FENIX_ORA_DSN", "localhost:1521/FREEPDB1"),
                    help="host:puerto/servicio (por defecto localhost:1521/FREEPDB1)")
    args = ap.parse_args()

    if not os.path.exists(args.sqlite):
        sys.exit(f"No existe {args.sqlite}. Ejecute scripts/migracion_fenix.py o restaure la base incluida.")
    clave = os.environ.get("FENIX_ORA_PASSWORD") or getpass.getpass(f"Clave de {args.usuario}@{args.dsn}: ")

    origen = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    try:
        con = oracledb.connect(user=args.usuario, password=clave, dsn=args.dsn)
    except oracledb.DatabaseError as exc:
        sys.exit(f"No se pudo conectar a Oracle: {exc}\n"
                 "Revise que el listener este activo, el nombre del servicio (FREEPDB1) y el usuario "
                 "(scripts/oracle_crear_usuario.sql).")

    with con:
        cur = con.cursor()
        print("Reconstruyendo esquema ...")
        reconstruir_esquema(cur)
        for t in TABLAS:
            filas = copiar_tabla(origen, cur, t)
            print(f"  {t:<22}{filas:>8} filas")
        con.commit()
        ok = verificar(origen, cur)
    origen.close()

    print("\nCarga completa: las filas cuadran." if ok else "\nATENCION: hay tablas que no cuadran con el origen.")
    print("Conecte DBeaver al servicio FREEPDB1 con el usuario", args.usuario)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
