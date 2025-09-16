import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from PyPDF2 import PdfMerger
from datetime import datetime, date
import tempfile, os

# =========================
# 🎨 Styles PDF
# =========================
styles = getSampleStyleSheet()
TITLE  = ParagraphStyle("Title", parent=styles["Title"], textColor=colors.HexColor("#8DC63F"), fontSize=18, alignment=1)
NORMAL = ParagraphStyle("Normal", parent=styles["Normal"], textColor=colors.HexColor("#4D4D4D"), fontSize=10)
HEADER = ParagraphStyle("Header", parent=styles["Heading2"], textColor=colors.HexColor("#8DC63F"), fontSize=12, spaceAfter=6)

# =========================
# ⚙️ Paramètres fiscaux & tarifs
# =========================
TVA_RATE = 0.20
DIV_TVA  = 1.0 + TVA_RATE

TARIFS_TTC_AVANT = {"HC": 0.1696, "HP": 0.2146}  # TTC
TARIFS_TTC_APRES = {"HC": 0.1635, "HP": 0.2081}  # TTC
DATE_BASCULE = pd.Timestamp(2025, 8, 1).date()

# =========================
# 🔧 Utilitaires
# =========================
def parse_minutes(val):
    """Convertit '6 hr 26 min' ou '5 min 3 sec' -> minutes (arrondi à la minute sup si sec>0)."""
    if pd.isna(val):
        return 0
    txt = str(val).lower()
    h = m = s = 0
    if "hr" in txt:
        try: h = int(txt.split("hr")[0].strip().split()[-1])
        except: h = 0
        txt = txt.split("hr",1)[1]
    if "min" in txt:
        try: m = int(txt.split("min")[0].strip().split()[-1])
        except: m = 0
        txt = txt.split("min",1)[1]
    if "sec" in txt:
        try: s = int(txt.split("sec")[0].strip().split()[-1])
        except: s = 0
    return h*60 + m + (1 if s>0 else 0)

def est_hc(dt):
    """Heures creuses : 00:06–06:06 et 15:06–17:06."""
    h, m = dt.hour, dt.minute
    if (h > 0 or (h == 0 and m >= 6)) and (h < 6 or (h == 6 and m <= 6)):
        return True
    if (h > 15 or (h == 15 and m >= 6)) and (h < 17 or (h == 17 and m <= 6)):
        return True
    return False

def calcul_hp_hc(start_time, duration_min, energy_kwh):
    """Ventile kWh entre HC/HP minute par minute."""
    if duration_min <= 0 or energy_kwh <= 0:
        return 0.0, 0.0
    hc_minutes = hp_minutes = 0
    current = start_time
    for _ in range(duration_min):
        if est_hc(current): hc_minutes += 1
        else: hp_minutes += 1
        current += pd.Timedelta(minutes=1)
    hc_kwh = energy_kwh * (hc_minutes / duration_min)
    hp_kwh = energy_kwh * (hp_minutes / duration_min)
    return round(hc_kwh, 2), round(hp_kwh, 2)

def tarifs_ttc_pour(date_obj: date):
    return TARIFS_TTC_APRES if date_obj >= DATE_BASCULE else TARIFS_TTC_AVANT

def tarifs_ht_depuis_ttc(tarifs_ttc: dict):
    return {k: v / DIV_TVA for k, v in tarifs_ttc.items()}

def co2_evite_from_kwh(total_kwh: float):
    # Hypothèses simples : Scenic ~16.5 kWh/100km → km ≈ kWh / 0.165
    km = int(round(total_kwh / 0.165))
    # Gain ~75 g CO2/km vs diesel → kg:
    co2_kg = int(round(km * 0.075))
    arbres = max(1, int(round(co2_kg / 25.0)))
    return km, co2_kg, arbres

