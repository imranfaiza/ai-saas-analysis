"""Labeling screen: your answer key for the eval.

Run from the repo root:
    streamlit run ai/label_app.py
"""

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LABEL_TICKERS, LABELS_CSV, QUESTIONS, latest_10k_text, read_csv, write_csv  # noqa: E402

st.set_page_config(page_title="Label filings", layout="wide")

labels = {r["ticker"]: r for r in read_csv(LABELS_CSV)}
done = [t for t in LABEL_TICKERS if t in labels]

st.title("Label 10-K margin text")
st.caption("Answer from the text only. Don't look at any AI answers first: this is the answer key.")
st.progress(len(done) / len(LABEL_TICKERS), text=f"{len(done)} of {len(LABEL_TICKERS)} companies labeled")

default = next((i for i, t in enumerate(LABEL_TICKERS) if t not in labels), 0)
ticker = st.selectbox(
    "Company",
    LABEL_TICKERS,
    index=default,
    format_func=lambda t: f"{t}  ✓" if t in labels else t,
)
path, text = latest_10k_text(ticker)

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader(path.stem.replace("_", " "))
    search = st.text_input("Highlight a word (e.g. AI, gross margin, hosting)", "")
    shown = text
    if search.strip():
        import re

        shown = re.sub(f"({re.escape(search.strip())})", r"**:orange[\1]**", text, flags=re.I)
    with st.container(height=700):
        st.markdown(shown)

with right:
    st.subheader("Your answers")
    current = labels.get(ticker, {})
    with st.form(f"form_{ticker}"):
        answers = {}
        for key, q in QUESTIONS.items():
            opts = list(q["options"])
            answers[key] = st.radio(
                q["prompt"],
                opts,
                index=opts.index(current[key]) if current.get(key) in opts else None,
                format_func=lambda o, q=q: q["options"][o],
                key=f"{ticker}_{key}",
            )
        note = st.text_input("Note (optional)", current.get("note", ""))
        if st.form_submit_button("Save", type="primary"):
            if any(v is None for v in answers.values()):
                st.error("Answer all three questions first.")
            else:
                labels[ticker] = {"ticker": ticker, **answers, "note": note,
                                  "labeled_at": datetime.now().isoformat(timespec="seconds")}
                rows = [labels[t] for t in LABEL_TICKERS if t in labels]
                write_csv(LABELS_CSV, rows, ["ticker", *QUESTIONS, "note", "labeled_at"])
                st.toast(f"Saved {ticker}")
                st.rerun()

    with st.expander("How to decide"):
        st.markdown(
            "- **AI cost pressure:** *reported* only if the company says AI costs actually moved "
            "its cost of revenue or margin. Risk-factor language (\"may\", \"could\") is *risk_only*.\n"
            "- **Main cost driver:** look in MD&A for \"Cost of revenue increased ... primarily due to\" "
            "and pick the first or largest item.\n"
            "- **AI revenue:** *yes* if they sell AI products/features (e.g. paid AI add-ons, AI SKUs)."
        )
