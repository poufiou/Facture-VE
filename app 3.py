import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from datetime import datetime
import io

# Styles et couleurs
alkern_green = colors.HexColor("#8DC63F")
alkern_gray = colors.HexColor("#4D4D4D")
light_gray = colors.HexColor("#f2f2f2")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=styles["Title"], textColor=alkern_green, fontSize=18, alignment=1)
normal_style = ParagraphStyle("Normal", parent=styles["Normal"], textColor=alkern_gray, fontSize=10)
header_style = ParagraphStyle("Header", parent=styles["Heading2"], textColor=alkern_green, fontSize=12, spaceAfter=6)
center_style = ParagraphStyle("Center", parent=styles["Normal"], alignment=1, fontSize=11, textColor=alkern_gray)

# Fonction de génération du PDF
def generate_facture(df, mois_selection):
    # Conversion des dates
    df["Date/heure de début"] = pd.to_datetime(df["Date/heure de début"])
    df["Date/heure de fin"] = pd.to_datetime(df["Date/heure de fin"])
    
    # Filtrage par mois
    df = df[df["Date/heure de début"].dt.strftime("%Y-%m") == mois_selection]
    df = df[df["Authentification"] == "Scenic"]
    
    if df.empty:
        return None

    # Sessions formatées
    sessions = []
    for _, row in df.iterrows():
        date = row["Date/heure de début"].strftime("%d/%m/%Y")
        debut = row["Date/heure de début"].strftime("%Hh%M")
        fin = row["Date/heure de fin"].strftime("%Hh%M")
        duree = row["Durée de la session"]
        kWh_total = row["Énergie consommée (Wh)"] / 1000
        # Pour simplifier ici : HC = 60%, HP = 40%
        kWh_HC = kWh_total * 0.6
        kWh_HP = kWh_total * 0.4
        tarif_HC = 0.1635 if row["Date/heure de début"] >= datetime(2025,8,1) else 0.1696
        tarif_HP = 0.2081 if row["Date/heure de début"] >= datetime(2025,8,1) else 0.2146
        cout = kWh_HC*tarif_HC + kWh_HP*tarif_HP
        sessions.append({
            "date": date, "debut": debut, "fin": fin, "duree": duree,
            "kWh_total": kWh_total, "kWh_HC": kWh_HC, "kWh_HP": kWh_HP,
            "tarif_HC": tarif_HC, "tarif_HP": tarif_HP, "cout": cout
        })

    total_kWh = sum(s["kWh_total"] for s in sessions)
    total_HT = sum(s["cout"] for s in sessions)
    tva, total_TTC = total_HT * 0.20, total_HT * 1.20

    # CO2
    km_estimes = total_kWh / 0.165
    co2_diesel = km_estimes * 120 / 1000
    co2_ev = km_estimes * 4.5 / 1000
    gain_co2 = co2_diesel - co2_ev
    arbres_eq = int(round(gain_co2 / 25))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []

    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", title_style))
    elements.append(Spacer(1, 18))

    # Bloc Emetteur / Client
    emetteur = Paragraph("<b>Émetteur :</b><br/>Wesley MARSTON<br/>5 clairière des vernedes<br/>83480 Puget sur Argens", normal_style)
    client = Paragraph("<b>Facture à :</b><br/>ALKERN France<br/>Rue André Bigotte<br/>Z.I. Parc de la motte au bois<br/>62440 Harnes", normal_style)
    table_info = Table([[emetteur, client]], colWidths=[250, 250])
    table_info.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"),
                                    ("BOX", (0,0), (-1,-1), 0.5, colors.black),
                                    ("BACKGROUND", (0,0), (-1,-1), colors.whitesmoke)]))
    elements.append(table_info)
    elements.append(Spacer(1, 18))

    # Infos générales
    infos = [
        [Paragraph(f"<b>Facture n°:</b> {datetime.now().strftime('%Y%m%d')}-HD-803-PZ", normal_style),
         Paragraph(f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}", normal_style)],
        [Paragraph(f"<b>Période :</b> {mois_selection}", normal_style),
         Paragraph("<b>Véhicule :</b> Scenic HD-803-PZ", normal_style)]
    ]
    table_infos = Table(infos, colWidths=[250, 250])
    table_infos.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), light_gray),
                                     ("GRID", (0,0), (-1,-1), 0.5, colors.black)]))
    elements.append(table_infos)
    elements.append(Spacer(1, 18))

    # Tableau sessions
    table_data = [["Date", "Début", "Fin", "Durée", "kWh total", "kWh HC", "kWh HP", "Tarif HC", "Tarif HP", "Montant (€)"]]
    for s in sessions:
        table_data.append([s["date"], s["debut"], s["fin"], s["duree"], f"{s['kWh_total']:.2f}", f"{s['kWh_HC']:.2f}",
                           f"{s['kWh_HP']:.2f}", f"{s['tarif_HC']:.4f}", f"{s['tarif_HP']:.4f}", f"{s['cout']:.2f}"])
    table = Table(table_data, repeatRows=1, colWidths=[65,50,50,55,55,55,55,55,55,65])
    table_style = TableStyle([("BACKGROUND", (0,0), (-1,0), alkern_green),
                              ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                              ("ALIGN", (4,1), (-1,-1), "RIGHT"),
                              ("GRID", (0,0), (-1,-1), 0.5, colors.black)])
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            table_style.add("BACKGROUND", (0,i), (-1,i), light_gray)
    table.setStyle(table_style)
    elements.append(table)
    elements.append(Spacer(1, 18))

    # Totaux
    recap = [["Total énergie consommée", f"{total_kWh:.2f} kWh"],
             ["Total HT", f"{total_HT:.2f} €"],
             ["TVA (20%)", f"{tva:.2f} €"],
             ["Total TTC", f"{total_TTC:.2f} €"]]
    recap_table = Table(recap, colWidths=[220, 120])
    recap_table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.black),
                                     ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#fff2cc")),
                                     ("TEXTCOLOR", (0,-1), (-1,-1), colors.HexColor("#b30000")),
                                     ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
                                     ("FONTSIZE", (0,-1), (-1,-1), 12)]))
    elements.append(recap_table)
    elements.append(Spacer(1, 18))

    # Conditions tarifaires
    elements.append(Paragraph("Conditions tarifaires", header_style))
    elements.append(Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06<br/>"
                              "Tarifs appliqués :<br/>"
                              "Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh<br/>"
                              "À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh", normal_style))
    elements.append(Spacer(1, 18))

    # Chargeur
    elements.append(Paragraph("Chargeur", header_style))
    elements.append(Paragraph("Enphase IQ-EVSE-EU-3032<br/>"
                              "Numéro de série : 202451008197<br/>"
                              "Conforme aux directives MID, LVD, EMC, RED, RoHS", normal_style))
    elements.append(Spacer(1, 18))

    # CO2
    elements.append(Paragraph("🌍 Impact CO₂ évité", header_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(f"Distance estimée parcourue : {km_estimes:,.0f} km", normal_style))
    elements.append(Paragraph(f"CO₂ évité : {gain_co2:,.0f} kg", normal_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("🌳 " * arbres_eq + f" ({arbres_eq} arbres équivalents)", center_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ---------------- Interface Streamlit -----------------
st.title("📄 Générateur de factures de recharge VE")

uploaded_file = st.file_uploader("Chargez le fichier CSV exporté de la borne", type=["csv"])
mois_selection = st.text_input("Mois de consommation (format YYYY-MM)", value=datetime.now().strftime("%Y-%m"))

if uploaded_file is not None and st.button("Générer la facture"):
    df = pd.read_csv(uploaded_file, sep=",")
    pdf_buffer = generate_facture(df, mois_selection)
    if pdf_buffer:
        st.success("✅ Facture générée avec succès !")
        st.download_button("⬇️ Télécharger la facture PDF", data=pdf_buffer, file_name=f"facture_HD-803-PZ_{mois_selection}.pdf", mime="application/pdf")
    else:
        st.error("⚠️ Aucune session trouvée pour ce mois et ce véhicule (Scenic).")
