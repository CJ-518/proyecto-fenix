"""
Proyecto Fenix - Migracion ETL (Fase 3)
Extrae las cuatro planillas del Programa SNIP 388, las estandariza, las depura y las carga en una
base SQLite normalizada (3FN). Escribe salida/auditoria.json con la conciliacion origen-destino.
Uso: python scripts/migracion_fenix.py [carpeta_datos] [carpeta_salida]
     (por defecto: ./datos y ./salida, relativas a la raiz del repositorio)
Es idempotente: reconstruye la base en cada ejecucion. Si faltan las planillas, termina sin tocar la base.
"""
import collections
import glob
import json
import os
import re
import sqlite3
import sys
import warnings
from datetime import date, datetime

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "datos")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "salida")
DB = os.path.join(OUT, "fenix_normalizada.db")

DEPARTAMENTOS = {0: "CAPITAL", 1: "CONCEPCIÓN", 2: "SAN PEDRO", 3: "CORDILLERA", 4: "GUAIRÁ", 5: "CAAGUAZÚ",
                 6: "CAAZAPÁ", 7: "ITAPÚA", 8: "MISIONES", 9: "PARAGUARÍ", 10: "ALTO PARANÁ", 11: "CENTRAL",
                 12: "ÑEEMBUCÚ", 13: "AMAMBAY", 14: "CANINDEYÚ", 15: "PRESIDENTE HAYES", 16: "BOQUERÓN",
                 17: "ALTO PARAGUAY"}
DEP_POR_NOMBRE = {v: k for k, v in DEPARTAMENTOS.items()}
CONCEPTOS = ["ANTICIPO", "ANTICIPO 20%", "PAGO 1", "PAGO 2", "PAGO PARCIAL 30%", "CANCELACION 45%",
             "FONDO DE REPARO 5%"]
FUENTES = [("PARQUES", "PARQUES"), ("MATERIALES", "MATERIALES"), ("MOBILIARIO", "MOBILIARIO"), ("DOTAC", "TIC")]
CATEGORIA = {"PARQUES": "PARQUE", "MATERIALES": "MATERIAL_DIDACTICO", "MOBILIARIO": "MOBILIARIO", "TIC": "TIC"}

