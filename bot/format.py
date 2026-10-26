"""Formattazione dei messaggi (HTML). Corti: una riga per informazione. Solo dati del backend, mai 'qualità'."""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import TZ
from .keyboards import PRESET_LABEL, PRESET_SHORT

TYPE_ICON = {"emergency_room": "🏥", "community_house": "🏠", "community_hospital": "🏠", "pharmacy": "💊"}
TYPE_LABEL = {"emergency_room": "Pronto Soccorso", "community_house": "Case della Comunità",
              "community_hospital": "Ospedali di Comunità", "pharmacy": "Farmacie"}
CAP_LABEL = {"orthopedics_trauma": "ortopedia", "pediatrics": "pediatria", "ophthalmology": "oculistica", "ent": "otorino",
             "obstetrics_gynecology": "ostetricia", "trauma_network": "rete trauma", "pediatric_emergency_room": "PS pediatrico",
             "community_house_dm77": "CdC", "pharmacy": "farmacia"}
TREND = {"increasing": "📈 in aumento", "decreasing": "📉 in calo", "stable": "➡️ stabile"}

FOOTER = "<i>Non è una diagnosi. Emergenza → 112 · consiglio → 116117</i>"
MSG_112 = ("🚨 <b>Chiama subito il 112.</b>\n"
           "Dolore al petto, fatica a respirare, svenimento, sangue che non si ferma, difficoltà a parlare o muovere un lato, "
           "convulsioni: non aspettare.\nLazioFlow non gestisce le emergenze.")
MSG_116117 = "🩺 <b>116117</b>: consiglio sanitario non urgente, gratuito, 24h, con operatori sanitari."
MSG_VISITA = ("📅 Visite ed esami si prenotano con la ricetta al <b>ReCUP 06 9939</b> o su salutelazio.it.\n"
              "Vuoi la Casa della Comunità più vicina (PUA, prelievi, infermiere)?")
MSG_WELCOME = ("👋 Sono <b>LazioFlow</b>: ti mostro le <b>strutture sanitarie vicine</b> nel Lazio, con i dati sulle attese dei Pronto Soccorso quando disponibili.\n\n"
               "Prima del testo libero leggi /privacy: se l’AI è attiva il testo viene inviato al provider configurato. "
               "Non inserire nomi o documenti. Puoi usare i pulsanti senza inviare testo all’AI.\n\n" + FOOTER)


