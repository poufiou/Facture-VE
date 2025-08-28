import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from PyPDF2 import PdfMerger

# === Styles ===
styles = getSampleStyleSheet()
TITLE  = ParagraphStyle("Title", parent=styles["Title"], textColor=colors.HexColor("#8DC63F"), fontSize=18, alignment=1)
NORMAL = ParagraphStyle("Normal", parent=styles["Normal"], textColor=colors.HexColor("#4D4D4D"), fontSize=10)
HEADER = ParagraphStyle("Header", parent=styles["Heading2"], textColor=colors.HexColor("#8DC63F"), fontSize=12, spaceAfter=6)

# === Tarifs ===
TARIFS = {
    "avant": {"HC": 0.1696, "HP": 0.2146},
    "apres": {"HC": 0.1635, "HP": 0.2081}
}
DATE_CHGT_TARIF = datetime(2025, 8, 1)

HC_PLAGES = [(0,6,6), (15,6,17,6)]  # (heure début, min début, heure fin, min fin)

# === Fonctions ===
def est_hc(dt):
    """Retourne True si datetime est en heures creuses"""
    h, m = dt.hour, dt.minute
    # Plage 1 : 00h06 -> 06h06
    if (h > 0 or (h == 0 and m >= 6)) and (h < 6 or (h == 6 and m <= 6)):
        return True
    # Plage 2 : 15h06 -> 17h06
    if (h > 15 or (h == 15 and m >= 6)) and (h < 17 or (h == 17 and m <= 6)):
        return True
    return False

def repartir_hp_hc(row):
    """Répartit les Wh entre HC et HP selon temps de charge active"""
    debut = row["Date/heure de début"]
    fin = row["Date/heure de fin"]
    wh_total = row["Énergie consommée (Wh)"]

    if wh_total == 0:
        return 0, 0

    duree = (fin - debut).total_seconds()
    if duree == 0:
        return 0,0

    wh_par_sec = wh_total / duree
    hc, hp = 0,0
    dt = debut

    while dt < fin:
        dt_next = dt + timedelta(minutes=1)
        wh = wh_par_sec * 60
        if est_hc(dt):
            hc += wh
        else:
            hp += wh
        dt = dt_next

    return hc/1000, hp/1000  # en kWh

def calculer_co2(kwh):
    """Calcule le CO2 évité et équivalent arbres"""
    # Hypothèse : Scenic 17 kWh/100 km, diesel 5 L/100 km = 130 gCO2/km
    km = kwh / 0.17
    co2_diesel = km * 0.13  # tonnes → kg
    co2_elec = km * 0.02    # France mix bas carbone
    co2_evite = co2_diesel - co2_elec
    arbres = int(round(co2_evite / 25))  # 1 arbre ≈ 25 kg/an
    return km, co2_evite, arbres

