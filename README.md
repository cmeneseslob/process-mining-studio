# ⚙️ Process Mining Studio

An open-source, interactive process mining web application built with **Streamlit** and **PM4Py** — inspired by commercial tools like [Celonis](https://www.celonis.com/) and [Fluxicon Disco](https://fluxicon.com/disco/).

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-red)
![PM4Py](https://img.shields.io/badge/PM4Py-2.7%2B-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

| View | What it does |
|---|---|
| **🗺️ Discovery** | Directly-Follows Graph (DFG) with Disco-style sliders to control activity and path visibility; toggle between Frequency and Performance (avg. transition time) |
| **🔀 Variants** | All process variants ranked by frequency, with a Pareto chart, cumulative %, and one-click variant isolation that filters the entire dashboard |
| **📊 Performance** | KPI panel (mean/median cycle time, min/max, total cases & events), cycle-time histogram, workload-over-time chart, and per-percentile breakdown |
| **🔧 Advanced Filters** | Date range, case duration range, start/end activity, required activities — all filters propagate to every view |

A built-in **synthetic P2P demo log** (500 cases) lets you explore the app immediately without any data.

---

## Quick Start

### 1. Prerequisites

**Python 3.9+** and the **graphviz system binary** (required for the process map):

```bash
# macOS
brew install graphviz

# Ubuntu / Debian
sudo apt-get install graphviz

# Windows (via Chocolatey)
choco install graphviz
```

### 2. Install & Run

```bash
git clone https://github.com/cmeneseslob/process-mining-studio.git
cd process-mining-studio

pip install -r requirements.txt

streamlit run app.py
```

Or use the helper script:

```bash
./setup_and_run.sh
```

The app opens at **http://localhost:8501**.

---

## Supported Input Formats

| Format | Extension | Notes |
|---|---|---|
| XES | `.xes` | Standard IEEE process mining format; columns mapped automatically |
| CSV | `.csv` | Interactive column mapper for Case ID, Activity, Timestamp, and optional Resource/Cost columns |

---

## Project Structure

```
process-mining-studio/
├── app.py              # Full Streamlit application (~600 lines)
├── requirements.txt    # Python dependencies
├── setup_and_run.sh    # One-command install + launch script
└── README.md
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `pm4py` | Process discovery, variant analysis, filtering, DFG algorithms |
| `streamlit` | Web UI framework |
| `plotly` | Interactive charts (histogram, line, bar) |
| `pandas` / `numpy` | Data manipulation |
| `graphviz` | DFG rendering (Python bindings + system binary) |

---

## Roadmap

- [ ] Petri Net and BPMN discovery (Alpha Miner, Inductive Miner)
- [ ] Conformance checking against a reference model
- [ ] Resource / organizational analysis view
- [ ] Export filtered log as CSV or XES
- [ ] Docker image for zero-setup deployment

---

## License

MIT — see [LICENSE](LICENSE).
