#!/usr/bin/env python3
"""Pipeline de inteligencia de alertas — Parco.

Orquesta las 7 capas del DAG determinista:
  ingest → normalize → dedupe → profiles → score → views → report

Uso:
    python pipeline.py --input data/raw/alerts_combined.json
    python pipeline.py --input data/raw/alerts_combined.json --no-llm
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

# Cargar variables de entorno desde .env (GEMINI_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline de inteligencia de alertas — Parco"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Ruta al JSON de alertas (alerts_combined.json)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Omitir la llamada a Gemini; digest con plantilla determinista",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: No se encuentra el archivo de entrada: {input_path}", file=sys.stderr)
        return 1

    # Directorio raíz del pipeline (donde vive este script)
    root = Path(__file__).parent
    output_dir = root / "output"
    config_path = root / "config.yaml"

    # Cargar config
    print("→ Cargando config.yaml…")
    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # API key de Gemini (vacía si --no-llm)
    api_key: str | None = None
    if not args.no_llm:
        api_key = os.environ.get("GEMINI_API_KEY") or None
        if not api_key:
            print("  [info] GEMINI_API_KEY no encontrada — digest en modo sin LLM")

    # Importar capas (después de establecer el path)
    sys.path.insert(0, str(root))
    from src.ingest import load, validate
    from src.normalize import normalize
    from src.dedupe import dedupe
    from src.profiles import build_profiles
    from src.score import score
    from src.views import vista_composicion, vista_patrones
    from src.report import build_metrics, build_digest, build_panel, write_outputs

    try:
        # Capa 1 — Ingest
        print("→ [1/7] Ingest…")
        records = load(input_path)
        report = validate(records)
        print(f"  {report['total']} registros · canales: {report['channel_counts']}")

        # Capa 2 — Normalize
        print("→ [2/7] Normalize…")
        df_norm = normalize(records, config)
        print(f"  {len(df_norm)} alertas normalizadas")

        # Capa 3 — Dedupe
        print("→ [3/7] Dedupe…")
        df_inc = dedupe(df_norm, config)
        print(f"  {len(df_inc)} incidentes detectados")

        # Capa 4 — Profiles
        print("→ [4/7] Profiles…")
        df_profiles = build_profiles(df_inc)
        print(f"  {len(df_profiles)} fichas de recurrencia")

        # Capa 5 — Score
        print("→ [5/7] Score…")
        df_scored = score(df_inc, df_profiles, config)
        bandas = df_scored["banda"].value_counts().to_dict()
        print(
            f"  score calculado · P1: {bandas.get('P1', 0)} · "
            f"P2: {bandas.get('P2', 0)} · P3: {bandas.get('P3', 0)}"
        )

        # Capa 6 — Views
        print("→ [6/7] Views…")
        composicion = vista_composicion(df_norm)
        df_patrones = vista_patrones(df_scored, config)
        n_cronicos = int(df_patrones["es_cronico"].sum())
        print(f"  composicion cx: {composicion['total']} alertas · {n_cronicos} crónicos activos")

        # Capa 7 — Report
        print("→ [7/7] Report…")
        metrics = build_metrics(df_norm, df_scored, composicion, config)
        digest = build_digest(df_scored, df_patrones, composicion, config, api_key=api_key)
        panel = build_panel(df_scored, df_patrones, composicion, metrics, digest)
        write_outputs(output_dir, df_scored, metrics, digest, panel)
        print(f"  artefactos escritos en {output_dir}/")

    except Exception:
        traceback.print_exc()
        return 1

    # Resumen final
    n_alertas = len(df_norm)
    n_inc = len(df_scored)
    print()
    print("✓ Pipeline completo")
    print(
        f"  {n_alertas} alertas → {n_inc} incidentes "
        f"(P1: {bandas.get('P1', 0)} · P2: {bandas.get('P2', 0)} · P3: {bandas.get('P3', 0)})"
    )
    print(f"  {n_cronicos} crónicos activos")
    print(
        "  output/incidents.csv · output/metrics.json · "
        "output/digest.md · output/panel.html"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