def generate_facture(df, mois, vehicule, annex_certif, annex_facture):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []

    # --- En-tête ---
    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", TITLE))
    elements.append(Spacer(1, 12))

    infos = [
        [Paragraph(f"<b>Facture n°:</b> {mois}-{vehicule}", NORMAL),
         Paragraph(f"<b>Date :</b> {datetime.today().strftime('%d/%m/%Y')}", NORMAL)],
        [Paragraph(f"<b>Période :</b> {mois}", NORMAL),
         Paragraph(f"<b>Véhicule :</b> {vehicule}", NORMAL)]
    ]
    t_infos = Table(infos, colWidths=[250,250])
    t_infos.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black),
                                 ("BACKGROUND",(0,0),(-1,-1),colors.whitesmoke)]))
    elements.append(t_infos)
    elements.append(Spacer(1, 12))

    # --- Sessions ---
    headers = ["Date","Début","Fin","Durée","kWh total","kWh HC","kWh HP","Tarif HC","Tarif HP","Montant (€)"]
    data = [headers]
    total_kwh, total_ht = 0,0

    for _, row in df.iterrows():
        hc, hp = repartir_hp_hc(row)
        kwh = hc + hp
        total_kwh += kwh

        tarif_set = TARIFS["avant"] if row["Date/heure de début"] < DATE_CHGT_TARIF else TARIFS["apres"]
        prix = hc * tarif_set["HC"] + hp * tarif_set["HP"]
        total_ht += prix

        data.append([
            row["Date/heure de début"].strftime("%d/%m/%Y"),
            row["Date/heure de début"].strftime("%Hh%M"),
            row["Date/heure de fin"].strftime("%Hh%M"),
            str(row["Durée de la session"]),
            f"{kwh:.2f}",
            f"{hc:.2f}",
            f"{hp:.2f}",
            f"{tarif_set['HC']:.4f}",
            f"{tarif_set['HP']:.4f}",
            f"{prix:.2f}"
        ])

    col_widths = [70,40,40,55,50,50,50,45,45,55]
    t_sessions = Table(data, repeatRows=1, colWidths=col_widths)
    t_sessions.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#8DC63F")),
        ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("GRID",(0,0),(-1,-1),0.5, colors.black)
    ]))
    elements.append(t_sessions)
    elements.append(Spacer(1, 12))

    # --- Récap ---
    ttc = total_ht * 1.2
    recap = [["Total énergie consommée",f"{total_kwh:.2f} kWh"],
             ["Total HT",f"{total_ht:.2f} €"],
             ["TVA (20%)",f"{total_ht*0.2:.2f} €"],
             ["Total TTC",f"{ttc:.2f} €"]]
    t_recap = Table(recap, colWidths=[350,150])
    t_recap.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
        ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#fff2cc")),
        ("TEXTCOLOR",(0,-1),(-1,-1), colors.HexColor("#b30000"))
    ]))
    elements.append(t_recap)
    elements.append(Spacer(1, 12))

    # --- Conditions tarifaires ---
    elements.append(Paragraph("<b>Conditions tarifaires</b>", HEADER))
    elements.append(Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06", NORMAL))
    elements.append(Paragraph("Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh", NORMAL))
    elements.append(Paragraph("À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh", NORMAL))
    elements.append(Spacer(1, 12))

    # --- Chargeur ---
    elements.append(Paragraph("<b>Chargeur</b>", HEADER))
    elements.append(Paragraph("Enphase IQ-EVSE-EU-3032", NORMAL))
    elements.append(Paragraph("Numéro de série : 202451008197", NORMAL))
    elements.append(Paragraph("Conforme aux directives MID, LVD, EMC, RED, RoHS", NORMAL))
    elements.append(Spacer(1, 12))

    # --- Impact CO2 ---
    km, co2, arbres = calculer_co2(total_kwh)
    elements.append(Paragraph("🌍 Impact CO<sub>2</sub> évité", HEADER))
    elements.append(Paragraph(f"Distance estimée parcourue : {int(km)} km", NORMAL))
    elements.append(Paragraph(f"CO<sub>2</sub> évité : {int(co2)} kg", NORMAL))
    elements.append(Paragraph("🌳" * arbres + f" ({arbres} arbres équivalents)", NORMAL))

    doc.build(elements)
    buffer.seek(0)

    # --- Fusion annexes ---
    merger = PdfMerger()
    merger.append(buffer)
    if annex_certif: merger.append(annex_certif)
    if annex_facture: merger.append(annex_facture)

    out_buf = BytesIO()
    merger.write(out_buf)
    merger.close()
    out_buf.seek(0)
    return out_buf

# === Interface ===
st.title("⚡ Générateur de factures de recharge VE")

uploaded_csv = st.file_uploader("Chargez le fichier CSV des sessions", type=["csv"])
uploaded_certif = st.file_uploader("Chargez le certificat de conformité (PDF)", type=["pdf"])
uploaded_facture = st.file_uploader("Chargez la facture d’électricité (PDF)", type=["pdf"])
mois = st.text_input("Mois de consommation (format YYYY-MM)", "2025-08")
vehicule = st.text_input("Nom du véhicule", "Scenic HD-803-PZ")

if st.button("Générer la facture PDF"):
    if uploaded_csv is None:
        st.error("Veuillez charger un fichier CSV.")
    else:
        df = pd.read_csv(uploaded_csv, sep=",")
        df["Date/heure de début"] = pd.to_datetime(df["Date/heure de début"])
        df["Date/heure de fin"] = pd.to_datetime(df["Date/heure de fin"])

        output_pdf = generate_facture(df, mois, vehicule, uploaded_certif, uploaded_facture)
        st.download_button("📥 Télécharger la facture PDF", data=output_pdf,
                           file_name=f"facture_complete_{vehicule}_{mois}.pdf",
                           mime="application/pdf")
