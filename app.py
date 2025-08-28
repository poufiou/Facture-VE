import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from PyPDF2 import PdfMerger
import tempfile, os
from datetime import datetime

# 🎨 Styles PDF
styles = getSampleStyleSheet()
TITLE  = ParagraphStyle("Title", parent=styles["Title"], textColor=colors.HexColor("#8DC63F"), fontSize=18, alignment=1)
NORMAL = ParagraphStyle("Normal", parent=styles["Normal"], textColor=colors.HexColor("#4D4D4D"), fontSize=10)
HEADER = ParagraphStyle("Header", parent=styles["Heading2"], textColor=colors.HexColor("#8DC63F"), fontSize=12, spaceAfter=6)

# ⚡ Fonctions utiles
def calcul_hp_hc(start_time, duration_min, energy_kwh):
    """Répartition simplifiée HP/HC (à améliorer si besoin)"""
    hc_slots = [(0,6*60+6),(15*60+6,17*60+6)]
    end_time = start_time + pd.to_timedelta(f"{duration_min}min")
    minutes = duration_min
    if minutes == 0: return 0, 0
    hc_minutes, hp_minutes = 0, 0
    current = start_time
    while current < end_time:
        minute_of_day = current.hour*60 + current.minute
        if any(start<=minute_of_day<end for start,end in hc_slots):
            hc_minutes += 1
        else:
            hp_minutes += 1
        current += pd.Timedelta(minutes=1)
    hc_kwh = energy_kwh * hc_minutes/minutes
    hp_kwh = energy_kwh * hp_minutes/minutes
    return round(hc_kwh,2), round(hp_kwh,2)

