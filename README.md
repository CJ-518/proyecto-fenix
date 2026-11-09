# Proyecto Fénix · Reingeniería, migración y optimización del Programa SNIP 388

Repositorio con los scripts del proyecto. Las cuatro planillas Excel (parques, materiales didácticos, mobiliario y
dotación TIC) se migran a una base relacional SQLite en 3FN, y opcionalmente a **Oracle**.

## Uso

1. Copie los cuatro `Encabezado_*.xlsx` en `datos/` (ver `datos/LEEME.md`).
2. Instale dependencias: `pip install -r requirements.txt` (incluye `xlrd` y `oracledb`)
3. Ejecute:

```bash
python scripts/migracion_fenix.py          # reconstruye salida/fenix_normalizada.db y auditoria.json
python scripts/benchmark_fenix.py          # compara planillas legacy vs. base normalizada -> salida/benchmark.json
python scripts/seguridad_fenix.py aplicar  # bitácora de cambios, triggers y sello SHA-256
python scripts/seguridad_fenix.py verificar  # comprueba que la base no fue alterada
python scripts/cargar_oracle.py            # carga la base migrada en Oracle (para verla en DBeaver)
python scripts/limpiar_oracle.py           # borra de Oracle todo lo cargado
```

La migración es **idempotente**: borra y reconstruye la base en cada ejecución. Si no encuentra las planillas, termina
con un mensaje claro sin tocar la base existente. Los scripts aceptan rutas propias:
`python scripts/migracion_fenix.py <carpeta_datos> <carpeta_salida>`.

Verificado con las planillas reales: la migración regenera la misma auditoría (10.930 filas, 10.821 entregas,
109 rechazos, montos idénticos). El benchmark vuelve a medir tiempos, que varían según la máquina; `salida/benchmark.json`
conserva las mediciones usadas en el informe y la presentación, y `salida/benchmark_ultima_ejecucion.json` guarda la última corrida local.

Si se pasa el control de acceso a Oracle, `scripts/seguridad_oracle.sql` define los roles (lector, cargador, admin) y la auditoría.

## Estructura

```
scripts/
  migracion_fenix.py     ETL: extraer, estandarizar, depurar, cargar, verificar
  benchmark_fenix.py     planillas "tal cual" vs. base normalizada (mediana de 15 ejecuciones)
  seguridad_fenix.py     bitácora de cambios, trazabilidad inmutable y sello de integridad
  seguridad_oracle.sql   roles de mínimo privilegio y auditoría en Oracle
  cargar_oracle.py       carga los datos normalizados en Oracle Database
  limpiar_oracle.py      limpia los datos cargados en Oracle Database
datos/                   planillas originales (no incluidas en el repositorio)
salida/                  base generada, auditoria.json, benchmark.json
docs/                    informe (.pdf y .docx) y presentación (.pptx)
```

## Notas

- Los scripts `migracion_fenix.py` y `benchmark_fenix.py` utilizan rutas relativas al repositorio (`datos/`, `salida/`) y avisan si faltan las planillas.
- Los tiempos son medianas en SQLite con ~11 mil filas: sirven para comparar estructuras, no para predecir producción.

## Licencia

Este proyecto está distribuido bajo los términos de la licencia **GNU General Public License v3.0 (GPLv3)**. Consulta el archivo [LICENSE](LICENSE) para más detalles.
