"""Chart rendering: plant-wise and Top-10-Buyer bar charts, as PNG bytes.

Per `spec/architecture.md -> Chart Rendering`: `matplotlib.use("Agg")` is set
before `pyplot` is imported (mandatory on a headless server), charts are
rendered to an in-memory `io.BytesIO()` at `dpi=150` with `bbox_inches="tight"`,
and are NEVER written to disk.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use("Agg"))

_TOP_BUYERS = 10


def _sorted_descending(totals: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def render_plant_chart(plant_totals_crore: dict[str, float], period_label: str) -> bytes:
    """Vertical bar chart, one bar per Plant, sorted descending by ₹-Crore value.

    Title: "Plant-wise GR Value (₹ Crore) — {period}"; y-axis "₹ Crore"; a
    2-decimal value label is drawn above each bar.
    """
    items = _sorted_descending(plant_totals_crore)
    labels = [name for name, _ in items]
    values = [value for _, value in items]

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 5))
    bars = ax.bar(labels, values, color="#2563eb")
    ax.set_title(f"Plant-wise GR Value (₹ Crore) — {period_label}")
    ax.set_ylabel("₹ Crore")
    ax.tick_params(axis="x", rotation=30)

    for bar, value in zip(bars, values):
        ax.annotate(
            f"{value:.2f}",
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
        )

    return _figure_to_png_bytes(fig)


def render_buyer_chart(buyer_totals_crore: dict[str, float], period_label: str) -> bytes:
    """Horizontal bar chart, exactly the top 10 buyers, descending top-to-bottom.

    Title: "Top 10 Buyers by GR Value (₹ Crore) — {period}".
    """
    items = _sorted_descending(buyer_totals_crore)[:_TOP_BUYERS]
    # Reverse so the highest value renders at the TOP of a horizontal barh
    # (matplotlib draws horizontal bars bottom-to-top by category order).
    items_bottom_up = list(reversed(items))
    labels = [name for name, _ in items_bottom_up]
    values = [value for _, value in items_bottom_up]

    fig, ax = plt.subplots(figsize=(8, max(4, len(labels) * 0.5)))
    bars = ax.barh(labels, values, color="#16a34a")
    ax.set_title(f"Top 10 Buyers by GR Value (₹ Crore) — {period_label}")
    ax.set_xlabel("₹ Crore")

    for bar, value in zip(bars, values):
        ax.annotate(
            f"{value:.2f}",
            xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(3, 0),
            textcoords="offset points",
            ha="left",
            va="center",
        )

    return _figure_to_png_bytes(fig)


def _figure_to_png_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)
