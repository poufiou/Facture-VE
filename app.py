import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from PyPDF2 import PdfMerger
from datetime import datetime
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

# Tarifs FOURNIS TTC
TARIFS_TTC_AVANT = {"HC": 0.1696, "HP": 0.2146}  # jusqu'au 31/07/2025 inclus
TARIFS_TTC_APRES = {"HC": 0.1635, "HP": 0.2081}  # à partir du 01/08/2025
DATE_BASCULE = pd.Timestamp(2025, 8, 1).date()

# =========================
# 📁 Persistance locale des annexes (PDF)
# =========================
STORAGE_DIR = os.path.join(os.getcwd(), "storage")
DEFAULT_CERT_PATH = os.path.join(STORAGE_DIR, "default_certificat.pdf")
DEFAULT_EDF_PATH  = os.path.join(STORAGE_DIR, "default_facture_electricite.pdf")

os.makedirs(STORAGE_DIR, exist_ok=True)

def save_default_pdf(uploaded_file, dest_path):
    """Sauvegarde un fichier uploadé comme PDF par défaut."""
    if uploaded_file is None:
        return False
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return True

def load_default_pdf(path):
    """Retourne un path si le PDF par défaut existe, sinon None."""
    return path if os.path.exists(path) and os.path.getsize(path) > 0 else None

# =========================
# 🔧 Utilitaires
# =========================
def parse_minutes(val):
    """'6 hr 26 min' ou '5 min 3 sec' -> minutes (arrondi à la minute sup si sec>0)."""
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
    """HC : 00:06–06:06 et 15:06–17:06."""
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

def tarifs_ttc_pour(date_obj):
    return TARIFS_TTC_APRES if date_obj >= DATE_BASCULE else TARIFS_TTC_AVANT

def tarifs_ht_depuis_ttc(tarifs_ttc):
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
def generate_facture(df, vehicule, mois, certif_path=None, edf_path=None):
    tmpdir = tempfile.mkdtemp()
    out_name = f"facture_complete_{vehicule}_{mois}.pdf"
    pdf_path = os.path.join(tmpdir, out_name)

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []

    # Titre
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
        [Paragraph(f"<b>Période :</b> {mois}", NORMAL),
         Paragraph(f"<b>Véhicule :</b> {vehicule}", NORMAL)],
    ]
    t_infos = Table(infos, colWidths=[250, 250])
    t_infos.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#f2f2f2")),
                                 ("GRID",(0,0),(-1,-1),0.5, colors.black)]))
    elements.append(t_infos)
    elements.append(Spacer(1, 12))

    # Tableau des sessions (on affiche Tarifs TTC, mais calcul en HT)
    headers = ["Date","Début","Fin","Durée","kWh total","kWh HC","kWh HP","Tarif HC (TTC)","Tarif HP (TTC)","Montant HT (€)"]
    data = [headers]
    total_kwh = 0.0
    total_ht  = 0.0

    for _, row in df.iterrows():
        d_deb = row["Date/heure de début"]
        d_fin = row["Date/heure de fin"]
        d_fact = d_deb.date()

        debut_txt = d_deb.strftime("%Hh%M")
        fin_txt   = d_fin.strftime("%Hh%M")

        # Durée HhMM (sans secondes)
        duree_min = parse_minutes(row["Temps de charge active"])
        h, m = divmod(duree_min, 60)
        duree_txt = f"{h}h{m:02d}"

        # Énergie & ventilation
        kwh_total = float(row["Énergie consommée (Wh)"] or 0) / 1000.0
        kwh_hc, kwh_hp = calcul_hp_hc(d_deb, duree_min, kwh_total)

        # Tarifs TTC -> HT
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

    # Conditions tarifaires
    conditions = [[Paragraph("<b>Conditions tarifaires</b>", HEADER)],
                  [Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06", NORMAL)],
                  [Paragraph("Tarifs fournis TTC. Les montants HT sont calculés avec (TTC / 1,20).", NORMAL)],
                  [Paragraph("Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh (TTC)", NORMAL)],
                  [Paragraph("À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh (TTC)", NORMAL)]]
    t_conditions = Table(conditions, colWidths=[500])
    t_conditions.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_conditions)
    elements.append(Spacer(1, 12))

    # Chargeur
    chargeur = [[Paragraph("<b>Chargeur</b>", HEADER)],
                [Paragraph("Enphase IQ-EVSE-EU-3032", NORMAL)],
                [Paragraph("Numéro de série : 202451008197", NORMAL)],
                [Paragraph("Conforme aux directives MID, LVD, EMC, RED, RoHS", NORMAL)]]
    t_chargeur = Table(chargeur, colWidths=[500])
    t_chargeur.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_chargeur)
    elements.append(Spacer(1, 12))

    # CO2 (simple)
    km, co2kg, arbres = co2_evite_from_kwh(total_kwh)
    co2_tab = [[Paragraph("Impact CO<sub>2</sub> évité", HEADER)],
               [Paragraph(f"Distance estimée parcourue : {km} km", NORMAL)],
               [Paragraph(f"CO<sub>2</sub> évité : {co2kg} kg", NORMAL)],
               [Paragraph(f"Arbres équivalents : {arbres}", NORMAL)]]
    t_co2 = Table(co2_tab, colWidths=[500])
    t_co2.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.black)]))
    elements.append(t_co2)

    doc.build(elements)

    # Fusion avec annexes
    merger = PdfMerger()
    merger.append(pdf_path)

    # Annexes : priorité à l'upload courant, sinon défaut persisté
    if certif_path and os.path.exists(certif_path):
        merger.append(certif_path)
    if edf_path and os.path.exists(edf_path):
        merger.append(edf_path)

    final_path = pdf_path.replace(".pdf", "_final.pdf")
    merger.write(final_path); merger.close()
    return final_path