DDL = """
CREATE TABLE departamento(
  id_departamento INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE);
CREATE TABLE distrito(
  id_distrito INTEGER PRIMARY KEY AUTOINCREMENT,
  id_departamento INTEGER NOT NULL REFERENCES departamento(id_departamento),
  cod_distrito INTEGER,
  nombre TEXT);
CREATE UNIQUE INDEX ux_distrito_cod ON distrito(id_departamento, cod_distrito) WHERE cod_distrito IS NOT NULL;
CREATE TABLE establecimiento(
  id_establecimiento INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo TEXT UNIQUE CHECK(codigo IS NULL OR length(codigo)=7),
  nombre TEXT NOT NULL,
  id_distrito INTEGER REFERENCES distrito(id_distrito),
  latitud REAL CHECK(latitud IS NULL OR latitud BETWEEN -28 AND -19),
  longitud REAL CHECK(longitud IS NULL OR longitud BETWEEN -63 AND -54),
  tipo_zona TEXT CHECK(tipo_zona IS NULL OR tipo_zona IN ('Urbana','Rural')),
  sector TEXT CHECK(sector IS NULL OR sector IN ('Oficial','Priv. Subv.')),
  cai INTEGER CHECK(cai IS NULL OR cai IN (0,1)),
  indigena INTEGER CHECK(indigena IS NULL OR indigena IN (0,1)));
CREATE UNIQUE INDEX ux_estab_nombre_sin_codigo ON establecimiento(nombre) WHERE codigo IS NULL;
CREATE TABLE institucion(
  cod_institucion INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  id_establecimiento INTEGER NOT NULL REFERENCES establecimiento(id_establecimiento));
CREATE TABLE empresa(
  id_empresa INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL UNIQUE);
CREATE TABLE llamado(
  id_llamado INTEGER PRIMARY KEY,
  codigo_licitacion TEXT NOT NULL);
CREATE TABLE contrato(
  id_contrato INTEGER PRIMARY KEY AUTOINCREMENT,
  id_llamado INTEGER NOT NULL REFERENCES llamado(id_llamado),
  nro_lote INTEGER NOT NULL,
  id_empresa INTEGER NOT NULL REFERENCES empresa(id_empresa),
  fecha_contrato DATE,
  fecha_adenda DATE,
  UNIQUE(id_llamado, nro_lote, id_empresa));
CREATE TABLE item(
  id_item INTEGER PRIMARY KEY AUTOINCREMENT,
  categoria TEXT NOT NULL CHECK(categoria IN ('PARQUE','MATERIAL_DIDACTICO','MOBILIARIO','TIC')),
  descripcion TEXT NOT NULL,
  tipologia TEXT,
  UNIQUE(categoria, descripcion));
CREATE TABLE entrega(
  id_entrega INTEGER PRIMARY KEY AUTOINCREMENT,
  id_establecimiento INTEGER NOT NULL REFERENCES establecimiento(id_establecimiento),
  cod_institucion INTEGER REFERENCES institucion(cod_institucion),
  id_contrato INTEGER NOT NULL REFERENCES contrato(id_contrato),
  id_item INTEGER NOT NULL REFERENCES item(id_item),
  cantidad REAL CHECK(cantidad IS NULL OR cantidad > 0),
  monto_adjudicado REAL CHECK(monto_adjudicado IS NULL OR monto_adjudicado >= 0),
  multa REAL NOT NULL DEFAULT 0 CHECK(multa >= 0),
  tiene_adenda INTEGER CHECK(tiene_adenda IS NULL OR tiene_adenda IN (0,1)),
  fecha_acta DATE,
  fecha_acta_texto TEXT,
  inscripta_patrimonio INTEGER CHECK(inscripta_patrimonio IS NULL OR inscripta_patrimonio IN (0,1)),
  fecha_inscripcion DATE,
  tiene_seguro INTEGER CHECK(tiene_seguro IS NULL OR tiene_seguro IN (0,1)),
  observacion TEXT,
  hoja_origen TEXT NOT NULL,
  fila_origen INTEGER NOT NULL,
  UNIQUE(hoja_origen, fila_origen));
CREATE TABLE concepto_pago(
  id_concepto INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL UNIQUE);
CREATE TABLE pago(
  id_pago INTEGER PRIMARY KEY AUTOINCREMENT,
  id_entrega INTEGER NOT NULL REFERENCES entrega(id_entrega) ON DELETE CASCADE,
  id_concepto INTEGER NOT NULL REFERENCES concepto_pago(id_concepto),
  monto REAL NOT NULL CHECK(monto >= 0),
  UNIQUE(id_entrega, id_concepto));
CREATE TABLE rechazo_migracion(
  hoja TEXT NOT NULL, fila INTEGER NOT NULL, motivo TEXT NOT NULL, detalle TEXT);
CREATE TABLE log_migracion(
  etapa TEXT NOT NULL, descripcion TEXT NOT NULL, filas INTEGER);
CREATE INDEX ix_estab_distrito ON establecimiento(id_distrito);
CREATE INDEX ix_inst_estab ON institucion(id_establecimiento);
CREATE INDEX ix_contrato_empresa ON contrato(id_empresa);
CREATE INDEX ix_contrato_llamado ON contrato(id_llamado);
CREATE INDEX ix_entrega_estab ON entrega(id_establecimiento);
CREATE INDEX ix_entrega_contrato ON entrega(id_contrato);
CREATE INDEX ix_entrega_item ON entrega(id_item);
CREATE INDEX ix_entrega_fecha ON entrega(fecha_acta);
CREATE INDEX ix_pago_entrega ON pago(id_entrega);
"""
VISTAS = """
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
JOIN empresa emp ON emp.id_empresa = c.id_empresa;
CREATE VIEW v_resumen_departamento AS
SELECT departamento, categoria, COUNT(DISTINCT cod_establecimiento) AS establecimientos,
       COUNT(*) AS entregas, SUM(monto_adjudicado) AS monto_total
FROM v_entregas_detalle GROUP BY departamento, categoria;
CREATE VIEW v_resumen_empresa AS
SELECT empresa, COUNT(DISTINCT categoria) AS categorias, COUNT(*) AS entregas, SUM(monto_adjudicado) AS monto_total
FROM v_entregas_detalle GROUP BY empresa;
CREATE VIEW v_cobertura_establecimiento AS
SELECT es.codigo, es.nombre,
       COUNT(DISTINCT i.categoria) AS categorias_recibidas,
       GROUP_CONCAT(DISTINCT i.categoria) AS categorias
FROM establecimiento es
LEFT JOIN entrega e ON e.id_establecimiento = es.id_establecimiento
LEFT JOIN item i ON i.id_item = e.id_item
GROUP BY es.id_establecimiento;
CREATE VIEW v_conciliacion_pagos AS
SELECT e.id_entrega, e.hoja_origen, e.fila_origen, e.monto_adjudicado,
       COALESCE(SUM(p.monto),0) AS pagado, e.multa,
       ROUND(e.monto_adjudicado - COALESCE(SUM(p.monto),0) - e.multa, 2) AS diferencia
FROM entrega e LEFT JOIN pago p ON p.id_entrega = e.id_entrega GROUP BY e.id_entrega;
"""


