#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proyecto Fenix - Script de migracion (Fase 3)
Origen : 4 planillas legacy (parques, materiales didacticos, mobiliario, dotacion TIC)
Destino: base relacional SQLite en 3FN (fenix_normalizada.db)

Idempotente: borra y reconstruye la base en cada ejecucion.
Uso: python3 scripts/migracion_fenix.py [carpeta_datos] [carpeta_salida]
     (por defecto: ./datos y ./salida, relativas a la raiz del repositorio)
"""
import sys, os, re, json, glob, sqlite3, warnings, unicodedata
from collections import Counter
from datetime import datetime, date
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "datos")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "salida")
os.makedirs(OUT, exist_ok=True)
DB = os.path.join(OUT, "fenix_normalizada.db")
AUD = {}  # metricas de auditoria para el informe

# ------------------------------------------------------------------ utilidades
def pad7(x):
    try:
        return str(int(float(x))).zfill(7)
    except (TypeError, ValueError):
        return None

def clean(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip()
    return s or None

def key(s):
    s = clean(s) or ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)

DMS = re.compile(r"^\s*(\d+)\s*[º°]\s*(\d+)\s*'\s*([\d.]+)\s*(?:\"|'')?\s*([NSEWO])\s*$")
def dms(s):
    s = clean(s)
    if not s or s.upper() == "S/D":
        return None
    m = DMS.match(s)
    if not m:
        return None
    g, mi, se, h = m.groups()
    v = int(g) + int(mi) / 60 + float(se) / 3600
    return -v if h in "SWO" else v

def flag(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    t = str(x).strip().lower().replace("í", "i")
    if t in ("1", "1.0", "si", "true"):
        return 1
    if t in ("0", "0.0", "no", "false"):
        return 0
    if t.startswith("si ("):
        return 1
    return None

D8 = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
def to_date(x):
    """devuelve (date|None, texto_original_si_no_parseable|None, fecha_adenda|None)"""
    if x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NaT:
        return None, None, None
    if isinstance(x, (datetime, pd.Timestamp)):
        return x.date(), None, None
    s = clean(x)
    if not s or s == "-":
        return None, None, None
    if s.lower().startswith("adenda"):
        f = D8.findall(s)
        ad = date(int(f[0][2]), int(f[0][1]), int(f[0][0])) if f else None
        co = date(int(f[1][2]), int(f[1][1]), int(f[1][0])) if len(f) > 1 else None
        return co, None, ad
    m = D8.fullmatch(s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1])), None, None
        except ValueError:
            return None, s, None
    return None, s, None  # 'XX/11/2021', 'Memo ...'

def lic(s):
    s = clean(s)
    if not s:
        return None
    s = re.sub(r"N\s*[º°o]\.?\s*", "N° ", s)
    return re.sub(r"\s+", " ", s).strip()

def num(x):
    try:
        v = float(x)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None

def mode(vals):
    vals = [v for v in vals if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else None

# ------------------------------------------------------------------ extraccion
def read_all():
    if not glob.glob(os.path.join(DATA, "Encabezado_*.xls*")):
        sys.exit(f"No se encontraron las planillas Encabezado_*.xls* en '{DATA}'.\n"
                 "Copielas en la carpeta datos/ (ver datos/LEEME.md) o pase la ruta como primer argumento.")
    p = pd.read_excel(os.path.join(DATA, "Encabezado_PARQUES_EXPANSION_UV.xlsx"))
    p.columns = [c.split("\n")[0] for c in p.columns]
    m = pd.read_excel(glob.glob(os.path.join(DATA, "Encabezado_MATERIALES*"))[0], sheet_name=0)
    b = pd.read_excel(glob.glob(os.path.join(DATA, "Encabezado_MOBILIARIO*"))[0])
    t = pd.read_excel(glob.glob(os.path.join(DATA, "Encabezado_DOTAC*"))[0])
    return p, m, b, t

def std_rows(p, m, b, t, rechazos):
    rows = []
    def add(**k):
        rows.append(k)
    # --- PARQUES
    for i, r in p.iterrows():
        pg = {"ANTICIPO 20%": num(r["monto_anticipo1"]), "PAGO PARCIAL 30%": num(r["Pago Parcial"]),
              "CANCELACION 45%": num(r["Cancelación"]), "FONDO DE REPARO 5%": num(r["Fondo de Reparo"])}
        add(hoja="PARQUES", fila=i + 2, cod=pad7(r["CodigoEstablecimiento"]), nombre_estab=clean(r["nombre"]),
            inst_cod=None, inst_nombre=None, dep_cod=None, dep_nom=clean(r["Departamento"]),
            dis_cod=None, dis_nom=clean(r["Distrito"]), lat=dms(r["latitud"]), lon=dms(r["longitud"]),
            zona=clean(r["TipoZona"]), sector=None, cai=flag(r["CAI"]), indigena=flag(r["indígena"]),
            licitacion=lic(r["licitacion1"]), id1=num(r["ID1"]), empresa=clean(r["empresa1"]),
            fecha_contrato=r["fecha_contrato1"], lote=num(r["nro_lote1"]), monto=num(r["monto_adjudicado1"]),
            adenda=flag(r["adenda_contrato1"]), item="Parque tipologia " + clean(r["Tipología"]),
            tipologia=clean(r["Tipología"]), cat="PARQUE", cantidad=num(r["Cantidad"]),
            acta=r["acta_entrega_fecha"], inscripta=flag(r["inscripta_patrimonio"]),
            fecha_insc=r["fecha_insc_patrimonio"], seguro=None, multa=0.0,
            obs="CAI: " + clean(r["CAI"]) if str(r["CAI"]).startswith("SI") else None, pagos=pg)
    # --- MATERIALES
    for i, r in m.iterrows():
        pg = {"ANTICIPO": num(r["monto_anticipo1"]), "PAGO 1": num(r["Pago1"])}
        add(hoja="MATERIALES", fila=i + 2, cod=pad7(r["CodigoEstablecimiento"]), nombre_estab=None,
            inst_cod=num(r["CodInstitucion"]), inst_nombre=clean(r["NombreInstitución"]),
            dep_cod=num(r["Departamento"]), dep_nom=None, dis_cod=num(r["Distrito"]), dis_nom=None,
            lat=dms(r["latitud"]), lon=dms(r["longitud"]), zona=clean(r["TipoZona"]), sector=clean(r["Sector"]),
            cai=flag(r["CAI"]), indigena=flag(r["indígena"]), licitacion=lic(r["licitacion1"]),
            id1=num(r["ID1"]), empresa=clean(r["empresa1"]), fecha_contrato=r["fecha_contrato1"],
            lote=num(r["nro_lote1"]), monto=num(r["monto_adjudicado1"]), adenda=flag(r["adenda_contrato1"]),
            item=clean(r["Materiales didácticos entregado"]), tipologia=clean(r["Tipología"]),
            cat="MATERIAL_DIDACTICO", cantidad=num(r["Cantidad1"]), acta=r["acta_entrega_fecha"],
            inscripta=None, fecha_insc=None, seguro=None, multa=0.0, obs=clean(r["Unnamed: 26"]), pagos=pg)
    # --- MOBILIARIO (fila 0 vacia + duplicados exactos)
    bb = b.copy()
    blank = bb.index[bb.isna().all(axis=1)]
    for i in blank:
        rechazos.append(("MOBILIARIO", i + 2, "FILA_VACIA", "Fila completamente vacia"))
    dup = bb.index[bb.duplicated(keep="first") & ~bb.isna().all(axis=1)]
    for i in dup:
        rechazos.append(("MOBILIARIO", i + 2, "DUPLICADO_EXACTO", "Fila identica en las 29 columnas a una anterior"))
    b = bb.drop(index=list(blank) + list(dup))
    AUD["mob_duplicados_monto"] = float(bb.loc[dup, "monto_adjudicado1"].sum())
    for i, r in b.iterrows():
        pg = {"ANTICIPO": num(r["monto_anticipo1"]), "PAGO 1": num(r["Pago1"]), "PAGO 2": num(r["Pago2"])}
        add(hoja="MOBILIARIO", fila=i + 2, cod=pad7(r["CodigoEstablecimiento"]), nombre_estab=None,
            inst_cod=num(r["CodInstitucion"]), inst_nombre=clean(r["NombreInstitución"]),
            dep_cod=num(r["Departamento"]), dep_nom=None, dis_cod=num(r["Distrito"]), dis_nom=None,
            lat=dms(r["latitud"]), lon=dms(r["longitud"]), zona=clean(r["TipoZona"]), sector=clean(r["Sector"]),
            cai=flag(r["CAI"]), indigena=flag(r["indígena"]), licitacion=lic(r["licitacion1"]),
            id1=num(r["ID1"]), empresa=clean(r["empresa1"]), fecha_contrato=r["fecha_contrato1"],
            lote=num(r["nro_lote1"]), monto=num(r["monto_adjudicado1"]), adenda=flag(r["adenda_contrato1"]),
            item=clean(r["Mobiliario"]), tipologia=None, cat="MOBILIARIO", cantidad=num(r["Cantidad"]),
            acta=r["Acta_Entrega_fecha"], inscripta=flag(r["Inscripta_patrimonio"]),
            fecha_insc=r["Fecha_insc_patrimonio"], seguro=None, multa=num(r["Multa"]) or 0.0, obs=None, pagos=pg)
    # --- TIC (fila 0 vacia; Sector/TipoZona codificados)
    tb = t.copy()
    for i in tb.index[tb.isna().all(axis=1)]:
        rechazos.append(("TIC", i + 2, "FILA_VACIA", "Fila completamente vacia"))
    tb = tb.dropna(how="all")
    SEC = {"1": "Oficial", "2": "Priv. Subv."}
    ZON = {"1": "Urbana", "6": "Rural"}
    for i, r in tb.iterrows():
        pg = {"ANTICIPO": num(r["monto_anticipo"]), "PAGO 1": num(r["Pago1"]), "PAGO 2": num(r["Pago2"])}
        sec = clean(r["Sector"]); zon = clean(r["TipoZona"])
        sec = SEC.get(str(sec).replace(".0", ""), None) if sec else None
        zon = ZON.get(str(zon).replace(".0", ""), None) if zon else None
        add(hoja="TIC", fila=i + 2, cod=pad7(r["CodigoEstablecimiento"]), nombre_estab=None,
            inst_cod=num(r["CodInstitucion"]), inst_nombre=clean(r["NombreInstitución"]),
            dep_cod=num(r["Departamento"]), dep_nom=None, dis_cod=num(r["Distrito"]), dis_nom=None,
            lat=dms(r["latitud"]), lon=dms(r["longitud"]), zona=zon, sector=sec,
            cai=flag(r["CAI"]), indigena=flag(r["indígena"]), licitacion=lic(r["licitacion1"]),
            id1=num(r["ID1"]), empresa=clean(r["empresa1"]), fecha_contrato=r["fecha_contrato1"],
            lote=num(r["nro_lote1"]), monto=num(r["monto_adjudicado1"]), adenda=flag(r["adenda_contrato1"]),
            item=clean(r["Dispositivo"]), tipologia=None, cat="TIC", cantidad=num(r["Cantidad"]),
            acta=r["Acta_Entrega_fecha"], inscripta=None, fecha_insc=None,
            seguro=flag(r["Tiene seguro"]), multa=0.0, obs=None, pagos=pg)
    df = pd.DataFrame(rows).astype(object)
    df = df.where(df.notna(), None)  # NaN -> None en todo el DataFrame
    # normalizaciones de catalogo
    df["zona"] = df["zona"].map(lambda z: None if z is None or z.upper() == "S/D" else z.capitalize())
    df["sector"] = df["sector"].map(lambda z: None if z is None or z.upper() == "S/D"
                                    else ("Oficial" if z.upper() == "OFICIAL" else z))
    return df

# ------------------------------------------------------------------ esquema
DDL = """
PRAGMA foreign_keys = ON;
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
"""

INDICES = """
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

