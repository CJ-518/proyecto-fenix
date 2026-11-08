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

Con las planillas aquí, `python demo.py migracion` reconstruye `salida/fenix_normalizada.db` desde cero
y `python demo.py benchmark` repite la comparación contra las planillas.

Sin ellas, las demos 1 a 5 funcionan igual sobre la base ya generada que está en `salida/`.