# ---------------------------------------------------------------- utilidades de limpieza
def vacio(v):
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and v.strip() in ("", "-", "S/D"))


def texto(v):
    return None if vacio(v) else re.sub(r"\s+", " ", str(v).replace("Nº", "N°")).strip()


def nombre_propio(v):
    """Nombres de instituciones: solo se ordenan los espacios; se respeta la grafia de la fuente."""
    return None if vacio(v) else re.sub(r"\s+", " ", str(v)).strip()


def entero(v):
    try:
        return None if vacio(v) else int(float(v))
    except (TypeError, ValueError):
        return None


def numero(v):
    try:
        return None if vacio(v) else float(v)
    except (TypeError, ValueError):
        return None


def codigo7(v):
    n = entero(v)
    return None if n is None else "%07d" % n


def fecha(v):
    """Fecha real o texto dd/mm/aaaa -> 'aaaa-mm-dd'; cualquier otra cosa -> None."""
    if isinstance(v, (datetime, pd.Timestamp)):
        return None if pd.isna(v) else v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", v)
        if m:
            try:
                return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
            except ValueError:
                return None
    return None


def coordenada(v, lo, hi):
    """Grados-minutos-segundos ('23º25'9.954"S') -> decimal con 5 decimales; None si es invalida."""
    if vacio(v):
        return None
    m = re.match(r"\s*(\d+)\D+?(\d+)\D+?([\d.]+)\D*([NSEWO])", str(v).strip(), re.I)
    if not m:
        return None
    d = int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600
    if m[4].upper() in "SWO":
        d = -d
    d = round(d, 5)
    return d if lo <= d <= hi else None


def si_no(v):
    if vacio(v):
        return None
    if isinstance(v, str):
        return 1 if v.strip().upper().startswith(("SI", "SÍ")) else 0
    return 1 if float(v) else 0


def zona(v):
    t = texto(v)
    if t is None:
        return None
    return {"1": "Urbana", "6": "Rural", "URBANA": "Urbana", "RURAL": "Rural"}.get(t.upper(), None)


def sector(v):
    t = texto(v)
    if t is None:
        return None
    return {"1": "Oficial", "2": "Priv. Subv.", "OFICIAL": "Oficial", "PRIV. SUBV.": "Priv. Subv."}.get(t.upper())


def moda(valores):
    """Valor mas frecuente (en empate, el primero que aparecio); None si no hay valores."""
    vs = [v for v in valores if v is not None]
    return collections.Counter(vs).most_common(1)[0][0] if vs else None


def clave_empresa(nombre):
    return nombre.casefold()


# ---------------------------------------------------------------- extraccion y estandarizacion
def buscar(prefijo):
    for patron in ("Encabezado_%s*.xlsx", "Encabezado_%s*.xls"):
        hallados = sorted(glob.glob(os.path.join(DATA, patron % prefijo)))
        if hallados:
            return hallados[0]
    return None


