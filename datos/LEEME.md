# Carpeta `datos/`

Aquí van las **cuatro planillas Excel originales** del Programa SNIP 388. No están en el repositorio
(pueden contener información no pública, ver "Viabilidad legal" en la presentación).

Nombres esperados (el script busca por prefijo):

| Planilla | Archivo |
|---|---|
| Parques | `Encabezado_PARQUES_EXPANSION_UV.xlsx` |
| Materiales didácticos | `Encabezado_MATERIALES*.xlsx` |
| Mobiliario | `Encabezado_MOBILIARIO*.xlsx` |
| Dotación TIC | `Encabezado_DOTAC*.xls` (formato antiguo; requiere `xlrd`) |

Con las planillas aquí, `python scripts/migracion_fenix.py` reconstruye `salida/fenix_normalizada.db` desde cero
y `python scripts/benchmark_fenix.py` repite la comparación contra las planillas.