def generate_facture(df, vehicule, mois, certif_file, edf_file):
    tmpdir = tempfile.mkdtemp()
    pdf_path = os.path.join(tmpdir, f"facture_complete_{vehicule}_{mois}.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=30,leftMargin=30,topMargin=30,bottomMargin=30)
    elements = []

    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", TITLE))
    elements.append(Spacer(1, 12))

    # Bloc émetteur / client
    emetteur = Paragraph("<b>Émetteur :</b><br/>Wesley MARSTON<br/>5 clairière des vernedes<br/>83480 Puget sur Argens", NORMAL)
    client = Paragraph("<b>Facture à :</b><br/>ALKERN France<br/>Rue André Bigotte<br/>Z.I. Parc de la motte au bois<br/>62440 Harnes", NORMAL)
    t_info = Table([[emetteur, client]], colWidths=[250,250])
    t_info.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                                ("BOX",(0,0),(-1,-1),0.5,colors.black),
                                ("BACKGROUND",(0,0),(-1,-1), colors.whitesmoke)]))
    elements.append(t_info)
    elements.append(Spacer(1, 12))

    # Bloc infos facture
    infos = [
        [Paragraph(f"<b>Facture n°:</b> {datetime.now().strftime('%Y%m%d')}-{vehicule}", NORMAL),
         Paragraph(f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}", NORMAL)],
        [Paragraph(f"<b>Période :</b> {mois}", NORMAL),
         Paragraph(f"<b>Véhicule :</b> {vehicule}", NORMAL)],
    ]
    t_infos = Table(infos, colWidths=[250,250])
    t_infos.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#f2f2f2")),
                                 ("GRID",(0,0),(-1,-1),0.5, colors.black)]))
    elements.append(t_infos)
    elements.append(Spacer(1, 12))

    # Table sessions
    headers = ["Date","Début","Fin","Durée","kWh total","kWh HC","kWh HP","Tarif HC","Tarif HP","Montant (€)"]
    data = [headers]
    total_kwh = total_ht = 0
    tarif_avant = {"HC":0.1696,"HP":0.2146}
    tarif_apres = {"HC":0.1635,"HP":0.2081}

    for _,row in df.iterrows():
        date = row["Date/heure de début"].date()
        debut = row["Date/heure de début"].strftime("%Hh%M")
        fin   = row["Date/heure de fin"].strftime("%Hh%M")
        duree = str(row["Temps de charge active"])
        kwh   = row["Énergie consommée (Wh)"]/1000
        hc, hp = calcul_hp_hc(row["Date/heure de début"], row["Temps de charge active"].seconds//60, kwh)
        tarif = tarif_avant if date < datetime(2025,8,1).date() else tarif_apres
        montant = hc*tarif["HC"] + hp*tarif["HP"]

        data.append([date.strftime("%d/%m/%Y"), debut, fin, duree,
                     f"{kwh:.2f}", f"{hc:.2f}", f"{hp:.2f}",
                     f"{tarif['HC']:.4f}", f"{tarif['HP']:.4f}", f"{montant:.2f}"])
        total_kwh += kwh
        total_ht  += montant

    col_widths = [70,40,40,55,50,50,50,45,45,55]
    t_sessions = Table(data, repeatRows=1, colWidths=col_widths)
    t_sessions.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0), colors.HexColor("#8DC63F")),
                                    ("TEXTCOLOR",(0,0),(-1,0), colors.white),
                                    ("GRID",(0,0),(-1,-1),0.5, colors.black)]))
    elements.append(t_sessions)
    elements.append(Spacer(1, 12))

    # Récap
    recap = [["Total énergie consommée",f"{total_kwh:.2f} kWh"],
             ["Total HT",f"{total_ht:.2f} €"],
             ["TVA (20%)",f"{total_ht*0.2:.2f} €"],
             ["Total TTC",f"{total_ht*1.2:.2f} €"]]
    t_recap = Table(recap, colWidths=[350,150])
    t_recap.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5, colors.black),
                                 ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#fff2cc")),
                                 ("TEXTCOLOR",(0,-1),(-1,-1), colors.HexColor("#b30000"))]))
    elements.append(t_recap)
    elements.append(Spacer(1, 12))

    # Bloc conditions
    conditions = [[Paragraph("<b>Conditions tarifaires</b>", HEADER)],
                  [Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06", NORMAL)],
                  [Paragraph("Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh", NORMAL)],
                  [Paragraph("À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh", NORMAL)]]
    t_conditions = Table(conditions, colWidths=[500])
    t_conditions.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_conditions)
    elements.append(Spacer(1, 12))

    # Bloc chargeur
    chargeur = [[Paragraph("<b>Chargeur</b>", HEADER)],
                [Paragraph("Enphase IQ-EVSE-EU-3032", NORMAL)],
                [Paragraph("Numéro de série : 202451008197", NORMAL)],
                [Paragraph("Conforme aux directives MID, LVD, EMC, RED, RoHS", NORMAL)]]
    t_chargeur = Table(chargeur, colWidths=[500])
    t_chargeur.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_chargeur)
    elements.append(Spacer(1, 12))

    # Bloc CO2
    co2_evite = total_kwh*0.115  # ~115g/km en diesel vs 15kWh/100km EV
    arbres = int(round(co2_evite/25))
    co2 = [[Paragraph("🌍 Impact CO<sub>2</sub> évité", HEADER)],
           [Paragraph(f"Distance estimée parcourue : {total_kwh*6:.0f} km", NORMAL)],
           [Paragraph(f"CO<sub>2</sub> évité : {co2_evite:.0f} kg", NORMAL)],
           [Paragraph("🌳"*arbres+f" ({arbres} arbres équivalents)", NORMAL)]]
    t_co2 = Table(co2, colWidths=[500])
    t_co2.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_co2)

    doc.build(elements)

    # Fusion avec annexes
    merger = PdfMerger()
    merger.append(pdf_path)
    if certif_file: merger.append(certif_file)
    if edf_file: merger.append(edf_file)
    final_path = pdf_path.replace(".pdf","_final.pdf")
    merger.write(final_path); merger.close()
    return final_path

# 🚀 Interface Streamlit
st.title("⚡ Facturation des recharges VE")

uploaded_csv = st.file_uploader("Chargez le fichier CSV", type=["csv"])
uploaded_certif = st.file_uploader("Chargez le certificat de conformité (PDF)", type=["pdf"])
uploaded_edf = st.file_uploader("Chargez la facture EDF (PDF)", type=["pdf"])
mois = st.text_input("Mois de consommation (format YYYY-MM)", datetime.now().strftime("%Y-%m"))

if uploaded_csv:
    df = pd.read_csv(uploaded_csv, sep=",")
    df["Date/heure de début"] = pd.to_datetime(df["Date/heure de début"])
    df["Date/heure de fin"] = pd.to_datetime(df["Date/heure de fin"])
    vehicules = df["Authentification"].dropna().unique()
    vehicule = st.selectbox("Choisissez le véhicule", vehicules)

    df_filtre = df[(df["Authentification"]==vehicule) & (df["Date/heure de début"].dt.strftime("%Y-%m")==mois)]

    st.write("🔎 Aperçu des sessions filtrées", df_filtre[["Date/heure de début","Énergie consommée (Wh)"]].head())

    if st.button("📄 Générer la facture PDF"):
        output = generate_facture(df_filtre, vehicule, mois, uploaded_certif, uploaded_edf)
        with open(output, "rb") as f:
            st.download_button("⬇️ Télécharger la facture", f, file_name=os.path.basename(output))