def leer_planillas():
    frames, faltan = {}, []
    for prefijo, nombre in FUENTES:
        ruta = buscar(prefijo)
        if not ruta:
            faltan.append(prefijo)
            continue
        frames[nombre] = pd.read_excel(ruta, sheet_name=0)
    if faltan:
        sys.exit("Faltan planillas en %s: %s (ver datos/LEEME.md). No se modifico la base." % (DATA, ", ".join(faltan)))
    return frames


def col(df, prefijo):
    """Primera columna cuyo nombre empieza con el prefijo (ignora saltos de linea y mayusculas)."""
    for c in df.columns:
        if re.sub(r"\s+", " ", str(c)).lower().startswith(prefijo.lower()):
            return c
    return None


def estandarizar(nombre, df):
    """Devuelve (filas estandarizadas, rechazos). Cada fila es un dict con los campos del modelo."""
    filas, rechazos, vistos = [], [], set()
    ncols = df.shape[1]
    get = lambda r, p: r[col(df, p)] if col(df, p) is not None else None
    for i, (_, r) in enumerate(df.iterrows()):
        n = i + 2  # numero de fila en Excel (la 1 es el encabezado)
        if r.isna().all():
            rechazos.append((nombre, n, "FILA_VACIA", "Fila completamente vacia"))
            continue
        clave = tuple(str(v) for v in r.tolist())
        if clave in vistos:
            rechazos.append((nombre, n, "DUPLICADO_EXACTO",
                             "Fila identica en las %d columnas a una anterior" % ncols))
            continue
        vistos.add(clave)
        f = dict(src=nombre, fila=n, cod=codigo7(get(r, "CodigoEstablecimiento")),
                 cod_inst=entero(get(r, "CodInstitucion")), nombre_inst=nombre_propio(get(r, "NombreInstitución")),
                 lat=coordenada(get(r, "latitud"), -28, -19), lon=coordenada(get(r, "longitud"), -63, -54),
                 obs=[], pagos=[], multa=0.0, tiene_adenda=None, inscripta=None, fecha_insc=None,
                 seguro=None, fecha_acta=None, fecha_acta_texto=None, fecha_adenda=None)
        # ---- ubicacion
        if nombre == "PARQUES":
            f["nombre_estab"] = nombre_propio(get(r, "nombre"))
            f["dep"] = DEP_POR_NOMBRE.get((texto(get(r, "Departamento")) or "").upper())
            f["dist"] = int(f["cod"][2:4]) if f["cod"] else None   # el distrito va en los digitos 3-4 del codigo
            if f["dep"] == 0:                                      # Capital: un unico distrito (Asuncion), codigo 0
                f["dist"] = 0
            f["dist_nombre"] = texto(get(r, "Distrito"))
        else:
            f["nombre_estab"] = None
            f["dep"] = entero(get(r, "Departamento"))
            f["dist"] = entero(get(r, "Distrito"))
            f["dist_nombre"] = None
        f["zona"] = zona(get(r, "TipoZona"))
        f["sector"] = None if nombre == "PARQUES" else sector(get(r, "Sector"))
        f["cai"] = si_no(get(r, "CAI"))
        f["indigena"] = si_no(get(r, "indígena"))
        if nombre == "PARQUES" and isinstance(get(r, "CAI"), str) and get(r, "CAI").strip().upper() != "NO":
            f["obs"].append("CAI: " + get(r, "CAI").strip())
        # ---- contrato / llamado
        f["licit"] = texto(get(r, "licitacion1"))
        f["id_llamado"] = entero(get(r, "ID1"))
        f["empresa"] = texto(get(r, "empresa1"))
        f["lote"] = entero(get(r, "nro_lote1"))
        fc = get(r, "fecha_contrato1")
        if isinstance(fc, str) and fc.strip().lower().startswith("adenda"):   # 'Adenda dd/mm/aaaa - Contrato dd/mm/aaaa'
            m = re.match(r"adenda\s+(\S+)\s*-\s*contrato\s+(\S+)", fc.strip(), re.I)
            f["fecha_adenda"], f["fecha_contrato"] = fecha(m[1]), fecha(m[2])
        else:
            f["fecha_contrato"] = fecha(fc)
        f["monto"] = numero(get(r, "monto_adjudicado1"))
        # ---- item, cantidad, adenda, patrimonio, pagos segun la fuente
        if nombre == "PARQUES":
            tip = texto(get(r, "Tipología"))
            f["item"] = ("Parque tipologia %s" % tip, tip) if tip else None
            f["cantidad"] = numero(get(r, "Cantidad"))
            f["tiene_adenda"] = si_no(get(r, "adenda_contrato1"))
            f["inscripta"] = si_no(get(r, "inscripta_patrimonio"))
            f["fecha_insc"] = fecha(get(r, "fecha_insc_patrimonio"))
            f["fecha_acta"] = fecha(get(r, "acta_entrega_fecha"))
            f["pagos"] = [("ANTICIPO 20%", numero(get(r, "monto_anticipo1"))),
                          ("PAGO PARCIAL 30%", numero(get(r, "Pago Parcial"))),
                          ("CANCELACION 45%", numero(get(r, "Cancelación"))),
                          ("FONDO DE REPARO 5%", numero(get(r, "Fondo de Reparo")))]
        else:
            if nombre == "MATERIALES":
                desc = texto(get(r, "Materiales didácticos entregado"))
                f["item"] = (desc, texto(get(r, "Tipología"))) if desc else None
                f["cantidad"] = numero(get(r, "Cantidad1"))
                f["tiene_adenda"] = si_no(get(r, "adenda_contrato1"))
                extra = texto(get(r, "Unnamed"))
                if extra:
                    f["obs"].append(extra)
                acta = get(r, "acta_entrega_fecha")
            elif nombre == "MOBILIARIO":
                desc = texto(get(r, "Mobiliario"))
                f["item"] = (desc, None) if desc else None
                f["cantidad"] = numero(get(r, "Cantidad"))
                f["tiene_adenda"] = si_no(get(r, "adenda_contrato1"))
                f["multa"] = numero(get(r, "Multa")) or 0.0
                f["inscripta"] = si_no(get(r, "Inscripta_patrimonio"))
                f["fecha_insc"] = fecha(get(r, "Fecha_insc_patrimonio"))
                acta = get(r, "Acta_Entrega_fecha")
            else:  # TIC
                desc = texto(get(r, "Dispositivo"))
                f["item"] = (desc, None) if desc else None
                f["cantidad"] = numero(get(r, "Cantidad"))
                f["tiene_adenda"] = si_no(get(r, "adenda_contrato1"))
                f["seguro"] = si_no(get(r, "Tiene seguro"))
                acta = get(r, "Acta_Entrega_fecha")
            f["fecha_acta"] = fecha(acta)
            if f["fecha_acta"] is None and isinstance(acta, str) and acta.strip():
                if acta.strip().lower().startswith("memo"):
                    f["obs"].append(acta.strip())            # 'Memo Nº 560 24/05/2022' va a observacion
                else:
                    f["fecha_acta_texto"] = acta.strip()     # acta parcial tipo 'XX/11/2021' se conserva como texto
            ant = col(df, "monto_anticipo")
            f["pagos"] = [("ANTICIPO", numero(r[ant])), ("PAGO 1", numero(get(r, "Pago1"))),
                          ("PAGO 2", numero(get(r, "Pago2")))]
        if f["licit"] is None or f["item"] is None:
            f["sin_entrega"] = True
            rechazos.append((nombre, n, "SIN_ENTREGA", "Establecimiento listado sin contrato/item asociado"))
        else:
            f["sin_entrega"] = False
        filas.append(f)
    return filas, rechazos


