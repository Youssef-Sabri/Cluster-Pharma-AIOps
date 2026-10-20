# ClusterOps: MVP Project Idea

**Goal:** a portfolio project to show the Cluster co-founder I can work as an AI / AIOps Engineer on their team.
**Data:** synthetic only. I will not claim anything about Cluster's real data or systems.

---

## 1. About Cluster (from their website and public profiles)

- B2B platform that digitizes pharmaceutical procurement in emerging markets, starting with Egypt.
- Connects pharmacies, suppliers and wholesalers. Features include AI "Best Prices", auctions/bidding, price lists, a supplier dashboard and an AI module for shortages.
- AI model "Clara" processes pharmaceutical orders in seconds.
- Roadmap (VC4A profile): procurement automation, a Peer-to-Peer Virtual Chain, an Intelligence Hub (demand forecasting, price benchmarks, analytics) and a Digital Twin of the pharma supply chain.
- 11-50 employees, founded 2023, based in Giza. Small team that builds in-house.

## 2. The idea

Cluster already has AI in production. The hard part of AI at scale is keeping it **monitored, retrainable and safe to change**. That is what an AIOps role does.

**ClusterOps** is a small platform that wraps two Cluster-style models with an operations layer:

1. **Demand forecasting:** predicts which medicines a pharmacy will run out of, so it can reorder in time (the Intelligence Hub use case).
2. **Order matching (Clara-style):** turns messy text like "10 panadol and 5 augmentn" into catalogue items, with a confidence score and human review for uncertain matches.
3. **Operations layer:** drift detection, automated retraining with a promotion gate, and monitoring dashboards.

## 3. MVP scope

| Part | What the MVP does | Success measure |
|---|---|---|
| Synthetic data | Generates orders, prices and a drug catalogue, plus a "demand shock" mode | Realistic Egyptian drug names and EGP prices |
| Forecast model | Predicts next-day demand per product | Beats a naive baseline (target: 15%+ lower error) |
| Order matcher | Fuzzy match first, then embeddings/LLM re-ranker | Accuracy on a golden set of 100+ messy orders |
| Drift detection | Compares new data to training data and raises an alarm | Detects the simulated demand shock |
| Retraining pipeline | Trains a challenger, compares with the current model, promotes only if better | No worse model reaches production |
| API | `/forecast`, `/match-order`, `/health`, `/metrics` | p95 latency under 500 ms |
| Dashboard | Request rate, latency, prediction distribution, low-confidence rate | Alerts fire on drift or errors |

**Out of scope for the MVP:** real user accounts, payments, a mobile app, real Cluster data.

## 4. Suggested tech stack

- **Python, pandas, scikit-learn / LightGBM:** forecasting
- **rapidfuzz + multilingual embeddings (e.g. multilingual-e5) and/or an LLM:** order matching
- **FastAPI:** serving
- **MLflow:** experiment tracking and model registry
- **Prometheus + Grafana:** monitoring
- **Docker + GitHub Actions:** packaging and CI
- **Prefect / Airflow / cron:** scheduled retraining
- **pytest:** tests

## 5. Architecture

```
synthetic orders -> feature pipeline -> train -> MLflow registry -> FastAPI
                          |                                          |
                    reference data                             Prometheus -> Grafana
                          |
new data -> drift check -> drift found? -> train challenger -> compare -> promote or reject
```

## 6. Build plan

**Phase 1: Data and baseline (days 1-3)**
- Generate synthetic data with weekly seasonality, trend and a demand-shock option.
- Build a naive baseline (same day last week) and log its error.

**Phase 2: Forecast model (days 4-6)**
- Features: lags, rolling averages, day of week, holidays/Ramadan.
- Time-based train/test split (never random).
- Per-product error table and prediction intervals.

**Phase 3: Order matcher (days 7-9)**
- Build the golden set: English, Arabic, Franco-Arabic, typos, brand vs generic names.
- Measure the fuzzy baseline, then add embeddings or an LLM re-ranker.
- Track accuracy, latency and cost per order.

**Phase 4: AIOps layer (days 10-12)**
- Drift detection (PSI or similar) with thresholds.
- Scheduled job: drift found, train a challenger, compare, promote or reject.
- Rollback if live error rises.

**Phase 5: Serving and monitoring (days 13-14)**
- FastAPI endpoints with Prometheus metrics.
- Grafana dashboard and alerts.
- Docker Compose to run everything locally.

**Phase 6: Polish & Verification**
- Deploy services with Docker Compose and verify healthchecks.
- Execute full integration test suite and load benchmarks.
- Document manual verification procedures and architecture decisions.

## 7. End-to-End Verification & Technical Walkthrough

1. **Problem Context**: pharmacies run out of stock, models go stale, procurement is manual.
2. **Model Training & Registry**: LightGBM beats naive baseline, registered with tags in MLflow.
3. **Clara Order Matching**: live fuzzy/LLM parsing of bilingual Egyptian pharmacy orders.
4. **Drift Detection**: synthetic volume shock triggers the PSI >= 0.20 alarm.
5. **Retraining & Promotion Gate**: Prefect retraining flow promotes challenger only if MAE improves by >= 3%.
6. **Observability**: Prometheus & Grafana monitor request rates, p95 latency (<500ms), and match confidence.
7. **Closing Discussion**: "With real order and ERP data, the first thing I would do is calibrate the fuzzy threshold against catalogue size and historical volume patterns."

## 8. Interview talking points

- Why compare against a naive baseline: a complex model that cannot beat it is not worth deploying.
- Why a time-based split: random splits leak the future in time series.
- Why one shared feature function for training and serving: it prevents training/serving skew.
- Why human review for low-confidence matches: pharma orders need a safe fallback.
- What LLM matching costs per order, and where it is worth it versus fuzzy matching.

## 9. Honesty rules

- Say it is a prototype on synthetic data.
- Be able to explain every line and every metric.
- Do not claim Cluster's real numbers, systems or internal architecture.
- Offer to adapt it to their real data as a first task on the team.
