# lab-report-extractor

![Python coverage](https://img.shields.io/badge/python%20coverage-93%25-brightgreen)
![.NET coverage](https://img.shields.io/badge/.NET%20coverage-89%25-brightgreen)

## Testing & coverage

Both CI jobs (`python-ci`, `dotnet-ci`) run their suite with coverage on every push and
gate at a **70% floor** — low enough not to block normal work, there to catch regressions.

- **Python (93%)**: the safety-critical logic (`validate.py`, `transform.py`) is at
  96-100%. See `docs/data-quality-rules.md`.
- **.NET (89%, generated code excluded)**: round-trips `LabReportRepository` through a real
  Postgres (`Testcontainers.PostgreSql`) to prove the owned-entity/JSONB mapping in
  `LabReportDbContext` works, plus `DbInitializer` and the `/documents` endpoints
  end-to-end.