# ---------------------------------------------------------------- carga
def construir(frames):
    aud = {"filas_origen": {k: int(v.shape[0]) for k, v in frames.items()},
           "columnas_origen": {k: int(v.shape[1]) for k, v in frames.items()}}
    todas, rechazos = [], []
    for _, nombre in FUENTES:
        filas, rech = estandarizar(nombre, frames[nombre])
        todas += filas
        rechazos += rech
    aud["mob_duplicados_monto"] = sum(numero(frames["MOBILIARIO"].iloc[r[1] - 2][col(frames["MOBILIARIO"], "monto_adjudicado1")]) or 0
                                      for r in rechazos if r[0] == "MOBILIARIO" and r[2] == "DUPLICADO_EXACTO")
    aud["monto_origen"] = {k: round(sum(f["monto"] or 0 for f in todas if f["src"] == k), 2) for k in frames}
    aud["filas_estandarizadas"] = dict(collections.Counter(f["src"] for f in todas))
    aud["mapa_departamentos"] = {str(k): v for k, v in DEPARTAMENTOS.items()}

    # ---- establecimientos: una fila por codigo (o por nombre si no tiene codigo); atributos por moda
    estabs = collections.OrderedDict()
    for f in todas:
        k = ("C", f["cod"]) if f["cod"] else ("N", f["nombre_estab"] or f["nombre_inst"])
        estabs.setdefault(k, []).append(f)
    conflictos = collections.Counter()
    estab_reg, estab_id = [], {}
    for i, (k, fs) in enumerate(estabs.items(), 1):
        for campo, clave in (("lat", "lat"), ("lon", "lon"), ("zona", "zona"), ("cai", "cai"), ("indigena", "indigena")):
            if len({f[clave] for f in fs if f[clave] is not None}) > 1:
                conflictos[campo] += 1
        nombre = next((f["nombre_estab"] for f in fs if f["nombre_estab"]), None) or moda(f["nombre_inst"] for f in fs)
        # departamento/distrito: se prefieren los codigos de las planillas numericas; parques (que solo trae nombres
        # y cuyo codigo no siempre refleja el distrito) se usa solo si el establecimiento no esta en otra fuente
        par = lambda fl: [(f["dep"], f["dist"]) for f in fl if f["dep"] is not None and f["dist"] is not None]
        dd = moda(par([f for f in fs if f["src"] != "PARQUES"])) or moda(par(fs))
        estab_reg.append(dict(id=i, cod=k[1] if k[0] == "C" else None, nombre=nombre, dd=dd,
                              lat=moda(f["lat"] for f in fs), lon=moda(f["lon"] for f in fs),
                              zona=moda(f["zona"] for f in fs), sector=moda(f["sector"] for f in fs),
                              cai=moda(f["cai"] for f in fs) or 0, ind=moda(f["indigena"] for f in fs) or 0))
        estab_id[k] = i
        for f in fs:
            f["id_estab"] = i
    aud["conflictos_atributos_establecimiento"] = {c: conflictos[c] for c in ("lat", "lon", "zona", "cai", "indigena")}

    # ---- distritos (departamento + codigo; el nombre solo viene en la planilla de parques)
    nombres_dist = {}
    for e in estab_reg:
        nm = next((f["dist_nombre"] for f in estabs[("C", e["cod"]) if e["cod"] else ("N", e["nombre"])] if f["dist_nombre"]), None)
        if nm and e["dd"]:
            nombres_dist.setdefault(e["dd"], nm)
    pares = list(dict.fromkeys(e["dd"] for e in estab_reg if e["dd"]))   # orden de primera aparicion
    dist_id = {p: i for i, p in enumerate(pares, 1)}

    # ---- instituciones, empresas, llamados, contratos, items
    instit, variantes_inst = collections.OrderedDict(), collections.defaultdict(list)
    for f in todas:
        if f["cod_inst"] is not None:
            variantes_inst[f["cod_inst"]].append(f["nombre_inst"])
            instit.setdefault(f["cod_inst"], [None, f["id_estab"]])
    for cod_i, v in instit.items():
        v[0] = moda(variantes_inst[cod_i])      # la grafia mas frecuente del nombre
    entregas = [f for f in todas if not f["sin_entrega"]]
    variantes = collections.Counter(f["empresa"] for f in entregas if f["empresa"])
    aud["empresas_variantes"] = len(variantes)
    por_clave = collections.OrderedDict()
    for nombre_e, n in variantes.items():
        por_clave.setdefault(clave_empresa(nombre_e), collections.Counter())[nombre_e] += n
    empresas = {k: c.most_common(1)[0][0] for k, c in por_clave.items()}
    emp_id = {k: i for i, k in enumerate(empresas, 1)}
    aud["empresas_unicas"] = len(empresas)
    llamados = {}
    for f in entregas:
        llamados.setdefault(f["id_llamado"], f["licit"])
    aud["variantes_codigo_licitacion"] = len(set(llamados.values()))
    contratos = collections.defaultdict(list)
    for f in entregas:
        contratos[(f["id_llamado"], f["lote"], clave_empresa(f["empresa"]))].append(f)
    contrato_id = {k: i for i, k in enumerate(sorted(contratos, key=lambda k: (k[0], k[1], empresas[k[2]])), 1)}
    items = sorted({(CATEGORIA[f["src"]], f["item"][0], f["item"][1]) for f in entregas})
    item_id = {(c, d): i for i, (c, d, t) in enumerate(items, 1)}

    if os.path.exists(DB):
        os.remove(DB)
    os.makedirs(OUT, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(DDL)
    con.executemany("INSERT INTO departamento VALUES (?,?)", DEPARTAMENTOS.items())
    con.executemany("INSERT INTO distrito VALUES (?,?,?,?)",
                    [(dist_id[p], p[0], p[1], nombres_dist.get(p)) for p in pares])
    con.executemany("INSERT INTO establecimiento VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(e["id"], e["cod"], e["nombre"], dist_id.get(e["dd"]), e["lat"], e["lon"], e["zona"],
                      e["sector"], e["cai"], e["ind"]) for e in estab_reg])
    con.executemany("INSERT INTO institucion VALUES (?,?,?)", [(k, v[0], v[1]) for k, v in instit.items()])
    con.executemany("INSERT INTO empresa VALUES (?,?)", [(emp_id[k], v) for k, v in empresas.items()])
    con.executemany("INSERT INTO llamado VALUES (?,?)", sorted(llamados.items()))
    filas_c = []
    for k, fs in contratos.items():
        filas_c.append((contrato_id[k], k[0], k[1], emp_id[k[2]], moda(f["fecha_contrato"] for f in fs),
                        moda(f["fecha_adenda"] for f in fs)))
    con.executemany("INSERT INTO contrato VALUES (?,?,?,?,?,?)", sorted(filas_c))
    con.executemany("INSERT INTO item VALUES (?,?,?,?)", [(item_id[(c, d)], c, d, t) for c, d, t in items])
    con.executemany("INSERT INTO concepto_pago VALUES (?,?)", list(enumerate(CONCEPTOS, 1)))
    cid = {c: i for i, c in enumerate(CONCEPTOS, 1)}
    n_pagos = 0
    for i, f in enumerate(entregas, 1):
        k = (f["id_llamado"], f["lote"], clave_empresa(f["empresa"]))
        con.execute("INSERT INTO entrega VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (i, f["id_estab"], f["cod_inst"], contrato_id[k], item_id[(CATEGORIA[f["src"]], f["item"][0])],
                     f["cantidad"], f["monto"], f["multa"], f["tiene_adenda"], f["fecha_acta"],
                     f["fecha_acta_texto"], f["inscripta"], f["fecha_insc"], f["seguro"],
                     " | ".join(f["obs"]) or None, f["src"], f["fila"]))
        for concepto, monto in f["pagos"]:
            if monto and monto > 0:
                con.execute("INSERT INTO pago(id_entrega, id_concepto, monto) VALUES (?,?,?)", (i, cid[concepto], monto))
                n_pagos += 1
    con.executemany("INSERT INTO rechazo_migracion VALUES (?,?,?,?)", rechazos)
    con.executescript(VISTAS)
    return con, aud, rechazos, todas


