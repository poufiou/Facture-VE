import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from PyPDF2 import PdfMerger
import tempfile
import os

# === Paramètres fixes ===
FACTURE_EMETTEUR = """<b>Émetteur :</b><br/>
Wesley MARSTON<br/>
5 clairière des vernedes<br/>
83480 Puget sur Argens"""

FACTURE_CLIENT = """<b>Facture à :</b><br/>
ALKERN France<br/>
Rue André Bigotte<br/>
Z.I. Parc de la motte au bois<br/>
62440 Harnes"""

VEHICULE = "Scenic"
IMMATRICULATION = "Scenic HD-803-PZ"

# === Fonctions utilitaires ===
def get_tarifs(date):
    seuil = datetime(2025, 8, 1)
    if date >= seuil:
        return {"HC": 0.1635, "HP": 0.2081}
    else:
        return {"HC": 0.1696, "HP": 0.2146}

def is_hc(time):
    h, m = time.hour, time.minute
    minutes = h * 60 + m
    return (6 <= minutes < 366) or (906 <= minutes < 1026)  # 00h06–06h06 et 15h06–17h06

def compute_cost(start, end, kWh_total):
    if kWh_total == 0 or start == end:
        return 0, 0, 0
    duration_sec = (end - start).total_seconds()
    kWh_per_sec = kWh_total / duration_sec
    kWh_hc, kWh_hp = 0, 0
    current = start
    while current < end:
        next_step = min(current + timedelta(minutes=1), end)
        secs = (next_step - current).total_seconds()
        kWh_chunk = kWh_per_sec * secs
        if is_hc(current.time()):
            kWh_hc += kWh_chunk
        else:
            kWh_hp += kWh_chunk
        current = next_step
    tarifs = get_tarifs(start)
    cost = kWh_hc * tarifs["HC"] + kWh_hp * tarifs["HP"]
    return kWh_hc, kWh_hp, cost

def generate_facture(df, annexe_file, mois_selection):
    # Conversion des dates
    df["Date/heure de début"] = pd.to_datetime(df["Date/heure de début"])
    df["Date/heure de fin"] = pd.to_datetime(df["Date/heure de fin"])
    df["kWh"] = df["Énergie consommée (Wh)"] / 1000

    # Filtre : véhicule Scenic + sessions > 0 Wh
    df = df[(df["Authentification"] == VEHICULE) & (df["Énergie consommée (Wh)"] > 0)]

    # Filtre sur le mois choisi
    df = df[df["Date/heure de début"].dt.strftime("%Y-%m") == mois_selection]

    if df.empty:
        return None  # aucune session

    sessions = []
    total_HT = 0
    for _, row in df.iterrows():
        kWh_hc, kWh_hp, cost = compute_cost(row["Date/heure de début"], row["Date/heure de fin"], row["kWh"])
        sessions.append({
            "date": row["Date/heure de début"].strftime("%d/%m/%Y"),
            "debut": row["Date/heure de début"].strftime("%Hh%M"),
            "fin": row["Date/heure de fin"].strftime("%Hh%M"),
            "duree": str(row["Date/heure de fin"] - row["Date/heure de début"]),
            "kWh_total": row["kWh"],
            "kWh_HC": kWh_hc,
            "kWh_HP": kWh_hp,
            "tarif_HC": get_tarifs(row["Date/heure de début"])["HC"],
            "tarif_HP": get_tarifs(row["Date/heure de début"])["HP"],
            "cout": cost
        })
        total_HT += cost

    total_kWh = sum(s["kWh_total"] for s in sessions)
    tva = total_HT * 0.20
    total_TTC = total_HT + tva

    # Génération facture page 1
    tmpdir = tempfile.mkdtemp()
    facture_file = os.path.join(tmpdir, "facture_page1.pdf")
    doc = SimpleDocTemplate(facture_file, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>FACTURE DE RECHARGE VEHICULE ELECTRIQUE</b>", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(FACTURE_EMETTEUR, styles["Normal"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(FACTURE_CLIENT, styles["Normal"]))
    elements.append(Spacer(1, 24))

    elements.append(Paragraph(f"<b>Facture n°:</b> {mois_selection}-{VEHICULE}<br/>"
                              f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}<br/>"
                              f"<b>Période :</b> {mois_selection}<br/>"
                              f"<b>Véhicule :</b> {IMMATRICULATION}", styles["Normal"]))
    elements.append(Spacer(1, 24))

    # Tableau sessions
    table_data = [["Date", "Début", "Fin", "Durée", "kWh total", "kWh HC", "kWh HP", "Tarif HC", "Tarif HP", "Montant (€)"]]
    for s in sessions:
        table_data.append([s["date"], s["debut"], s["fin"], s["duree"],
                           f"{s['kWh_total']:.2f}", f"{s['kWh_HC']:.2f}", f"{s['kWh_HP']:.2f}",
                           f"{s['tarif_HC']:.4f}", f"{s['tarif_HP']:.4f}", f"{s['cout']:.2f}"])
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    elements.append(table)
    elements.append(Spacer(1, 24))

    # Récap
    recap_data = [
        ["Total énergie consommée", f"{total_kWh:.2f} kWh"],
        ["Total HT", f"{total_HT:.2f} €"],
        ["TVA (20%)", f"{tva:.2f} €"],
        ["Total TTC", f"{total_TTC:.2f} €"]
    ]
    recap_table = Table(recap_data, colWidths=[200, 100])
    recap_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    elements.append(recap_table)
    elements.append(Spacer(1, 24))

    mentions = """Facture générée automatiquement à partir du compteur certifié MID<br/>
    <b>Enphase IQ-EVSE-EU-3032</b> – Conforme aux directives MID, LVD, EMC, RED, RoHS"""
    elements.append(Paragraph(mentions, styles["Normal"]))

    doc.build(elements)

    # Fusion avec annexe
    final_pdf = os.path.join(tmpdir, "facture_complete.pdf")
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

mois_selection = st.text_input("Mois de consommation (format YYYY-MM)", value=datetime.now().strftime("%Y-%m"))

if uploaded_csv is not None and uploaded_annexe is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
        tmp_csv.write(uploaded_csv.read())
        csv_path = tmp_csv.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
        tmp_pdf.write(uploaded_annexe.read())
        annexe_path = tmp_pdf.name

    if st.button("📄 Générer la facture"):
        df = pd.read_csv(csv_path)
        output_pdf = generate_facture(df, annexe_path, mois_selection)
        if output_pdf is None:
            st.error("⚠️ Aucune session trouvée pour ce mois et ce véhicule (Scenic).")
        else:
            with open(output_pdf, "rb") as f:
                st.download_button("⬇️ Télécharger la facture PDF", f, file_name=f"facture_{mois_selection}.pdf")
