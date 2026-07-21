"""Render a CONSORT-style subject-disposition flowchart (matplotlib PNG) from the
generated disposition table, so §6.1.1 gets a real figure — not a bare table.

Pure Python (matplotlib + Agg), no system binaries. The numbers come from the
grounded disposition table the writer already produces; we only draw them.
"""
from __future__ import annotations

from pathlib import Path

_DISPO_HINTS = ("enrolled", "screen", "exclud", "treat", "discontinu", "complet",
                "withdraw", "lost", "consent")


def find_disposition_rows(blocks: list[dict]) -> list[tuple[str, str, str]] | None:
    """Find the disposition table among a section's blocks; return [(label, N, eyes)]."""
    for b in blocks:
        if b.get("type") != "table":
            continue
        rows = b.get("rows") or []
        if len(rows) < 2:
            continue
        body = rows[1:]
        labels = " ".join((r[0] if r else "").lower() for r in body)
        if not any(h in labels for h in _DISPO_HINTS):
            continue
        out = []
        for r in body:
            label = (r[0] if len(r) > 0 else "").strip()
            n = (r[1] if len(r) > 1 else "").strip()
            eyes = (r[2] if len(r) > 2 else "").strip()
            if label:
                out.append((label, n, eyes))
        return out or None
    return None


def _pick(rows, *keys):
    for label, n, eyes in rows:
        low = label.lower()
        if any(k in low for k in keys):
            return label, n, eyes
    return None


def render_consort(rows: list[tuple[str, str, str]], out_path: Path) -> bool:
    """Draw a vertical CONSORT flow: Enrolled -> Treated -> Completed, with
    Excluded and Discontinued as side boxes. Returns True on success."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except Exception:
        return False

    enrolled = _pick(rows, "enrolled", "consent")
    excluded = _pick(rows, "screen", "exclud")
    treated = _pick(rows, "treat")
    discont = _pick(rows, "discontinu", "withdraw", "lost")
    completed = _pick(rows, "complet")

    def cap(item, fallback):
        if not item:
            return None
        label, n, eyes = item
        line = label
        if n:
            line += f"\nN = {n}"
        if eyes:
            line += f" ({eyes} eyes)"
        return line

    main = [cap(enrolled, "Enrolled"), cap(treated, "Treated"), cap(completed, "Completed")]
    main = [m for m in main if m]
    if len(main) < 2:
        return False

    fig, ax = plt.subplots(figsize=(6.6, 1.9 * len(main) + 0.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 2 * len(main))
    ax.axis("off")

    def box(x, y, text, w=4.2, h=1.1, fc="#eff6ff", ec="#2563eb"):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                     boxstyle="round,pad=0.08", fc=fc, ec=ec, lw=1.4))
        ax.text(x, y, text, ha="center", va="center", fontsize=9.5, wrap=True)

    n = len(main)
    ys = [2 * (n - i) - 1 for i in range(n)]
    for i, (m, y) in enumerate(zip(main, ys)):
        box(3.2, y, m)
        if i > 0:  # arrow from previous main box
            ax.annotate("", xy=(3.2, y + 0.55), xytext=(3.2, ys[i - 1] - 0.55),
                        arrowprops=dict(arrowstyle="-|>", color="#334155", lw=1.4))
    # side boxes: excluded off the first arrow, discontinued off the last arrow
    side = cap(excluded, "Excluded")
    if side and n >= 2:
        my = (ys[0] + ys[1]) / 2
        box(7.4, my, side, w=3.6, h=1.0, fc="#fef2f2", ec="#dc2626")
        ax.annotate("", xy=(5.5, my), xytext=(3.2, my),
                    arrowprops=dict(arrowstyle="-|>", color="#94a3b8", lw=1.2))
    sidd = cap(discont, "Discontinued")
    if sidd and n >= 2:
        my = (ys[-2] + ys[-1]) / 2
        box(7.4, my, sidd, w=3.6, h=1.0, fc="#fffbeb", ec="#b45309")
        ax.annotate("", xy=(5.5, my), xytext=(3.2, my),
                    arrowprops=dict(arrowstyle="-|>", color="#94a3b8", lw=1.2))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True