def verificar(con, aud, rechazos, todas):
    q = lambda s: con.execute(s).fetchall()
    cnt = lambda t: q("SELECT COUNT(*) FROM %s" % t)[0][0]
    aud["instituciones"] = cnt("institucion")
    aud["destino"] = {t: cnt(t) for t in ("departamento", "distrito", "establecimiento", "institucion", "empresa",
                                           "llamado", "contrato", "item", "entrega", "concepto_pago", "pago",
                                           "rechazo_migracion")}
    aud["monto_destino"] = {c: round(m, 2) for c, m in q(
        "SELECT hoja_origen, SUM(monto_adjudicado) FROM entrega GROUP BY hoja_origen")}
    por_motivo = collections.Counter("%s|%s" % (r[0], r[2]) for r in rechazos)
    aud["rechazos_por_motivo"] = dict(sorted(por_motivo.items()))
    aud["fk_violaciones"] = len(q("PRAGMA foreign_key_check"))
    aud["integrity"] = q("PRAGMA integrity_check")[0][0]
    aud["coord_nulas_estab"] = q("SELECT COUNT(*) FROM establecimiento WHERE latitud IS NULL OR longitud IS NULL")[0][0]
    aud["fechas_acta_parciales"] = q("SELECT COUNT(*) FROM entrega WHERE fecha_acta_texto IS NOT NULL")[0][0]
    concil = {}
    for hoja, n, dif, mx in q("SELECT hoja_origen, COUNT(*), SUM(ABS(diferencia) > 0.5), MAX(ABS(diferencia)) "
                              "FROM v_conciliacion_pagos GROUP BY hoja_origen"):
        concil[hoja] = [n, int(dif or 0), round(mx or 0, 2) if dif else 0]
    aud["conciliacion"] = concil
    aud["cobertura"] = {str(k): v for k, v in q(
        "SELECT categorias_recibidas, COUNT(*) FROM v_cobertura_establecimiento GROUP BY 1 ORDER BY 1")}
    aud["top_empresas"] = [list(r) for r in q(
        "SELECT empresa, entregas, ROUND(monto_total) FROM v_resumen_empresa ORDER BY monto_total DESC LIMIT 5")]
    log = [("DEPARTAMENTO", "Departamentos unificados (codigo numerico + nombre)", aud["destino"]["departamento"]),
           ("DISTRITO", "Distritos unicos (dep+codigo)", aud["destino"]["distrito"]),
           ("ESTABLECIMIENTO", "Establecimientos consolidados de las 4 fuentes", aud["destino"]["establecimiento"]),
           ("CONTRATO", "Contratos (llamado+lote+empresa)", aud["destino"]["contrato"]),
           ("ENTREGA", "Lineas de entrega migradas", aud["destino"]["entrega"]),
           ("PAGO", "Pagos (filas) generados desde columnas repetidas", aud["destino"]["pago"])]
    con.executemany("INSERT INTO log_migracion VALUES (?,?,?)", log)
    con.commit()


def main():
    frames = leer_planillas()
    con, aud, rechazos, todas = construir(frames)
    verificar(con, aud, rechazos, todas)
    con.close()
    with open(os.path.join(OUT, "auditoria.json"), "w", encoding="utf-8") as fh:
        json.dump(aud, fh, indent=1, ensure_ascii=False)
    d = aud["destino"]
    print("Migracion completa -> %s" % DB)
    print("  Filas de origen: %d | entregas cargadas: %d | rechazos: %d" % (
        sum(aud["filas_origen"].values()), d["entrega"], d["rechazo_migracion"]))
    for k, v in aud["rechazos_por_motivo"].items():
        print("    rechazo %-28s %d" % (k, v))
    for k in aud["monto_origen"]:
        o, de = round(aud["monto_origen"][k], 2), aud["monto_destino"].get(k)
        print("  Monto %-11s origen %18s | destino %18s | %s" % (k, "{:,.0f}".format(o), "{:,.0f}".format(de or 0),
                                                              "OK" if abs(o - (de or 0)) < 1 else "DIFERENCIA"))
    print("  Violaciones de clave foranea: %d | integrity_check: %s" % (aud["fk_violaciones"], aud["integrity"]))


if __name__ == "__main__":
    main()