def _t(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(ts).astimezone(ZoneInfo(TZ)).strftime("%H:%M")
    except ValueError:
        return ts


def e(s) -> str:
    return html.escape(str(s), quote=False) if s is not None else ""


def fmt_km(km: float) -> str:
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km".replace(".", ",")


CATEGORY_SHORT = {"FARMACIA": "Farmacia", "ASSISTENZA_TERRITORIALE": "Casa della Comunità", "TRAUMA_MINORE": "Disturbo muscolo-scheletrico",
                  "PEDIATRICO": "Bambino/a", "OCCHIO": "Occhio", "ORECCHIO_NASO_GOLA": "Orecchio, naso, gola", "GRAVIDANZA": "Gravidanza / ginecologia",
                  "DENTI": "Denti", "PROBLEMA_GENERICO_NON_URGENTE": "Sintomi da chiarire"}


def category_short(cat_id: str, facility_type: str | None = None) -> str:
    if cat_id == "PROBLEMA_GENERICO_NON_URGENTE" and facility_type == "emergency_room":
        return "Pronto Soccorso"
    return CATEGORY_SHORT.get(cat_id, cat_id)


def _short_name(r: dict) -> str:
    return r["name"].replace("Pronto Soccorso ", "").replace("Casa della Comunità ", "").replace("Ospedale di Comunità ", "OdC ")


def card(r: dict) -> str:
    """Nome, indirizzo, distanza e stato; ogni dato live mantiene la sua ora."""
    sc, lv, tr = r.get("score") or {}, r.get("live") or {}, r.get("trend") or {}
    lines = [f"<b>{r['rank']}. {e(_short_name(r))}</b> · {e(fmt_km(r['distance_km']))}"]
    if r.get("address"):
        lines.append(f"📍 {e(r['address'])}")
    if r["type"] == "emergency_room":
        if lv.get("available"):
            w = lv.get("total_waiting")
            s = f"🚗 {sc.get('travel_minutes')} min · 👥 {w} in attesa"
            if lv.get("observed_wait_code"):
                s += f" · attesa massima osservata codice {lv.get('observed_wait_code')}: ~{lv.get('observed_wait_minutes')} min"
            if tr.get("direction") == "increasing":
                s += " · 📈"
            elif tr.get("direction") == "decreasing":
                s += " · 📉"
            if lv.get("freshness") == "stale":
                s += " · ⚠️ dato vecchio"
            if lv.get("data_timestamp"):
                s += f" · dato delle {e(_t(lv['data_timestamp']))}"
            lines.append(s)
        else:
            lines.append(f"🚗 {sc.get('travel_minutes')} min · 👥 dato non disponibile")
        if r.get("compatibility_confidence") == "verified":
            caps = ", ".join(CAP_LABEL.get(k, k) for k in (r.get("compatibility_sources") or {}))
            lines.append(f"✅ {e(caps)}")
        elif r.get("compatibility_confidence") == "unverified":
            lines.append("⚠️ reparto non verificato qui")
    else:
        op = r.get("opening") or {}
        mark = {"open": "🟢", "closed": "🔴"}.get(op.get("status"), "⚪️")
        lab = op.get("label") or "orario non verificato"
        s = f"🚗 {sc.get('travel_minutes')} min · {mark} {e(lab)}"
        lines.append(s)
        if op.get("retrieved_at"):
            lines.append(f"🕒 {e(op.get('evidence_label', 'Fonte consultata'))}: {e(op['retrieved_at'][:10])} alle {e(_t(op['retrieved_at']))}")
        if op.get("source_url") and op['source_url'].startswith('https://'):
            lines.append(f'<a href="{html.escape(op["source_url"], quote=True)}">Orari e turni: fonte ufficiale</a>')
        if r.get("phone"):
            lines.append(f"☎️ {e(r['phone'])}")
    return "\n".join(lines)


def results_message(res: dict, recs: list[dict], offset: int = 0) -> str:
    pref = res.get("preference", "balanced")
    is_ps = res.get("facility_type") == "emergency_room"
    tlabel = TYPE_LABEL.get(res.get("facility_type"), "")
    order = {"nearest": "i più vicini", "less_crowded": "attesa osservata più breve", "balanced": "dati recenti, poi vicinanza"}.get(pref, "")
    head = f"<b>{tlabel}</b> · " + (order if is_ps else "strutture vicine")
    if offset:
        head += f" · dal {offset + 1}°"
    parts = (["<b>DEMO: strutture fittizie. Non usare per cercare assistenza sanitaria.</b>"] if res.get("synthetic") else []) + [head]
    if not recs:
        parts.append("Non ci sono altre strutture da mostrare." if offset else "Nessuna struttura compatibile trovata nel raggio di ricerca.")
    parts += [card(r) for r in recs]
    foot = (f"🕒 ricerca delle {e(_t(res.get('generated_at')))}" + (" · fonte attese: SaluteLazio" if is_ps and not res.get("synthetic") else "")
            + " · distanze in linea d’aria · 🚗 = viaggio stimato")
    if is_ps:
        foot += " · non è una previsione della tua attesa; dati vecchi esclusi dall’ordinamento"
        foot += " · 👥 = persone in attesa nei codici 3-5; durata massima osservata nel codice indicato"
    parts.append(foot + "\n" + FOOTER)
    return "\n\n".join(parts)


def why_message(res: dict, recs: list[dict], explanation: dict | None) -> str:
    pref = res.get("preference", "balanced")
    is_ps = res.get("facility_type") == "emergency_room"
    parts = ([f"<b>Perché questo ordine</b> ({PRESET_LABEL.get(pref)}: {PRESET_SHORT.get(pref)})",
              "Prima il tipo di struttura e la compatibilità del reparto, poi il criterio selezionato: "
              f"{PRESET_SHORT.get(pref, 'viaggio e attesa separati')}. L'attesa osservata non è una previsione della tua attesa."]
             if is_ps else ["<b>Perché questo ordine</b>",
                            "Le strutture sono ordinate per vicinanza, tenendo conto delle aperture note. "
                            "Se gli orari non sono verificati, chiama prima di andare."])
    if explanation and explanation.get("generator") == "llm" and explanation.get("text"):
        parts.append(e(explanation["text"]))
    for r in recs:
        parts.append(f"<b>#{r['rank']} {e(_short_name(r))}</b>\n" + "\n".join("• " + e(x) for x in (r.get("reasons", []) + r.get("warnings", []))[:5]))
    return "\n\n".join(parts)


def rete_message(live: dict) -> str:
    items = live.get("items", [])
    ok = [i for i in items if i.get("total_waiting") is not None]
    tot = sum(i["total_waiting"] for i in ok)
    top = sorted(ok, key=lambda i: -(i["total_waiting"] or 0))[:5]
    lines = [f"<b>Rete PS Lazio</b> · {len(ok)}/{len(items)} PS con dato"]
    lines.append(f"{tot} persone in attesa (codici 3-5). Più pressione nei dati disponibili:" if ok else "Dati sulle attese al momento non disponibili.")
    for i in top:
        tr = TREND.get((i.get("trend") or {}).get("direction"), "")
        wait = i.get("observed_wait_minutes")
        wait_label = f"~{wait} min" if wait is not None else "tempo non disponibile"
        freshness = " · ⚠️ dato vecchio" if i.get("freshness") == "stale" else ""
        lines.append(f"• {e(i['name'].replace('Pronto Soccorso ', ''))}: {i['total_waiting']} · {wait_label} {tr.split(' ')[0]}{freshness}")
    lines.append(f"<i>Ricerca delle {e(_t(live.get('generated_at')))} · SaluteLazio · pressione osservata, non qualità</i>")
    return "\n".join(lines)


def info_message(src: dict) -> str:
    lines = ["<b>Fonti</b>"]
    for s in src.get("sources", []):
        lines.append(f"• {e(s['name'])}: {e(s['what'])}")
    lines.append("\n<b>Limiti</b>")
    lines += ["• " + e(x) for x in src.get("limits", [])]
    lines.append("\n" + FOOTER)
    return "\n".join(lines)


def coverage_message(report: dict) -> str:
    lines = ['<b>Copertura LazioFlow</b>', 'Catalogo e dati aggiornati sono distinti.']
    for row in report.get('provinces', []):
        catalog, ph, cdc = row['catalog'], row['pharmacies'], row['community_houses']
        lines.append(f"\n<b>{e(row['name'])}</b>: {catalog['emergency_rooms']} PS, {catalog['community_houses']} CdC, {catalog['pharmacies']} farmacie.")
        lines.append(f"CdC: {cdc['regional_cards_matched']} schede regionali associate; {cdc['service_hours_matched']} con informazioni sugli orari dei servizi.")
        lines.append(f"Farmacie: {ph['known_open']} con apertura pubblicata valida adesso; {ph['published_shift_now']} indicate in turno (anche a chiamata).")
        if row['code'] != 'RM':
            state = 'consultati di recente' if ph.get('fresh') else 'aggiornamento non disponibile'
            lines.append(f"Calendari: {ph['documents']} documenti, {state}.")
        url = ph.get('source_url')
        if url and url.startswith('https://'):
            lines.append(f'<a href="{html.escape(url, quote=True)}">Turni ufficiali: {e(row["name"])}</a>')
    lines.append('\nOrari incompleti e modifiche improvvise restano possibili. Verifica con la farmacia o con la sede prima di partire.')
    lines.append('I numeri indicano la copertura delle fonti, non tutte le strutture effettivamente aperte.')
    return '\n'.join(lines)
