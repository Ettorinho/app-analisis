#!/usr/bin/env python3
"""Combina el CSV exportado de IQVIA (CMBD) con el modelo de datos común (CDM).

Lee ``IQVIA 4T2024 H.csv`` y ``common_datamodel.xlsx`` (por defecto, desde la raíz
del repositorio), usa las hojas de entidad del xlsx como esquema objetivo (la
columna ``label`` de cada hoja define las cabeceras y su orden) y genera un CSV
por entidad en ``output/``:

    HOSPITAL.csv, EPISODE.csv, LAB.csv, TRANSFUSION.csv, HOSP_PHARMACY.csv,
    HOSP_AMB_PHARMACY.csv, AMB_PHARMACY.csv, VISCOELASTIC_TEST.csv

Formato de salida:
    * separador ``;`` (configurable con ``--sep``)
    * UTF-8 sin BOM
    * punto (``.``) como separador decimal
    * fechas ``YYYY-MM-DD HH:MM:SS`` (``YYYY-MM-DD`` para variables ``Date``)
    * cabeceras exactas del CDM

Uso:
    python scripts/combine_iqvia_to_model.py [--csv RUTA] [--model RUTA]
        [--output-dir DIR] [--sep SEP] [--salt SALT]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "IQVIA 4T2024 H.csv"
DEFAULT_MODEL = REPO_ROOT / "common_datamodel.xlsx"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"

# Formato de salida
DEFAULT_SEP = ";"
OUTPUT_ENCODING = "utf-8"  # UTF-8 sin BOM
DECIMAL = "."
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

# Formato de fecha de origen en el CSV de IQVIA (dd/mm/aaaa)
SOURCE_DATE_FORMAT = "%d/%m/%Y"

CANDIDATE_ENCODINGS = ("utf-8-sig", "latin1")
CANDIDATE_SEPARATORS = "|;,\t"

# Entidades a generar (nombre del CSV de salida); la hoja del xlsx se busca
# por nombre sin distinguir mayúsculas/minúsculas.
ENTITIES = [
    "HOSPITAL",
    "EPISODE",
    "LAB",
    "TRANSFUSION",
    "HOSP_PHARMACY",
    "HOSP_AMB_PHARMACY",
    "AMB_PHARMACY",
    "VISCOELASTIC_TEST",
]

# Código de provincia INE (2 primeros dígitos del código CNH) -> NUTS2 (catálogo
# ``hospital_aacc_cd`` del CDM).
PROVINCE_TO_NUTS2 = {
    "01": "ES21", "02": "ES42", "03": "ES52", "04": "ES61", "05": "ES41",
    "06": "ES43", "07": "ES53", "08": "ES51", "09": "ES41", "10": "ES43",
    "11": "ES61", "12": "ES52", "13": "ES42", "14": "ES61", "15": "ES11",
    "16": "ES42", "17": "ES51", "18": "ES61", "19": "ES42", "20": "ES21",
    "21": "ES61", "22": "ES24", "23": "ES61", "24": "ES41", "25": "ES51",
    "26": "ES23", "27": "ES11", "28": "ES30", "29": "ES61", "30": "ES62",
    "31": "ES22", "32": "ES11", "33": "ES12", "34": "ES41", "35": "ES70",
    "36": "ES11", "37": "ES41", "38": "ES70", "39": "ES13", "40": "ES41",
    "41": "ES61", "42": "ES41", "43": "ES51", "44": "ES24", "45": "ES42",
    "46": "ES52", "47": "ES41", "48": "ES21", "49": "ES41", "50": "ES24",
    "51": "ES63", "52": "ES64",
}

# Sexo CMBD (1 hombre, 2 mujer, 3 indeterminado, 9 no especificado) -> CDM
SEX_MAP = {"1": "1", "2": "2", "3": "0", "9": "0"}
# Tipo de alta CMBD -> catálogo discharge_type_cd del CDM (mismos códigos)
DISCHARGE_TYPE_CODES = {"1", "2", "3", "4", "5", "8", "9"}
# Tipo de ingreso CMBD (1 urgente, 2 programado) -> planification_cd del CDM
PLANIFICATION_MAP = {"1": "1", "2": "2"}
# Catálogo episode_poadN del CDM
POA_CODES = {"S", "N", "D", "I", "E"}


# --------------------------------------------------------------------------- #
# Lectura de ficheros
# --------------------------------------------------------------------------- #
def read_source_csv(path: Path) -> pd.DataFrame:
    """Lee el CSV detectando automáticamente encoding y separador."""
    raw = path.read_bytes()
    for encoding in CANDIDATE_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    header = text.splitlines()[0] if text else ""
    try:
        sep = csv.Sniffer().sniff(header, delimiters=CANDIDATE_SEPARATORS).delimiter
    except csv.Error:
        sep = max(CANDIDATE_SEPARATORS, key=header.count)

    print(f"[INFO] Leyendo '{path.name}' (encoding={encoding}, separador={sep!r})")
    df = pd.read_csv(path, sep=sep, encoding=encoding, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    return df.apply(lambda s: s.str.strip())


def read_model_schema(path: Path) -> Dict[str, pd.DataFrame]:
    """Devuelve, por entidad, un DataFrame con ``label`` y ``format`` en orden.

    Las hojas de entidad del CDM están en formato "largo": cada fila describe
    una variable (columna ``label``). Si una hoja no tuviera la columna
    ``label``, se usan sus cabeceras directamente como columnas objetivo.
    """
    xls = pd.ExcelFile(path)
    sheets = {name.strip().lower(): name for name in xls.sheet_names}
    schema: Dict[str, pd.DataFrame] = {}
    for entity in ENTITIES:
        sheet = sheets.get(entity.lower())
        if sheet is None:
            raise ValueError(
                f"No se encontró la hoja '{entity.lower()}' en {path.name}. "
                f"Hojas disponibles: {xls.sheet_names}"
            )
        sheet_df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
        if "label" in sheet_df.columns:
            spec = sheet_df[sheet_df["label"].notna()].copy()
            spec["label"] = spec["label"].str.strip()
            if "format" not in spec.columns:
                spec["format"] = "String"
            spec["format"] = spec["format"].fillna("String").str.strip()
            spec = spec[["label", "format"]].reset_index(drop=True)
        else:
            spec = pd.DataFrame(
                {"label": [str(c).strip() for c in sheet_df.columns], "format": "String"}
            )
        schema[entity] = spec
    return schema


# --------------------------------------------------------------------------- #
# Transformaciones auxiliares
# --------------------------------------------------------------------------- #
def parse_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, format=SOURCE_DATE_FORMAT, errors="coerce")


def pseudonymize(series: pd.Series, salt: str) -> pd.Series:
    key = salt.encode("utf-8")
    return series.map(
        lambda v: hmac.new(key, v.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    )


def map_codes(series: pd.Series, mapping: Dict[str, str], default: str = "") -> pd.Series:
    return series.map(lambda v: mapping.get(v, default))


def keep_codes(series: pd.Series, valid: set) -> pd.Series:
    return series.where(series.isin(valid), "")


def age_in_years(birth: pd.Series, reference: pd.Series) -> pd.Series:
    birth_dt = parse_date(birth)
    ref_dt = parse_date(reference)
    years = ref_dt.dt.year - birth_dt.dt.year
    before_birthday = (ref_dt.dt.month < birth_dt.dt.month) | (
        (ref_dt.dt.month == birth_dt.dt.month) & (ref_dt.dt.day < birth_dt.dt.day)
    )
    return (years - before_birthday.astype(int)).astype("Int64")


def patient_key(df: pd.DataFrame) -> pd.Series:
    return df["HOSPITAL"] + "|" + df["HISTORIA"]


# --------------------------------------------------------------------------- #
# Mapeos por entidad: label CDM -> (descripción del origen, función)
# --------------------------------------------------------------------------- #
Mapping = Dict[str, Tuple[str, Callable[[pd.DataFrame], pd.Series]]]


def hospital_mapping() -> Mapping:
    return {
        "cnh_cd": ("HOSPITAL", lambda d: d["HOSPITAL"]),
        "cnh_nm": ("HOSPITAL_DES", lambda d: d["HOSPITAL_DES"]),
        "aacc_cd": (
            "HOSPITAL (provincia = 2 primeros dígitos del CNH -> NUTS2)",
            lambda d: d["HOSPITAL"].str.zfill(6).str[:2].map(PROVINCE_TO_NUTS2).fillna(""),
        ),
    }


def episode_mapping(salt: str) -> Mapping:
    mapping: Mapping = {
        "patient_id": (
            "HMAC-SHA256(HOSPITAL|HISTORIA)",
            lambda d: pseudonymize(patient_key(d), salt),
        ),
        "cnh_cd": ("HOSPITAL", lambda d: d["HOSPITAL"]),
        "episode_id": (
            "HMAC-SHA256(HOSPITAL|HISTORIA|FECING|FECALT)",
            lambda d: pseudonymize(patient_key(d) + "|" + d["FECING"] + "|" + d["FECALT"], salt),
        ),
        "age_nm": (
            "FECNAC y FECINT1 (o FECING si no hay intervención)",
            lambda d: age_in_years(
                d["FECNAC"], d["FECINT1"].where(d["FECINT1"] != "", d["FECING"])
            ),
        ),
        "sex_cd": ("SEXO", lambda d: map_codes(d["SEXO"], SEX_MAP)),
        "admission_dt": ("FECING", lambda d: parse_date(d["FECING"])),
        "discharge_dt": ("FECALT", lambda d: parse_date(d["FECALT"])),
        "discharge_type_cd": ("TIPALT", lambda d: keep_codes(d["TIPALT"], DISCHARGE_TYPE_CODES)),
        "start_intervention_dt": ("FECINT1", lambda d: parse_date(d["FECINT1"])),
        "planification_cd": (
            "TIPING",
            lambda d: map_codes(d["TIPING"], PLANIFICATION_MAP, default="9"),
        ),
    }
    for i in range(1, 21):
        mapping[f"d{i}"] = (f"D{i}", lambda d, c=f"D{i}": d[c])
        mapping[f"poad{i}"] = (
            f"POA_{i:02d}",
            lambda d, c=f"POA_{i:02d}": keep_codes(d[c], POA_CODES),
        )
        mapping[f"proc{i}"] = (f"P{i}", lambda d, c=f"P{i}": d[c])
    return mapping


def entity_mappings(salt: str) -> Dict[str, Mapping]:
    return {
        "HOSPITAL": hospital_mapping(),
        "EPISODE": episode_mapping(salt),
        # El CSV de IQVIA (CMBD) no contiene datos de laboratorio, transfusión,
        # farmacia ni test viscoelásticos: se generan solo con cabeceras.
        "LAB": {},
        "TRANSFUSION": {},
        "HOSP_PHARMACY": {},
        "HOSP_AMB_PHARMACY": {},
        "AMB_PHARMACY": {},
        "VISCOELASTIC_TEST": {},
    }


def entity_rows(entity: str, source: pd.DataFrame) -> pd.DataFrame:
    if entity == "HOSPITAL":
        return source.drop_duplicates(subset=["HOSPITAL"]).reset_index(drop=True)
    if entity == "EPISODE":
        return source.reset_index(drop=True)
    return source.iloc[0:0].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Construcción y escritura
# --------------------------------------------------------------------------- #
def format_column(values: pd.Series, fmt: str) -> pd.Series:
    fmt_l = fmt.lower()
    if fmt_l in ("datetime", "date"):
        if not pd.api.types.is_datetime64_any_dtype(values):
            values = pd.to_datetime(values, errors="coerce")
        out_fmt = DATETIME_FORMAT if fmt_l == "datetime" else DATE_FORMAT
        return values.dt.strftime(out_fmt).fillna("")
    if fmt_l in ("integer", "double"):
        if not pd.api.types.is_numeric_dtype(values):
            cleaned = values.astype(str).str.replace(",", DECIMAL, regex=False)
            values = pd.to_numeric(cleaned, errors="coerce")
        if fmt_l == "integer":
            values = values.round().astype("Int64")
        return values
    return values.fillna("").astype(str)


def build_entity(
    entity: str, spec: pd.DataFrame, source: pd.DataFrame, mapping: Mapping
) -> Tuple[pd.DataFrame, List[str]]:
    rows = entity_rows(entity, source)
    data = {}
    unmapped = []
    for label, fmt in zip(spec["label"], spec["format"]):
        if label in mapping:
            data[label] = format_column(mapping[label][1](rows), fmt)
        else:
            data[label] = pd.Series([""] * len(rows), index=rows.index, dtype=object)
            unmapped.append(label)
    return pd.DataFrame(data, index=rows.index, columns=list(spec["label"])), unmapped


def write_csv(df: pd.DataFrame, path: Path, sep: str) -> None:
    df.to_csv(
        path,
        sep=sep,
        index=False,
        encoding=OUTPUT_ENCODING,
        decimal=DECIMAL,
        lineterminator="\n",
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combina el CSV de IQVIA con el modelo de datos común (CDM)."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV de IQVIA de entrada")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Plantilla CDM (.xlsx)")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Carpeta de salida"
    )
    parser.add_argument(
        "--sep", default=DEFAULT_SEP, help=f"Separador de salida (por defecto {DEFAULT_SEP!r})"
    )
    parser.add_argument(
        "--salt",
        default=os.environ.get("IQVIA_PSEUDO_SALT", ""),
        help="Clave secreta (HMAC) para pseudonimizar patient_id/episode_id (o variable IQVIA_PSEUDO_SALT)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    source = read_source_csv(args.csv)
    schema = read_model_schema(args.model)
    mappings = entity_mappings(args.salt)
    if not args.salt:
        print(
            "[AVISO] Sin --salt: patient_id/episode_id se calculan sin clave secreta y "
            "podrían revertirse por fuerza bruta. Indique --salt o IQVIA_PSEUDO_SALT."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for entity in ENTITIES:
        df, unmapped = build_entity(entity, schema[entity], source, mappings[entity])
        out_path = args.output_dir / f"{entity}.csv"
        write_csv(df, out_path, args.sep)
        print(f"[OK] {out_path.name}: {len(df)} filas, {len(df.columns)} columnas")
        if unmapped:
            print(f"     Columnas sin mapear (vacías): {', '.join(unmapped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