# ------------------------------------------------------------------ transformacion + carga
def nf(x, dec=0):
    """Numero con punto de miles y coma decimal."""
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_resumen(a):
    """Resumen legible de la auditoria (el detalle completo queda en auditoria.json)."""
    print("\n" + "=" * 70)
    print("  MIGRACION COMPLETADA")
    print("=" * 70)
    print("\nFilas por planilla      origen   estandarizadas")
    for h, n_ in a["filas_origen"].items():
        print(f"  {h:<12}  {nf(n_):>10}   {nf(a['filas_estandarizadas'][h]):>10}")
    print("\nBase destino (filas por tabla)")
    for t_, n_ in a["destino"].items():
        print(f"  {t_:<18} {nf(n_):>10}")
    print("\nMontos adjudicados            origen           destino")
    for h, v in a["monto_origen"].items():
        d = a["monto_destino"].get(h, 0)
        print(f"  {h:<12}  {nf(v):>18}  {nf(d):>16}  {'OK' if abs(v - d) < 1 else 'REVISAR'}")
    print("\nRechazos en cuarentena")
    for k, n_ in a["rechazos_por_motivo"].items():
        print(f"  {k.replace('|', ' / '):<32} {nf(n_):>5}")
    print(f"\nIntegridad: foreign_key_check = {a['fk_violaciones']} violaciones; integrity_check = {a['integrity']}")
    print("\nTop 5 empresas por monto")
    for e, n_, m in a["top_empresas"]:
        print(f"  {e:<32} {nf(n_):>6} entregas  {nf(m):>16}")
    print("\nDetalle completo en salida/auditoria.json")


