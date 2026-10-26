# Source feasibility and limitations

The original project investigated whether heterogeneous public-facing healthcare sources could support explicit facility navigation without predicting clinical outcomes. The public edition preserves the integration code but includes only synthetic facilities.

| Integration | Intended information | Main limitation |
|---|---|---|
| SaluteLazio | Facility descriptions and emergency-department observations | Changing API formats, incomplete coverage and source terms. |
| Ministry of Health datasets | Facilities, disciplines and pharmacy registry | Periodic updates, source-specific licences and imperfect joins. |
| Regional planning documents | Structural capability references | Curated interpretation is needed; this does not establish availability now. |
| ASL and community-care pages | Published site/service hours | Service hours are not equivalent to the opening of an entire facility. |
| Pharmacy orders | Published shifts, contacts and opening lists | Provincial formats differ; on-call duty does not guarantee an open door. |

Links: [SaluteLazio](https://salutelazio.it), [SaluteLazio legal notice](https://salutelazio.it/it/note-legali), [Ministry of Health datasets](https://www.dati.salute.gov.it/), [Regione Lazio](https://www.regione.lazio.it), [Rome pharmacy order](https://www.ordinefarmacistiroma.it).

Public access is not a blanket redistribution licence. Obtain the applicable permission or dataset licence before downloading for a new purpose or publishing source copies and derived records. No third-party source exports or webpage caches are bundled here.

Ranking compatibility is a reproducible software rule, not clinical assessment. Travel uses declared geometric assumptions; observed waiting time is not a prediction. Missing data and ambiguous source matches must remain explicit. The synthetic demo does not validate any real facility's capabilities or opening hours.
