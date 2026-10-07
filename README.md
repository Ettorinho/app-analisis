# app-analisis

## Combinar IQVIA con el modelo de datos común (CDM)

El script [`scripts/combine_iqvia_to_model.py`](scripts/combine_iqvia_to_model.py) toma el CSV
exportado de IQVIA (`IQVIA 4T2024 H.csv`, formato CMBD) y la plantilla `common_datamodel.xlsx`
(CDM MAPBM v0.0.3) y genera en `output/` un CSV por entidad del modelo:

`HOSPITAL.csv`, `EPISODE.csv`, `LAB.csv`, `TRANSFUSION.csv`, `HOSP_PHARMACY.csv`,
`HOSP_AMB_PHARMACY.csv`, `AMB_PHARMACY.csv`, `VISCOELASTIC_TEST.csv`.

### Ejecución

```bash
pip install -r requirements.txt
python scripts/combine_iqvia_to_model.py
```

Argumentos opcionales:

| Argumento | Por defecto | Descripción |
|-----------|-------------|-------------|
| `--csv` | `IQVIA 4T2024 H.csv` | CSV de IQVIA de entrada |
| `--model` | `common_datamodel.xlsx` | Plantilla CDM |
| `--output-dir` | `output/` | Carpeta de salida |
| `--sep` | `;` | Separador de los CSV de salida |
| `--salt` | variable `IQVIA_PSEUDO_SALT` o vacío | Clave secreta (HMAC) para pseudonimizar `patient_id` / `episode_id` |

Ejemplo: `python scripts/combine_iqvia_to_model.py --csv "IQVIA 1T2025 H.csv" --salt "mi-secreto"`

### Qué hace

1. Lee el CSV detectando automáticamente encoding (UTF-8 / latin1) y separador (`|`, `;`, `,`, tabulador).
   El fichero actual usa `|` y UTF-8.
2. Lee las hojas de entidad del xlsx (`hospital`, `episode`, `lab`, `transfusion`, `hosp_pharmacy`,
   `hosp_amb_pharmacy`, `amb_pharmacy`, `viscoelastic_test`). Cada hoja describe una variable por fila;
   la columna `label` define las **cabeceras exactas y su orden** y la columna `format` el formato.
3. Aplica el mapeo descrito abajo y escribe los CSV con:
   - separador `;` (configurable con `--sep`),
   - UTF-8 **sin BOM**,
   - punto (`.`) como separador decimal,
   - fechas `YYYY-MM-DD HH:MM:SS` (variables `Datetime`) o `YYYY-MM-DD` (variables `Date`).
     El CSV de origen solo contiene fechas sin hora, por lo que la hora se escribe como `00:00:00`.
4. Muestra por consola las columnas que han quedado sin mapear (vacías).

### Mapeo aplicado

#### HOSPITAL.csv (una fila por hospital distinto)

| Columna CDM | Origen IQVIA | Notas |
|-------------|--------------|-------|
| `cnh_cd` | `HOSPITAL` | |
| `cnh_nm` | `HOSPITAL_DES` | |
| `aacc_cd` | `HOSPITAL` | Provincia (2 primeros dígitos del CNH) → código NUTS2 (p. ej. 22 Huesca → `ES24` Aragón) |
| `size_nm` | — | **Sin mapear** (nº de camas no disponible) |
| `teaching_bl` | — | **Sin mapear** |

#### EPISODE.csv (una fila por registro del CSV)

| Columna CDM | Origen IQVIA | Notas |
|-------------|--------------|-------|
| `patient_id` | `HOSPITAL` + `HISTORIA` | Pseudonimizado: HMAC-SHA256 con la clave `--salt` (16 primeros caracteres hex) |
| `cnh_cd` | `HOSPITAL` | |
| `episode_id` | `HOSPITAL` + `HISTORIA` + `FECING` + `FECALT` | Pseudonimizado igual que `patient_id` (`EPISODIO` viene vacío, `-`) |
| `age_nm` | `FECNAC`, `FECINT1` (o `FECING`) | Años cumplidos a la fecha de intervención; si no hay, a la de ingreso |
| `sex_cd` | `SEXO` | 1→1, 2→2, 3/9→0 |
| `admission_dt` | `FECING` | |
| `discharge_dt` | `FECALT` | |
| `discharge_type_cd` | `TIPALT` | Mismos códigos RAE-CMBD (1,2,3,4,5,8,9); otros → vacío |
| `start_intervention_dt` | `FECINT1` | Solo fecha |
| `d1` … `d20` | `D1` … `D20` | |
| `poad1` … `poad20` | `POA_01` … `POA_20` | Códigos S/N/D/I/E; otros → vacío |
| `proc1` … `proc20` | `P1` … `P20` | |
| `planification_cd` | `TIPING` | 1 (urgente)→1, 2 (programado)→2, otro→9 |
| `end_intervention_dt` | — | **Sin mapear** |
| `readmission_dt`, `readmission_d1`, `readmission_poad1` | — | **Sin mapear** |
| `bleeding_bl`, `estimbleeding_nm`, `anesth_cd`, `asa_cd`, `brs_bl`, `eras_recovery_bl` | — | **Sin mapear** (formulario quirúrgico / HCE) |

Columnas de IQVIA no utilizadas: `CIP`, `TIS`, `CODPOS`, `TIPASIS`, `PROC`, `SERVING`, `FECTRASn`/`SERVTRASn`,
`SERVALT`, `SECALT`, `SECALT_DES`, `MEDICOALT`, `T1`–`T7`, `TRASHOSPITAL`, `CM1`–`CM7`, `CIAS_PRO`,
`APRV380_COD_GRD`, `APRV380_PESO`, `REGCON`, `REGCON_DES`, `EPISODIO`.

#### LAB, TRANSFUSION, HOSP_PHARMACY, HOSP_AMB_PHARMACY, AMB_PHARMACY, VISCOELASTIC_TEST

El CSV de IQVIA es un extracto del CMBD y **no contiene** datos de laboratorio, banco de sangre,
farmacia ni test viscoelásticos. Estos ficheros se generan **solo con las cabeceras del CDM** y
todas sus columnas quedan sin mapear. Deben completarse con las fuentes indicadas en el CDM
(Lab registry, Blood bank registry, farmacia, VET registry), usando el mismo `patient_id`
pseudonimizado (`HOSPITAL|HISTORIA` + misma sal).

### Advertencias

- No se aplican los criterios de inclusión/exclusión de cohorte (`cohort_definition_*`): se exportan todos los episodios.
- Sin `--salt` los identificadores se calculan sin clave secreta y podrían revertirse por fuerza bruta
  (los números de historia son predecibles). Indica siempre una clave secreta, guárdala fuera del repositorio
  y usa siempre la misma para que los identificadores coincidan entre entidades y ejecuciones.
  Los CSV de `output/` del repositorio se generaron sin clave (el CSV de origen, con `CIP`, ya está en el repositorio).
- Para ajustar el mapeo, edita las funciones `hospital_mapping()` / `episode_mapping()` /
  `entity_mappings()` del script.