def main():
    p, m, b, t = read_all()
    AUD["filas_origen"] = {"PARQUES": len(p), "MATERIALES": len(m), "MOBILIARIO": len(b), "TIC": len(t)}
    AUD["columnas_origen"] = {"PARQUES": p.shape[1], "MATERIALES": m.shape[1], "MOBILIARIO": b.shape[1], "TIC": t.shape[1]}
    rechazos = []
    df = std_rows(p, m, b, t, rechazos)
    AUD["monto_origen"] = {h: float(g["monto"].sum()) for h, g in df.groupby("hoja")}
    AUD["filas_estandarizadas"] = df.groupby("hoja").size().to_dict()

    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(DDL)
    cur = con.cursor()
    log = []

    # ---- departamentos / distritos: mapa codigo<->nombre desde establecimientos presentes en ambas fuentes
    pk = df[df.hoja == "PARQUES"].drop_duplicates("cod").set_index("cod")
    ot = df[df.hoja != "PARQUES"].dropna(subset=["dep_cod"])
    j = ot.drop_duplicates(["cod", "dep_cod"]).join(pk[["dep_nom", "dis_nom"]], on="cod", rsuffix="_p").dropna(subset=["dep_nom_p"])
    dep_name = {int(c): mode(g["dep_nom_p"].tolist()) for c, g in j.groupby("dep_cod")}
    name_dep = {}
    for c, n in dep_name.items():
        name_dep.setdefault(n, c)
    j2 = ot.drop_duplicates(["cod", "dis_cod"]).join(pk[["dis_nom"]], on="cod", rsuffix="_p").dropna(subset=["dis_nom_p", "dis_cod"])
    dis_name = {(int(a), int(c)): mode(g["dis_nom_p"].tolist()) for (a, c), g in j2.groupby(["dep_cod", "dis_cod"])}
    name_dis = {}
    for (a, c), n in dis_name.items():
        name_dis.setdefault((a, n), c)
    AUD["mapa_departamentos"] = {int(k): v for k, v in dep_name.items()}

    # departamentos sin correspondencia de nombre (solo aparecen en TIC/otros): nombre provisional
    for c in sorted(set(int(x) for x in ot.dep_cod.dropna()) - set(dep_name)):
        dep_name[c] = f"DEPARTAMENTO {c} (nombre sin fuente)"
    for c, n in sorted(dep_name.items()):
        cur.execute("INSERT INTO departamento VALUES(?,?)", (c, n))
    log.append(("DEPARTAMENTO", "Departamentos unificados (codigo numerico + nombre)", len(dep_name)))

    # ---- establecimientos: consolidacion por moda entre fuentes
    conflictos = Counter()
    est_rows = {}
    df["clave_estab"] = df.apply(lambda r: r["cod"] if r["cod"] else "SC:" + (r["inst_nombre"] or r["nombre_estab"] or "?"), axis=1)
    for k, g in df.groupby("clave_estab", sort=False):
        rec = {"cod": g["cod"].iloc[0]}
        for attr in ["lat", "lon", "zona", "sector", "cai", "indigena"]:
            vals = [round(v, 5) if isinstance(v, float) else v for v in g[attr].tolist() if v is not None and not pd.isna(v)]
            if len(set(vals)) > 1:
                conflictos[attr] += 1
            rec[attr] = mode(vals)
        nm = [x for x in g["nombre_estab"].tolist() if x] or [x for x in g["inst_nombre"].tolist() if x]
        rec["nombre"] = mode(nm) or "(sin nombre)"
        dc = [int(x) for x in g["dep_cod"].tolist() if x is not None and not pd.isna(x)]
        dn = [x for x in g["dep_nom"].tolist() if x]
        dep = mode(dc) if dc else name_dep.get(mode(dn))
        dsc = [int(x) for x in g["dis_cod"].tolist() if x is not None and not pd.isna(x)]
        dsn = [x for x in g["dis_nom"].tolist() if x]
        dis_c = mode(dsc) if dsc else name_dis.get((dep, mode(dsn)))
        dis_n = mode(dsn) or dis_name.get((dep, dis_c))
        rec["dep"], rec["dis_c"], rec["dis_n"] = dep, dis_c, dis_n
        est_rows[k] = rec
    AUD["conflictos_atributos_establecimiento"] = dict(conflictos)

    dis_id = {}
    est_id = {}
    for k, r in est_rows.items():
        did = None
        if r["dep"] is not None:
            kk = (r["dep"], r["dis_c"], r["dis_n"] if r["dis_c"] is None else None)
            if kk not in dis_id:
                cur.execute("INSERT INTO distrito(id_departamento,cod_distrito,nombre) VALUES(?,?,?)",
                            (r["dep"], r["dis_c"], r["dis_n"]))
                dis_id[kk] = cur.lastrowid
            did = dis_id[kk]
        cur.execute("""INSERT INTO establecimiento(codigo,nombre,id_distrito,latitud,longitud,tipo_zona,sector,cai,indigena)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (r["cod"], r["nombre"], did, r["lat"], r["lon"], r["zona"], r["sector"], r["cai"], r["indigena"]))
        est_id[k] = cur.lastrowid
    # nombres de distrito faltantes en distritos existentes
    log.append(("DISTRITO", "Distritos unicos (dep+codigo)", len(dis_id)))
    log.append(("ESTABLECIMIENTO", "Establecimientos consolidados de las 4 fuentes", len(est_id)))

    # ---- instituciones
    inst = df.dropna(subset=["inst_cod"]).groupby("inst_cod")
    for c, g in inst:
        nm = mode([x for x in g["inst_nombre"] if x])
        cur.execute("INSERT INTO institucion VALUES(?,?,?)", (int(c), nm, est_id[g["clave_estab"].iloc[0]]))
    AUD["instituciones"] = int(inst.ngroups)

    # ---- empresas
    ek = {}
    for e in df["empresa"].dropna():
        ek.setdefault(key(e), []).append(e)
    emp_id = {}
    for k, v in ek.items():
        cur.execute("INSERT INTO empresa(nombre) VALUES(?)", (mode(v),))
        emp_id[k] = cur.lastrowid
    AUD["empresas_variantes"] = len(set(df["empresa"].dropna()))
    AUD["empresas_unicas"] = len(emp_id)

    # ---- llamados y contratos
    d = df[df["id1"].notna()].copy()
    for i1, g in d.groupby("id1"):
        cur.execute("INSERT INTO llamado VALUES(?,?)", (int(i1), mode(g["licitacion"].tolist())))
    AUD["variantes_codigo_licitacion"] = int(df["licitacion"].nunique())
    d["fc"] = d["fecha_contrato"].map(to_date)
    d["ekey"] = d["empresa"].map(key)
    con_id = {}
    for (i1, lo, ek_), g in d.groupby(["id1", "lote", "ekey"], dropna=False):
        fc = mode([x[0] for x in g["fc"] if x[0]])
        fa = mode([x[2] for x in g["fc"] if x[2]])
        cur.execute("INSERT INTO contrato(id_llamado,nro_lote,id_empresa,fecha_contrato,fecha_adenda) VALUES(?,?,?,?,?)",
                    (int(i1), int(lo) if lo is not None and lo == lo else 0, emp_id[ek_], fc, fa))
        con_id[(i1, lo, ek_)] = cur.lastrowid
    log.append(("CONTRATO", "Contratos (llamado+lote+empresa)", len(con_id)))

    # ---- items y conceptos de pago
    item_id, conc_id = {}, {}
    for (cat, it), g in d.groupby(["cat", "item"]):
        cur.execute("INSERT INTO item(categoria,descripcion,tipologia) VALUES(?,?,?)", (cat, it, g["tipologia"].iloc[0]))
        item_id[(cat, it)] = cur.lastrowid
    for c in ["ANTICIPO", "ANTICIPO 20%", "PAGO 1", "PAGO 2", "PAGO PARCIAL 30%", "CANCELACION 45%", "FONDO DE REPARO 5%"]:
        cur.execute("INSERT INTO concepto_pago(nombre) VALUES(?)", (c,))
        conc_id[c] = cur.lastrowid

    # ---- entregas + pagos
    n_ent = n_pag = 0
    for _, r in df.iterrows():
        if r["id1"] is None or r["item"] is None:
            rechazos.append((r["hoja"], r["fila"], "SIN_ENTREGA", "Establecimiento listado sin contrato/item asociado"))
            continue
        fa, fa_txt, _ = to_date(r["acta"])
        fi, _, _ = to_date(r["fecha_insc"])
        obs = clean(r["obs"])
        if fa_txt and fa_txt.lower().startswith("memo"):
            obs = (obs + " | " if obs else "") + fa_txt
            fa_txt = None
        cid = con_id[(r["id1"], r["lote"], key(r["empresa"]))]
        cur.execute("""INSERT INTO entrega(id_establecimiento,cod_institucion,id_contrato,id_item,cantidad,monto_adjudicado,
                       multa,tiene_adenda,fecha_acta,fecha_acta_texto,inscripta_patrimonio,fecha_inscripcion,tiene_seguro,
                       observacion,hoja_origen,fila_origen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (est_id[r["clave_estab"]], int(r["inst_cod"]) if r["inst_cod"] is not None else None,
                     cid, item_id[(r["cat"], r["item"])], r["cantidad"], r["monto"], r["multa"], r["adenda"],
                     fa, fa_txt, r["inscripta"], fi, r["seguro"], obs, r["hoja"], int(r["fila"])))
        eid = cur.lastrowid
        n_ent += 1
        for cn, mv in r["pagos"].items():
            if mv is not None and mv > 0:
                cur.execute("INSERT INTO pago(id_entrega,id_concepto,monto) VALUES(?,?,?)", (eid, conc_id[cn], mv))
                n_pag += 1
    log.append(("ENTREGA", "Lineas de entrega migradas", n_ent))
    log.append(("PAGO", "Pagos (filas) generados desde columnas repetidas", n_pag))
    cur.executemany("INSERT INTO rechazo_migracion VALUES(?,?,?,?)", rechazos)
    cur.executemany("INSERT INTO log_migracion VALUES(?,?,?)", log)
    cur.executescript(INDICES)
    cur.executescript(VISTAS)
    con.commit()

    # ---- verificacion cruzada (Fase 4)
    q = lambda s: cur.execute(s).fetchall()
    AUD["destino"] = {t_: q(f"SELECT COUNT(*) FROM {t_}")[0][0] for t_ in
                      ["departamento", "distrito", "establecimiento", "institucion", "empresa", "llamado", "contrato",
                       "item", "entrega", "concepto_pago", "pago", "rechazo_migracion"]}
    AUD["monto_destino"] = {h: v for h, v in q("SELECT hoja_origen, SUM(monto_adjudicado) FROM entrega GROUP BY hoja_origen")}
    AUD["rechazos_por_motivo"] = {f"{h}|{mv}": n for h, mv, n in q("SELECT hoja,motivo,COUNT(*) FROM rechazo_migracion GROUP BY 1,2")}
    AUD["fk_violaciones"] = len(q("PRAGMA foreign_key_check"))
    AUD["integrity"] = q("PRAGMA integrity_check")[0][0]
    AUD["coord_nulas_estab"] = q("SELECT COUNT(*) FROM establecimiento WHERE latitud IS NULL OR longitud IS NULL")[0][0]
    AUD["fechas_acta_parciales"] = q("SELECT COUNT(*) FROM entrega WHERE fecha_acta_texto IS NOT NULL")[0][0]
    AUD["conciliacion"] = {h: (n, ndif, round(mx or 0, 2)) for h, n, ndif, mx in q(
        "SELECT hoja_origen, COUNT(*), SUM(ABS(diferencia)>1), MAX(ABS(diferencia)) FROM v_conciliacion_pagos GROUP BY 1")}
    AUD["cobertura"] = {int(k): n for k, n in q("SELECT categorias_recibidas, COUNT(*) FROM v_cobertura_establecimiento GROUP BY 1")}
    AUD["top_empresas"] = q("SELECT empresa, entregas, ROUND(monto_total) FROM v_resumen_empresa ORDER BY monto_total DESC LIMIT 5")
    con.close()
    with open(os.path.join(OUT, "auditoria.json"), "w", encoding="utf-8") as f:
        json.dump(AUD, f, ensure_ascii=False, indent=1, default=str)
    imprimir_resumen(AUD)

if __name__ == "__main__":
    main()
