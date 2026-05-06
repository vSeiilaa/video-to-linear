from pathlib import Path
from typing import List

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from .bug_extractor import Bug

_TEMPLATES = Path(__file__).parent.parent / "templates"


def export_csv(bugs: List[Bug], path: Path) -> None:
    df = pd.DataFrame([b.model_dump() for b in bugs])
    df.to_csv(path, index=False)


def export_html(
    bugs: List[Bug],
    video_path: str,
    out_path: Path,
    provider: str = "",
    model_id: str = "",
) -> None:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)))
    template = env.get_template("report.html.j2")
    html = template.render(
        bugs=bugs,
        video_path=video_path,
        provider=provider,
        model_id=model_id,
    )
    out_path.write_text(html, encoding="utf-8")
