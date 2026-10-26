# Data in the public edition

`normalized/facilities.json` contains 17 fictional records generated specifically for this demo: six emergency departments, eight pharmacies, two community healthcare centres and one community hospital. Names, addresses, coordinates, identifiers and capabilities are illustrative, not real service information. No real contact details or waiting observations are included.

The top-level metadata include `synthetic: true`; each record is also marked synthetic. Backend collectors stay disabled with this catalogue, the poller refuses to start collection, responses carry a demo warning and map navigation is omitted.

`normalized/categories.json` contains the project's category/routing definitions. `scripts/` retains the explicit acquisition and normalization utilities used in the original research workflow; running those utilities contacts external sources. Review source conditions and permissions before doing so.

## What is intentionally absent

- Original source exports and seed files.
- Cached external webpages, live snapshots and source documents.
- SQLite databases, logs and old validation reports.
- The original real-world normalized catalogue and capability CSV.

These remain outside this public edition. The original build used source-specific and curated reference inputs, so the scripts alone are not a complete one-command reconstruction of the original dataset. An authorized real catalogue must be assembled separately, validated against the schema and truthfully identified in its metadata. Changing only the synthetic flag does not make these records real.

See [source feasibility](../docs/FATTIBILITA.md) and [operational notes](../docs/OPERATIVITA.md).
