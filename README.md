# Proyecto Fénix · Reingeniería, migración y optimización del Programa SNIP 388

Repositorio con los scripts del proyecto y **demos ejecutables** para mostrar sus resultados en la presentación.
Las cuatro planillas Excel (parques, materiales didácticos, mobiliario y dotación TIC) se migran a una base
relacional SQLite en 3FN, y opcionalmente a **Oracle**.

## Inicio rápido (sin las planillas originales)

Solo requiere Python 3.9+ (las demos usan únicamente la biblioteca estándar) y trabajan sobre la base ya generada
en `salida/fenix_normalizada.db`:

```bash
python demo.py          # menú interactivo
python demo.py 3        # una demo concreta
python demo.py todo     # las cinco, con pausa entre cada una
```

## Demos y su lugar en la presentación

| Demo | Comando | Qué muestra | Diapositiva |
|---|---|---|---|
| 1 | `python demo.py 1` | Las tablas del modelo, 11 claves foráneas, 15 CHECK, y el motor rechazando datos inválidos en vivo | 6 · Modelo rediseñado |
| 2 | `python demo.py 2` | Antes y después: códigos de 7 caracteres, coordenadas decimales, empresas unificadas, duplicados | 4 · Hallazgos |
| 3 | `python demo.py 3` | Conciliación de filas y montos origen–destino, rechazos con motivo, 0 violaciones de claves | 7–8 · ETL y conciliación |
| 4 | `python demo.py 4` | Consultas que cruzan las cuatro fuentes: empresas, departamentos, cobertura, trazabilidad a la fila de Excel | 10 · Lo que revela la base |
| 5 | `python demo.py 5` | Efecto de los índices medido en vivo y comparación con las planillas | 9 · Optimización |

Cada demo imprime el SQL que ejecuta, de modo que la audiencia ve que los números salen de la base y no de una diapositiva.
Las cifras de conciliación, integridad y rendimiento con índices se recalculan en cada ejecución; solo la
comparación contra las planillas legacy (demo 5) y las cifras de origen (demo 3) se leen de `salida/benchmark.json` y
`salida/auditoria.json`, generados por los scripts completos.

## Con las planillas originales (pipeline completo) y Oracle

1. Copie los cuatro `Encabezado_*.xlsx` en `datos/` (ver `datos/LEEME.md`).
2. Instale dependencias: `pip install -r requirements.txt` (incluye `xlrd` y `oracledb`)
3. Ejecute:

```bash
python demo.py migracion    # = python scripts/migracion_fenix.py   -> reconstruye salida/fenix_normalizada.db y auditoria.json
python demo.py benchmark    # = python scripts/benchmark_fenix.py   -> salida/benchmark.json
python demo.py oracle       # carga la base migrada en Oracle (para verla en DBeaver)
python demo.py limpiar      # borra de Oracle todo lo cargado
```

La migración es **idempotente**: borra y reconstruye la base en cada ejecución. Si no encuentra las planillas, termina
con un mensaje claro sin tocar la base existente. Ambos scripts aceptan rutas propias:
`python scripts/migracion_fenix.py <carpeta_datos> <carpeta_salida>`.

Verificado con las planillas reales: la migración regenera exactamente la misma auditoría (10.930 filas, 10.821 entregas,
109 rechazos, montos idénticos). El benchmark vuelve a medir tiempos, que varían según la máquina; `salida/benchmark.json`
conserva las mediciones usadas en el informe y la presentación, y `salida/benchmark_ultima_ejecucion.json` guarda la última corrida local.

## Estructura

```
demo.py                  lanzador de demos (interactivo, migracion, benchmark, oracle, limpiar)
demos/                   demos 1 a 5 (solo sqlite3 de la biblioteca estándar)
scripts/
  migracion_fenix.py     ETL: extraer, estandarizar, depurar, cargar, verificar
  benchmark_fenix.py     planillas "tal cual" vs. base normalizada (mediana de 15 ejecuciones)
  cargar_oracle.py       carga los datos normalizados en Oracle Database
  limpiar_oracle.py      limpia los datos cargados en Oracle Database
datos/                   planillas originales (vía Git LFS / exclusión)
salida/                  base generada, auditoria.json, benchmark.json
docs/                    informe (.docx) y presentación (.pptx)
```

## Notas

- Los scripts `migracion_fenix.py` y `benchmark_fenix.py` utilizan rutas relativas al repositorio (`datos/`, `salida/`) y avisan si faltan las planillas.
- Los tiempos son medianas en SQLite con ~11 mil filas: sirven para comparar estructuras, no para predecir producción.
