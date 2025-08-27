import streamlit as st
import pandas as pd
import unicodedata
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from PyPDF2 import PdfMerger
import tempfile
import os

# === Paramètres fixes (en-têtes facture) ===
FACTURE_EMETTEUR = """<b>Émetteur :</b><br/>
Wesley MARSTON<br/>
5 clairière des vernedes<br/>
83480 Puget sur Argens"""

FACTURE_CLIENT = """<b>Facture à :</b><br/>
ALKERN France<br/>
Rue André Bigotte<br/>
Z.I. Parc de la motte au bois<br/>
62440 Harnes"""

IMMATRICULATION = "Scenic HD-803-PZ"

# === Utilitaires robustes ===
def normalize_txt(x: str) -> str:
    if x is None:
        return ""
    x = str(x)
    x = x.replace("\xa0", " ")  # NBSP -> space
    x = "".join(c for c in unicodedata.normalize("NFKD", x) if not unicodedata.combining(c))
    return x.strip().lower()

def read_csv_safely(uploaded_file):
    # Essai 1: virgule + guillemets
    try:
        df = pd.read_csv(uploaded_file, sep=",", quotechar='"', encoding="utf-8")
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    uploaded_file.seek(0)
    # Essai 2: point-virgule
    try:
        df = pd.read_csv(uploaded_file, sep=";", encoding="utf-8")
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    uploaded_file.seek(0)
    # Essai 3: auto-détection
    try:
        df = pd.read_csv(uploaded_file, engine="python")
        return df
    except Exception:
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file)

def find_column(cols, *keywords):
    cols_norm = {normalize_txt(c): c for c in cols}
    for key in keywords:
        k = normalize_txt(key)
        for cnorm, corig in cols_norm.items():
            if k in cnorm:
                return corig
    return None

def get_tarifs(date):
    seuil = datetime(2025, 8, 1)
    if date >= seuil:
        return {"HC": 0.1635, "HP": 0.2081}
    else:
        return {"HC": 0.1696, "HP": 0.2146}

def is_hc(time):
    # Heures creuses: 00:06–06:06 et 15:06–17:06
    minutes = time.hour * 60 + time.minute
    return (6 <= minutes < 366) or (906 <= minutes < 1026)

def compute_cost(start, end, kWh_total):
    if kWh_total <= 0 or pd.isna(start) or pd.isna(end) or start == end:
        return 0.0, 0.0, 0.0
    duration_sec = (end - start).total_seconds()
    if duration_sec <= 0:
        return 0.0, 0.0, 0.0
    kWh_per_sec = kWh_total / duration_sec
    kWh_hc = 0.0
    kWh_hp = 0.0
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(minutes=1), end)
        secs = (nxt - cur).total_seconds()
        kwh_chunk = kWh_per_sec * secs
        if is_hc(cur.time()):
            kWh_hc += kwh_chunk
        else:
            kWh_hp += kwh_chunk
        cur = nxt
    t = get_tarifs(start)
    cost = kWh_hc * t["HC"] + kWh_hp * t["HP"]
    return kWh_hc, kWh_hp, cost

def generate_facture(df, annexe_file, mois_selection, vehicule_value, cols):
    col_start, col_end, col_energy, col_auth = cols

    # Nettoyage / conversions
    df[col_start] = pd.to_datetime(df[col_start], errors="coerce")
    df[col_end] = pd.to_datetime(df[col_end], errors="coerce")

    # énergies en Wh -> float
    df[col_energy] = pd.to_numeric(df[col_energy], errors="coerce")

    # Filtre véhicule & énergie > 0
    auth_norm = df[col_auth].astype(str).apply(normalize_txt)
    veh_norm = normalize_txt(vehicule_value)
    mask_vehicle = auth_norm.str.contains(veh_norm, na=False)
    dfv = df[mask_vehicle & (df[col_energy] > 0)].copy()

    # Filtre mois YYYY-MM
    dfv["YYYY-MM"] = dfv[col_start].dt.strftime("%Y-%m")
    dfv = dfv[dfv["YYYY-MM"] == mois_selection]

    if dfv.empty:
        return None

    # kWh
    dfv["kWh"] = dfv[col_energy] / 1000.0

    sessions = []
    total_HT = 0.0
    for _, row in dfv.iterrows():
        kwh_hc, kwh_hp, cost = compute_cost(row[col_start], row[col_end], row["kWh"])
        sessions.append({
            "date": row[col_start].strftime("%d/%m/%Y") if not pd.isna(row[col_start]) else "",
            "debut": row[col_start].strftime("%Hh%M") if not pd.isna(row[col_start]) else "",
            "fin": row[col_end].strftime("%Hh%M") if not pd.isna(row[col_end]) else "",
            "duree": str(row[col_end] - row[col_start]) if (not pd.isna(row[col_end]) and not pd.isna(row[col_start])) else "",
            "kWh_total": row["kWh"],
            "kWh_HC": kwh_hc,
            "kWh_HP": kwh_hp,
            "tarif_HC": get_tarifs(row[col_start])["HC"] if not pd.isna(row[col_start]) else get_tarifs(datetime.now())["HC"],
            "tarif_HP": get_tarifs(row[col_start])["HP"] if not pd.isna(row[col_start]) else get_tarifs(datetime.now())["HP"],
            "cout": cost
        })
        total_HT += cost

    total_kWh = sum(s["kWh_total"] for s in sessions)
    tva = total_HT * 0.20
    total_TTC = total_HT + tva

    # Génération facture (page 1)
    tmpdir = tempfile.mkdtemp()
    facture_file = os.path.join(tmpdir, f"facture_{mois_selection}.pdf")
    doc = SimpleDocTemplate(facture_file, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>FACTURE DE RECHARGE VEHICULE ELECTRIQUE</b>", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(FACTURE_EMETTEUR, styles["Normal"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(FACTURE_CLIENT, styles["Normal"]))
    elements.append(Spacer(1, 24))

    elements.append(Paragraph(f"<b>Facture n°:</b> {mois_selection}-{vehicule_value}<br/>"
                              f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}<br/>"
                              f"<b>Période :</b> {mois_selection}<br/>"
                              f"<b>Véhicule :</b> {IMMATRICULATION}", styles["Normal"]))
    elements.append(Spacer(1, 24))

    # Tableau
    table_data = [["Date", "Début", "Fin", "Durée", "kWh total", "kWh HC", "kWh HP", "Tarif HC", "Tarif HP", "Montant (€)"]]
    for s in sessions:
        table_data.append([s["date"], s["debut"], s["fin"], s["duree"],
                           f"{s['kWh_total']:.2f}", f"{s['kWh_HC']:.2f}", f"{s['kWh_HP']:.2f}",
                           f"{s['tarif_HC']:.4f}", f"{s['tarif_HP']:.4f}", f"{s['cout']:.2f}"])
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 24))

    # Récap
    recap = [
        ["Total énergie consommée", f"{total_kWh:.2f} kWh"],
        ["Total HT", f"{total_HT:.2f} €"],
        ["TVA (20%)", f"{tva:.2f} €"],
        ["Total TTC", f"{total_TTC:.2f} €"],
    ]
    recap_table = Table(recap, colWidths=[220, 120])
    recap_table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.black)]))
    elements.append(recap_table)
    elements.append(Spacer(1, 24))

    mentions = """Facture générée automatiquement à partir du compteur certifié MID<br/>
<b>Enphase IQ-EVSE-EU-3032</b> – Conforme aux directives MID, LVD, EMC, RED, RoHS"""
    elements.append(Paragraph(mentions, styles["Normal"]))

    doc.build(elements)

    # Annexes
    final_pdf = os.path.join(tmpdir, f"facture_complete_{mois_selection}.pdf")
    merger = PdfMerger()
    merger.append(facture_file)
    if annexe_file is not None:
        merger.append(annexe_file)
    merger.write(final_pdf)
    merger.close()

    return final_pdf