# =========================
# 🧾 Génération PDF
# =========================
def generate_facture(df, vehicule, date_deb: date, date_fin: date, certif_file, edf_file):
    tmpdir = tempfile.mkdtemp()
    period_txt = f"{date_deb.strftime('%Y-%m-%d')} au {date_fin.strftime('%Y-%m-%d')}"
    out_name = f"facture_complete_{vehicule}_{date_deb.isoformat()}_{date_fin.isoformat()}.pdf"
    pdf_path = os.path.join(tmpdir, out_name)

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []

    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", TITLE))
    elements.append(Spacer(1, 12))

    # Émetteur / Client
    emetteur = Paragraph("<b>Émetteur :</b><br/>Wesley MARSTON<br/>5 clairière des vernedes<br/>83480 Puget sur Argens", NORMAL)
    client = Paragraph("<b>Facture à :</b><br/>ALKERN France<br/>Rue André Bigotte<br/>Z.I. Parc de la motte au bois<br/>62440 Harnes", NORMAL)
    t_info = Table([[emetteur, client]], colWidths=[250, 250])
    t_info.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                                ("BOX",(0,0),(-1,-1),0.5,colors.black),
                                ("BACKGROUND",(0,0),(-1,-1), colors.whitesmoke)]))
    elements.append(t_info)
    elements.append(Spacer(1, 12))

    # Infos facture
    infos = [
        [Paragraph(f"<b>Facture n°:</b> {datetime.now().strftime('%Y%m%d')}-{vehicule}", NORMAL),
         Paragraph(f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}", NORMAL)],
        [Paragraph(f"<b>Période :</b> {period_txt}", NORMAL),
         Paragraph(f"<b>Véhicule :</b> {vehicule}", NORMAL)],
    ]
    t_infos = Table(infos, colWidths=[250, 250])
    t_infos.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#f2f2f2")),
                                 ("GRID",(0,0),(-1,-1),0.5, colors.black)]))
    elements.append(t_infos)
    elements.append(Spacer(1, 12))

    # Tableau des sessions
    headers = ["Date","Début","Fin","Durée","kWh total","kWh HC","kWh HP",
               "Tarif HC (TTC)","Tarif HP (TTC)","Montant HT (€)"]
    data = [headers]
    total_kwh = 0.0
    total_ht = 0.0

    for _, row in df.iterrows():
        d_deb = row["Date/heure de début"]
        d_fin = row["Date/heure de fin"]
        d_fact = d_deb.date()

        debut_txt = d_deb.strftime("%Hh%M")
        fin_txt   = d_fin.strftime("%Hh%M")

        # Durée HhMM
        duree_min = parse_minutes(row["Temps de charge active"])
        h, m = divmod(duree_min, 60)
        duree_txt = f"{h}h{m:02d}"

        kwh_total = float(row["Énergie consommée (Wh)"] or 0) / 1000.0
        kwh_hc, kwh_hp = calcul_hp_hc(d_deb, duree_min, kwh_total)

        tarifs_ttc = tarifs_ttc_pour(d_fact)
        tarifs_ht  = tarifs_ht_depuis_ttc(tarifs_ttc)

        montant_ht = kwh_hc*tarifs_ht["HC"] + kwh_hp*tarifs_ht["HP"]

        data.append([
            d_deb.strftime("%d/%m/%Y"),
            debut_txt, fin_txt, duree_txt,
            f"{kwh_total:.2f}", f"{kwh_hc:.2f}", f"{kwh_hp:.2f}",
            f"{tarifs_ttc['HC']:.4f}", f"{tarifs_ttc['HP']:.4f}",
            f"{montant_ht:.2f}",
        ])

        total_kwh += kwh_total
        total_ht  += montant_ht

    col_widths = [70,40,40,55,50,50,50,45,45,55]
    t_sessions = Table(data, repeatRows=1, colWidths=col_widths)
    t_sessions.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#8DC63F")),
        ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("GRID",(0,0),(-1,-1),0.5, colors.black)
    ]))
    elements.append(t_sessions)
    elements.append(Spacer(1, 12))

    # Récap (HT -> TVA -> TTC)
    tva_amount = total_ht * TVA_RATE
    total_ttc  = total_ht + tva_amount
    recap = [["Total énergie consommée", f"{total_kwh:.2f} kWh"],
             ["Total HT",              f"{total_ht:.2f} €"],
             [f"TVA ({int(TVA_RATE*100)}%)", f"{tva_amount:.2f} €"],
             ["Total TTC",             f"{total_ttc:.2f} €"]]
    t_recap = Table(recap, colWidths=[350,150])
    t_recap.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
        ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#fff2cc")),
        ("TEXTCOLOR",(0,-1),(-1,-1), colors.HexColor("#b30000"))
    ]))
    elements.append(t_recap)
    elements.append(Spacer(1, 12))

    # Conditions tarifaires (aligné)
    conditions = [[Paragraph("<b>Conditions tarifaires</b>", HEADER)],
                  [Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06", NORMAL)],
                  [Paragraph("Tarifs fournis TTC. La facture calcule les montants HT = TTC / 1,20.", NORMAL)],
                  [Paragraph("Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh (TTC)", NORMAL)],
                  [Paragraph("À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh (TTC)", NORMAL)]]
    t_conditions = Table(conditions, colWidths=[500])
    t_conditions.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_conditions)
    elements.append(Spacer(1, 12))

    # Chargeur (aligné)
    chargeur = [[Paragraph("<b>Chargeur</b>", HEADER)],
                [Paragraph("Enphase IQ-EVSE-EU-3032", NORMAL)],
                [Paragraph("Numéro de série : 202451008197", NORMAL)],
                [Paragraph("Conforme aux directives MID, LVD, EMC, RED, RoHS", NORMAL)]]
    t_chargeur = Table(chargeur, colWidths=[500])
    t_chargeur.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_chargeur)
    elements.append(Spacer(1, 12))

    # CO2 (aligné)
    km, co2kg, arbres = co2_evite_from_kwh(total_kwh)
    co2_tab = [[Paragraph("🌍 Impact CO<sub>2</sub> évité", HEADER)],
               [Paragraph(f"Distance estimée parcourue : {km} km", NORMAL)],
               [Paragraph(f"CO<sub>2</sub> évité : {co2kg} kg", NORMAL)],
               [Paragraph("🌳"*min(arbres, 20) + f" ({arbres} arbres équivalents)", NORMAL)]]
    t_co2 = Table(co2_tab, colWidths=[500])
    t_co2.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_co2)

    doc.build(elements)

    # Fusion avec annexes
    merger = PdfMerger()
    merger.append(pdf_path)
    if certif_file: merger.append(certif_file)
    if edf_file:    merger.append(edf_file)
    final_path = pdf_path.replace(".pdf", "_final.pdf")
    merger.write(final_path); merger.close()
    return final_path

