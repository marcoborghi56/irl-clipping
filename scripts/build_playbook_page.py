"""Render the skill's knowledge files into one self-contained HTML page.

    python build_playbook_page.py --out <dir>

Writes <dir>/index.html from assets/playbook_page.html. Reads references/*.md,
references/style.json, references/evidence/aggregate.md and feedback/*.md.
No network. Output is deterministic apart from the build date.
Needs python-markdown (pip install markdown).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("python-markdown is missing: run  pip install markdown")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "playbook_page.html"
DEFAULT_VIEW = "playbook"
FORBIDDEN = ("settings", "sidebar", "customize", "upgrade", "downloads", "comment-")

# (hash/id, nav label, id prefix for headings, source path relative to ROOT, text when missing)
VIEWS = [
    ("playbook", "Playbook", "pb", "references/PLAYBOOK.md", "The playbook file is missing."),
    ("rubric", "Rubric", "rb", "references/rubric.md", "The rubric file is missing."),
    ("edit-defaults", "Edit defaults", "ed", "references/style.json", "The edit defaults file is missing."),
    ("qa", "QA checklist", "qa", "references/qa_brief.md", "The QA brief is missing."),
    ("evidence", "Evidence", "ev", "references/evidence/aggregate.md", "The evidence tables are missing."),
    ("pipeline", "Pipeline", "pl", "references/DESIGN.md", "The pipeline design file is missing."),
    ("picks", "Clip picks", "pk", "feedback/SUMMARY.md", "No review round has been recorded yet."),
    ("changes", "Changes", "ch", "feedback/CHANGELOG.md", "No playbook change has been recorded yet."),
]
FALLBACK_TITLES = {
    "edit-defaults": "Edit defaults",
    "picks": "What the clip picks have taught",
    "changes": "Playbook changes",
}

esc = html.escape


def safe_id(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "s"
    for word in FORBIDDEN:
        s = s.replace(word.rstrip("-"), "x")
    return s[:60].strip("-")


def md_converter(prefix: str) -> markdown.Markdown:
    def slugify(value: str, separator: str = "-") -> str:
        return f"{prefix}-{safe_id(value)}"

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
        extension_configs={"toc": {"slugify": slugify, "toc_depth": "2-6"}},
    )
    # Treat raw HTML in the sources as text so a stray tag cannot break the page.
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    return md


def shift_headings(body: str) -> str:
    """Demote headings one level: the view header is the page's h2."""
    return re.sub(r"<(/?)h([1-5])\b", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}", body)


def wrap_tables(body: str) -> str:
    body = re.sub(r"<table\b", '<div class="tw"><table', body)
    return body.replace("</table>", "</table></div>")


def split_title(text: str) -> tuple[str | None, str]:
    m = re.match(r"\s*#\s+(.+?)\s*#*\s*\n", text + "\n")
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def inline_md(text: str) -> str:
    out = md_converter("x").convert(text)
    return re.sub(r"^<p>(.*)</p>$", r"\1", out.strip(), flags=re.S)


def render_markdown(path: Path, prefix: str):
    raw = path.read_text(encoding="utf-8")
    title, rest = split_title(raw)
    if path.name == "aggregate.md":
        # Other study write-ups in the evidence folder (e.g. speed_check.md) join the Evidence view,
        # each under its own heading with its headings demoted one level.
        for extra in sorted(path.parent.glob("*.md")):
            if extra.name in ("aggregate.md", "review_brief.md"):
                continue
            t, r = split_title(extra.read_text(encoding="utf-8"))
            rest += f"\n\n## {t or extra.stem}\n\n" + re.sub(r"^(#+) ", r"#\1 ", r, flags=re.M)
    md = md_converter(prefix)
    body = wrap_tables(shift_headings(md.convert(rest)))
    sections = [(t["id"], t["name"]) for t in md.toc_tokens]
    return (inline_md(title) if title else None), body, sections


# ---------- style.json ----------
def humanize(key: str) -> str:
    s = key.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def fmt_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def fmt_value(v) -> tuple[str, bool]:
    """Return (text, is_prose)."""
    if isinstance(v, list):
        return ", ".join(fmt_value(x)[0] for x in v) if v else "(empty)", False
    if isinstance(v, str):
        return v, (" " in v and len(v) > 24)
    return fmt_scalar(v), False


