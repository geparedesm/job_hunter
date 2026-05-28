"""Styling helpers for the Streamlit cyberpunk dashboard."""

from __future__ import annotations

import streamlit as st


def apply_global_styles() -> None:
    """Inject the dashboard-wide cyberpunk style system."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Space+Mono:wght@400;700&display=swap');

        :root {
            --bg: #030712;
            --bg-soft: #06101f;
            --panel: rgba(5, 10, 20, 0.92);
            --panel-alt: rgba(8, 17, 28, 0.94);
            --border: rgba(74, 222, 128, 0.18);
            --text: #d1fae5;
            --muted: #86efac;
            --green: #7cffb2;
            --cyan: #67e8f9;
            --purple: #a78bfa;
            --yellow: #facc15;
            --red: #fb7185;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(34, 197, 94, 0.16), transparent 26rem),
                radial-gradient(circle at top right, rgba(103, 232, 249, 0.12), transparent 28rem),
                radial-gradient(circle at bottom center, rgba(167, 139, 250, 0.10), transparent 30rem),
                linear-gradient(180deg, #020617 0%, #04111d 55%, #020617 100%);
            color: var(--text);
        }

        .block-container {
            max-width: 1440px;
            padding-top: 1.4rem;
            padding-bottom: 2rem;
        }

        html, body, [class*="css"], [data-testid="stSidebar"], .stMarkdown, .stCodeBlock {
            font-family: "Space Mono", monospace;
        }

        h1, h2, h3 {
            font-family: "Orbitron", sans-serif !important;
            letter-spacing: 0.05em;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(4, 7, 16, 0.98), rgba(7, 17, 29, 0.98));
            border-right: 1px solid var(--border);
        }

        [data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(5, 10, 20, 0.95), rgba(4, 10, 16, 0.92));
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 0.8rem 0.95rem;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22), inset 0 0 0 1px rgba(16, 185, 129, 0.04);
        }

        [data-testid="stMetricLabel"] {
            color: var(--cyan);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 0.72rem;
        }

        [data-testid="stMetricValue"] {
            color: var(--green);
        }

        .stButton > button,
        .stDownloadButton > button {
            background: linear-gradient(180deg, rgba(6, 78, 59, 0.35), rgba(5, 46, 34, 0.42));
            color: var(--text);
            border: 1px solid rgba(74, 222, 128, 0.28);
            border-radius: 14px;
            font-weight: 700;
            min-height: 2.7rem;
            box-shadow: 0 0 18px rgba(16, 185, 129, 0.08);
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: rgba(103, 232, 249, 0.35);
            box-shadow: 0 0 22px rgba(103, 232, 249, 0.10);
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.45rem;
            flex-wrap: wrap;
        }

        .stTabs [data-baseweb="tab"] {
            background: rgba(5, 10, 20, 0.82);
            border: 1px solid rgba(74, 222, 128, 0.14);
            border-radius: 12px;
            color: #bbf7d0;
        }

        .stTabs [aria-selected="true"] {
            background: rgba(6, 78, 59, 0.34) !important;
            border-color: rgba(103, 232, 249, 0.38) !important;
            color: #ecfeff !important;
        }

        .stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input {
            background: rgba(5, 10, 20, 0.92);
            color: var(--text);
            border-radius: 12px;
        }

        .hero-card, .terminal-card {
            background: linear-gradient(180deg, rgba(5, 10, 20, 0.93), rgba(5, 12, 18, 0.96));
            border: 1px solid var(--border);
            border-radius: 22px;
            box-shadow: 0 24px 44px rgba(0, 0, 0, 0.26), inset 0 0 0 1px rgba(16, 185, 129, 0.04);
        }

        .hero-card {
            padding: 1.2rem 1.35rem;
            position: relative;
            overflow: hidden;
        }

        .hero-card::before {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(90deg, transparent 0%, rgba(103, 232, 249, 0.05) 50%, transparent 100%);
            transform: translateX(-100%);
            animation: scanline 7s linear infinite;
        }

        .terminal-card {
            padding: 1rem 1.05rem;
            margin-bottom: 1rem;
        }

        .compact-card {
            margin-top: 1rem;
            margin-bottom: 0.55rem;
            padding-top: 0.85rem;
            padding-bottom: 0.85rem;
        }

        .eyebrow {
            color: var(--cyan);
            text-transform: uppercase;
            font-size: 0.76rem;
            letter-spacing: 0.1em;
            font-weight: 700;
        }

        .hero-title {
            color: #d9f99d;
            font-size: 2rem;
            font-weight: 800;
            margin: 0.15rem 0 0.35rem 0;
            text-shadow: 0 0 18px rgba(163, 230, 53, 0.14);
        }

        .terminal-title {
            color: #ecfccb;
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }

        .muted-copy {
            color: var(--muted);
            font-size: 0.92rem;
            line-height: 1.45;
        }

        .chip-row {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-top: 0.7rem;
        }

        .chip {
            border-radius: 999px;
            padding: 0.32rem 0.68rem;
            font-size: 0.84rem;
            font-weight: 700;
            background: rgba(6, 78, 59, 0.45);
            color: #bbf7d0;
            border: 1px solid rgba(74, 222, 128, 0.15);
        }

        .console-line {
            color: #5eead4;
            margin-top: 0.65rem;
            font-size: 0.86rem;
        }

        .status-pill {
            display: inline-block;
            border-radius: 999px;
            padding: 0.25rem 0.6rem;
            font-size: 0.8rem;
            font-weight: 700;
            margin-right: 0.4rem;
            margin-bottom: 0.35rem;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .alert-line {
            border-left: 3px solid var(--cyan);
            padding: 0.65rem 0.8rem;
            margin-bottom: 0.55rem;
            background: rgba(8, 17, 28, 0.72);
            border-radius: 12px;
        }

        .tiny {
            font-size: 0.8rem;
            color: #93c5fd;
        }

        @keyframes scanline {
            from { transform: translateX(-100%); }
            to { transform: translateX(100%); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