# === Interface Streamlit ===
st.title("🔌 Générateur de Factures de Recharge VE")

uploaded_csv = st.file_uploader("Déposez votre fichier CSV de sessions", type=["csv"])
uploaded_annexe = st.file_uploader("Déposez la Déclaration de Conformité Enphase (PDF)", type=["pdf"])

if uploaded_csv is not None:
    df = read_csv_safely(uploaded_csv)

    st.subheader("🗂️ Colonnes détectées dans le fichier CSV")
    st.write(list(df.columns))

    # Recherche intelligente des colonnes
    col_start = find_column(df.columns, "date/heure de debut", "début", "start", "begin")
    col_end = find_column(df.columns, "date/heure de fin", "fin", "end")
    col_energy = find_column(df.columns, "energie", "énergie", "wh", "kwh")
    col_auth = find_column(df.columns, "authentification", "badge", "rfid", "vehicule", "véhicule")

    missing = [name for name, col in [
        ("Date/heure de début", col_start),
        ("Date/heure de fin", col_end),
        ("Énergie consommée (Wh)", col_energy),
        ("Authentification", col_auth),
    ] if col is None]

    if missing:
        st.error("Colonnes manquantes/non reconnues : " + ", ".join(missing))
    else:
        # Normaliser Authentification pour détecter les valeurs uniques
        auth_values = df[col_auth].dropna().astype(str).apply(lambda x: x.replace("\xa0"," ").strip())
        uniques = sorted(auth_values.unique().tolist())

        st.subheader("🚗 Sélection du véhicule / badge")
        default_idx = 0
        for i, v in enumerate(uniques):
            if normalize_txt("scenic") in normalize_txt(v):
                default_idx = i
                break
        vehicule_value = st.selectbox("Choisissez le véhicule à facturer :", options=uniques, index=default_idx)

        # Construire la liste des mois disponibles dans les données
        df_dates = pd.to_datetime(df[col_start], errors="coerce")
        mois_dispo = sorted(df_dates.dt.strftime("%Y-%m").dropna().unique().tolist())
        default_month = mois_dispo[-1] if mois_dispo else datetime.now().strftime("%Y-%m")
        mois_selection = st.selectbox("Mois de consommation (YYYY-MM)", options=mois_dispo or [default_month], index=(len(mois_dispo)-1) if mois_dispo else 0)

        # Aperçu sessions du véhicule choisi (toutes, même 0 Wh)
        st.subheader("🔎 Aperçu des sessions du véhicule sélectionné (toutes)")
        auth_norm = df[col_auth].astype(str).apply(normalize_txt)
        mask_vehicle = auth_norm.str.contains(normalize_txt(vehicule_value), na=False)
        st.dataframe(df.loc[mask_vehicle, [col_start, col_end, col_energy, col_auth]].head(50))

        if uploaded_annexe is not None and st.button("📄 Générer la facture"):
            output_pdf = generate_facture(df, uploaded_annexe, mois_selection, vehicule_value, (col_start, col_end, col_energy, col_auth))
            if output_pdf is None:
                st.error("⚠️ Aucune session trouvée pour ce mois et ce véhicule avec énergie > 0.")
            else:
                with open(output_pdf, "rb") as f:
                    st.download_button("⬇️ Télécharger la facture PDF", f, file_name=os.path.basename(output_pdf))