# =========================
# 🚀 Interface Streamlit
# =========================
st.title("⚡ Facturation des recharges VE — Sélection par MOIS")

uploaded_csv    = st.file_uploader("Chargez le fichier CSV", type=["csv"])

# Chargement / mémorisation des annexes
st.subheader("Annexes (facultatif)")
colA, colB = st.columns(2)
with colA:
    uploaded_certif = st.file_uploader("Certificat de conformité (PDF)", type=["pdf"], key="cert")
with colB:
    uploaded_edf    = st.file_uploader("Facture d’électricité (PDF)", type=["pdf"], key="edf")

memo = st.checkbox("Mémoriser ces fichiers comme défaut", value=False, help="Ils seront réutilisés automatiquement la prochaine fois.")
# Sauvegarde des défauts si demandé
if memo:
    if uploaded_certif: save_default_pdf(uploaded_certif, DEFAULT_CERT_PATH)
    if uploaded_edf:    save_default_pdf(uploaded_edf, DEFAULT_EDF_PATH)

# Fichiers par défaut (persistés)
default_cert = load_default_pdf(DEFAULT_CERT_PATH)
default_edf  = load_default_pdf(DEFAULT_EDF_PATH)

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

    # 📅 Sélecteur MOIS (YYYY-MM) disponibles
    mois_dispos = sorted(df["Date/heure de début"].dt.strftime("%Y-%m").dropna().unique())
    mois = st.selectbox("Choisissez le mois de consommation", mois_dispos)

    # Filtrage
    df_filtre = df[
        (df["Authentification"] == vehicule) &
        (df["Date/heure de début"].dt.strftime("%Y-%m") == mois) &
        (df["Énergie consommée (Wh)"].fillna(0) > 0)
    ].copy()

    st.write("🔎 Aperçu des sessions filtrées",
             df_filtre[["Date/heure de début","Date/heure de fin","Énergie consommée (Wh)","Temps de charge active"]].head())

    if st.button("📄 Générer la facture PDF"):
        if df_filtre.empty:
            st.error("Aucune session trouvée pour ce véhicule et ce mois.")
        else:
            # Choix des annexes : upload courant prioritaire, sinon défauts mémorisés
            cert_path = None
            edf_path  = None
            if uploaded_certif:
                cert_path = os.path.join(tempfile.mkdtemp(), "cert.pdf")
                with open(cert_path, "wb") as f: f.write(uploaded_certif.getbuffer())
            elif default_cert:
                cert_path = default_cert

            if uploaded_edf:
                edf_path = os.path.join(tempfile.mkdtemp(), "edf.pdf")
                with open(edf_path, "wb") as f: f.write(uploaded_edf.getbuffer())
            elif default_edf:
                edf_path = default_edf

            output = generate_facture(df_filtre, vehicule, mois, cert_path, edf_path)
            with open(output, "rb") as f:
                st.download_button("⬇️ Télécharger la facture", f, file_name=os.path.basename(output))