# =========================
# 🚀 Interface Streamlit
# =========================
st.title("⚡ Facturation des recharges VE — Sélection par période")

uploaded_csv    = st.file_uploader("Chargez le fichier CSV", type=["csv"])
uploaded_certif = st.file_uploader("Chargez le certificat de conformité (PDF)", type=["pdf"])
uploaded_edf    = st.file_uploader("Chargez la facture d’électricité (PDF)", type=["pdf"])

if uploaded_csv:
    df = pd.read_csv(uploaded_csv, sep=",")
    # Dates
    df["Date/heure de début"] = pd.to_datetime(df["Date/heure de début"], errors="coerce")
    df["Date/heure de fin"]   = pd.to_datetime(df["Date/heure de fin"],   errors="coerce")

    # Sélecteur véhicule
    vehicules = df["Authentification"].dropna().unique().tolist()
    if not vehicules:
        st.error("Aucun véhicule détecté (colonne 'Authentification').")
        st.stop()
    vehicule = st.selectbox("Choisissez le véhicule", vehicules)

    # 📅 Sélecteur de période (deux dates)
    min_date = df["Date/heure de début"].dropna().min().date()
    max_date = df["Date/heure de début"].dropna().max().date()
    col1, col2 = st.columns(2)
    with col1:
        date_deb = st.date_input("Date de début", value=min_date, min_value=min_date, max_value=max_date)
    with col2:
        date_fin = st.date_input("Date de fin", value=max_date, min_value=min_date, max_value=max_date)

    if date_deb > date_fin:
        st.error("La date de début doit être antérieure ou égale à la date de fin.")
        st.stop()

    # Filtrage par véhicule + plage de dates (sur la date de début de session)
    mask = (
        (df["Authentification"] == vehicule) &
        (df["Date/heure de début"].dt.date >= date_deb) &
        (df["Date/heure de début"].dt.date <= date_fin) &
        (df["Énergie consommée (Wh)"].fillna(0) > 0)
    )
    df_filtre = df.loc[mask].copy()

    st.write("🔎 Aperçu des sessions filtrées",
             df_filtre[["Date/heure de début","Date/heure de fin","Énergie consommée (Wh)","Temps de charge active"]].head())

    if st.button("📄 Générer la facture PDF"):
        if df_filtre.empty:
            st.error("Aucune session trouvée pour ce véhicule et cette période.")
        else:
            output = generate_facture(df_filtre, vehicule, date_deb, date_fin, uploaded_certif, uploaded_edf)
            with open(output, "rb") as f:
                st.download_button("⬇️ Télécharger la facture", f, file_name=os.path.basename(output))