def flatten(d: dict, base: str = ""):
    for k, v in d.items():
        if k.startswith("_"):
            continue
        key = f"{base}.{k}" if base else k
        if isinstance(v, dict):
            yield from flatten(v, key)
        else:
            yield key, v


def render_style(path: Path, prefix: str):
    data = json.loads(path.read_text(encoding="utf-8"))
    parts, sections = [], []
    if isinstance(data.get("_about"), str):
        parts.append(f"<p>{esc(data['_about'])}</p>")
    loose = []
    for group, val in data.items():
        if group.startswith("_"):
            continue
        if not isinstance(val, dict):
            loose.append((group, val))
            continue
        gid = f"{prefix}-{safe_id(group)}"
        sections.append((gid, humanize(group)))
        parts.append(f'<h3 id="{gid}">{esc(humanize(group))}</h3>')
        if isinstance(val.get("_notes"), str):
            parts.append(f"<p>{esc(val['_notes'])}</p>")
        rows = list(flatten(val))
        if rows:
            parts.append(kv_table(rows))
    if loose:
        parts.append(f'<h3 id="{prefix}-other">Other values</h3>')
        parts.append(kv_table(loose))
    return None, "\n".join(parts), sections


def kv_table(rows) -> str:
    out = ['<div class="tw"><table class="kv"><thead><tr><th scope="col">Key</th>'
           '<th scope="col">Value</th></tr></thead><tbody>']
    for k, v in rows:
        text, prose = fmt_value(v)
        cls = "t" if prose else "v"
        out.append(f'<tr><td>{esc(k)}</td><td class="{cls}">{esc(text)}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


# ---------- facts ----------
def count_changelog(path: Path) -> int:
    if not path.is_file():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    heads = [l for l in lines if re.match(r"##\s+\S", l)]
    if heads:
        return len(heads)
    return len([l for l in lines if re.match(r"[-*]\s+\S", l)])


def count_rounds(path: Path) -> int:
    return sum(1 for p in path.iterdir() if p.is_file()) if path.is_dir() else 0


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# ---------- page ----------
def build(out_dir: Path) -> Path:
    template = TEMPLATE.read_text(encoding="utf-8")
    nav, views = [], []
    for vid, label, prefix, rel, missing in VIEWS:
        src = ROOT / rel
        title, body, sections = None, "", []
        if src.is_file() and src.read_text(encoding="utf-8").strip():
            if src.suffix == ".json":
                title, body, sections = render_style(src, prefix)
            else:
                title, body, sections = render_markdown(src, prefix)
            if not body.strip():
                body = f'<p class="empty">{esc(missing)}</p>'
        else:
            body = f'<p class="empty">{esc(missing)}</p>'
        title = title or FALLBACK_TITLES.get(vid, label)
        toc = ""
        if vid == DEFAULT_VIEW and sections:
            items = "".join(f'<li><a href="#{sid}">{esc(html.unescape(name))}</a></li>' for sid, name in sections)
            toc = f'<nav class="toc" aria-label="Playbook sections"><p>Sections</p><ol>{items}</ol></nav>'
        nav.append(f'<li><a class="chip" href="#{vid}">{esc(label)}</a></li>')
        views.append(
            f'<section class="view" id="{vid}" aria-labelledby="{vid}-h">\n'
            f'<div class="vhead"><h2 id="{vid}-h">{title}</h2><span class="src">{esc(rel)}</span></div>\n'
            f'{toc}<div class="doc">\n{body}\n</div>\n</section>'
        )

    today = dt.date.today().isoformat()
    n_changes = count_changelog(ROOT / "feedback" / "CHANGELOG.md")
    n_rounds = count_rounds(ROOT / "feedback" / "rounds")
    facts = f"Built {today}, {plural(n_changes, 'change-log entry').replace('entrys', 'entries')}, {plural(n_rounds, 'review round')}"
    footer = ("This page is built from the skill's reference and feedback files by "
              "scripts/build_playbook_page.py. Rebuild it after every playbook change.")

    page = (template
            .replace("<!--SLOT:facts-->", esc(facts))
            .replace("<!--SLOT:nav-->", "".join(nav))
            .replace("<!--SLOT:views-->", "\n".join(views))
            .replace("<!--SLOT:footer-->", esc(footer)))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="folder to write index.html into")
    args = ap.parse_args()
    out = build(args.out)
    print(f"{out}  {out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
