from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from futures_research_backtest import (
    ResearchConfig,
    _json_safe,
    _prepare_segmented_bars,
    load_futures_bars,
)
from tianji_auto_research import run_auto_research


def write_auto_report(result, output_dir):
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(
            f"refusing to overwrite automatic research evidence: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(
        prefix=f".{output.name}.", dir=output.parent
    ))
    try:
        payload = _json_safe(result)
        (temporary / "auto_research_report.json").write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        (temporary / "search_space.json").write_text(
            json.dumps(
                payload["search_space"],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        for filename, key in (
            ("stage1_metrics.csv", "stage1_metrics"),
            ("stage2_metrics.csv", "stage2_metrics"),
            ("attack_metrics.csv", "attack_metrics"),
            ("survivors.csv", "survivors"),
        ):
            result[key].to_csv(temporary / filename, index=False)
        if payload["selected_rule"] is not None:
            (temporary / "selected_rule.json").write_text(
                json.dumps(
                    payload["selected_rule"],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                ) + "\n",
                encoding="utf-8",
            )
        (temporary / "auto_research_report.md").write_text(
            "\n".join([
                f"# {payload['status']}",
                "",
                f"Selected candidate: `{payload['selected_candidate']}`",
                "",
                "Development-only weighted-index research; not final OOS evidence.",
            ]) + "\n",
            encoding="utf-8",
        )
        json.loads(
            (temporary / "auto_research_report.json").read_text(
                encoding="utf-8"
            )
        )
        if output.exists():
            output.rmdir()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    config = ResearchConfig(
        strategy_mode="tianji",
        timeframe="15m",
        min_symbols=8,
        min_symbol_rows=1000,
    )
    bars = load_futures_bars(args.db_path)
    segmented, quality = _prepare_segmented_bars(bars, config)
    result = run_auto_research(segmented, quality, config)
    write_auto_report(result, args.output_dir)
    print(json.dumps({
        "status": result["status"],
        "selected_candidate": result["selected_candidate"],
        "output_dir": str(args.output_dir.resolve()),
    }, ensure_ascii=False))
    return 0 if result["selected_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

