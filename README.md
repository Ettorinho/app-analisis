# Exportación IQVIA al modelo común de datos

El script `scripts/combine_iqvia_to_model.py` transforma el CSV de IQVIA en ocho
CSV independientes. Usa las etiquetas de la columna `label` de cada hoja del
archivo `common_datamodel.xlsx` como cabeceras de salida, respetando su orden.
El script detecta la codificación y el separador del archivo de origen (el
archivo incluido actualmente usa UTF-8 y `|`) y lee los valores como texto para
no alterar identificadores ni códigos.

## Ejecución

Instala las dependencias y ejecuta desde cualquier directorio:

```bash
python -m pip install -r requirements.txt
python scripts/combine_iqvia_to_model.py
```

De forma predeterminada, se leen `IQVIA 4T2024 H.csv` y
`common_datamodel.xlsx` de la raíz del repositorio y se escriben los resultados
en `output/`. Se pueden indicar otras rutas:

```bash
python scripts/combine_iqvia_to_model.py \
  --source /ruta/origen.csv \
  --model /ruta/common_datamodel.xlsx \
  --output-dir /ruta/salida
```

## Mapeo y limitaciones

El origen incluido contiene registros hospitalarios/episodios, pero no contiene
registros de laboratorio, farmacia, transfusiones ni pruebas viscoelásticas.
Por tanto, esos seis archivos se generan con las cabeceras CDM exactas y sin
filas de datos.

| Salida | Mapeo aplicado desde el CSV IQVIA |
| --- | --- |
| `HOSPITAL.csv` | `cnh_cd` ← `HOSPITAL`; `cnh_nm` ← `HOSPITAL_DES`. Se genera una fila por hospital distinto. |
| `EPISODE.csv` | `cnh_cd` ← `HOSPITAL`; `sex_cd` ← `SEXO`; `admission_dt` ← `FECING`; `discharge_dt` ← `FECALT`; `discharge_type_cd` ← `TIPALT`; `start_intervention_dt` ← `FECINT1`; `d1`–`d20` ← `D1`–`D20`; `poad1`–`poad20` ← `POA_01`–`POA_20`; `proc1`–`proc20` ← `P1`–`P20`; `age_nm` se calcula en años cumplidos a partir de `FECNAC` y `FECING`. |
| `LAB.csv` | Sin mapeo: el origen no contiene resultados de laboratorio. |
| `TRANSFUSION.csv` | Sin mapeo: el origen no contiene datos de transfusiones. |
| `HOSP_PHARMACY.csv` | Sin mapeo: el origen no contiene datos de farmacia hospitalaria. |
| `HOSP_AMB_PHARMACY.csv` | Sin mapeo: el origen no contiene datos de farmacia hospitalaria ambulatoria. |
| `AMB_PHARMACY.csv` | Sin mapeo: el origen no contiene datos de farmacia ambulatoria. |
| `VISCOELASTIC_TEST.csv` | Sin mapeo: el origen no contiene pruebas viscoelásticas. |

Las columnas CDM que no aparecen en la tabla quedan vacías. En particular,
`patient_id` queda vacío porque el origen no proporciona un identificador
pseudonimizado; no se copian identificadores personales como `CIP`, `TIS` o
`HISTORIA`. Tampoco se asigna `EPISODIO` a `episode_id`: sus valores en este
archivo son `-`, y `HISTORIA` no es un identificador de episodio (se repite).
Los campos de hospital `aacc_cd`, `size_nm` y `teaching_bl` no están disponibles
en el origen. Las fechas `FECNAC`, `FECING`, `FECALT` y `FECINT1` se interpretan
como día/mes/año. No se infieren otros campos cuya equivalencia no sea clara.

## Formato de salida fijo

Los requisitos de formato están fijados como constantes en el script y no son
opciones de línea de comandos:

- Separador: punto y coma (`;`).
- Codificación: UTF-8 sin BOM (`utf-8`, no `utf-8-sig`).
- Decimales: punto (`.`); los valores numéricos con coma decimal se normalizan.
- Fechas/horas: `YYYY-MM-DD HH:MM:SS`; las fechas sin hora reciben `00:00:00`.
- Cabeceras: etiquetas CDM exactas de la hoja correspondiente, en el mismo
  orden definido en la plantilla, sin cambios de mayúsculas/minúsculas.

Los archivos generados son `HOSPITAL.csv`, `EPISODE.csv`, `LAB.csv`,
`TRANSFUSION.csv`, `HOSP_PHARMACY.csv`, `HOSP_AMB_PHARMACY.csv`,
`AMB_PHARMACY.csv` y `VISCOELASTIC_TEST.csv`.
