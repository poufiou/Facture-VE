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
NORMAL = ParagraphStyle("Normal", parent=styles["Normal"], textColor=colors.HexColor("#4D4D4D"), fontSize=10.5)
HEADER = ParagraphStyle("Header", parent=styles["Heading2"], textColor=colors.HexColor("#8DC63F"), fontSize=12, spaceAfter=6)

TOTAL_WIDTH = 520  # largeur totale (points) pour aligner tous les tableaux

# =========================
# ⚙️ Paramètres fiscaux & tarifs
# =========================
TVA_RATE = 0.20
DIV_TVA  = 1.0 + TVA_RATE

# Tarifs FOURNIS TTC (affichage / référence)
TARIFS_TTC_AVANT = {"HC": 0.1696, "HP": 0.2146}  # jusqu'au 31/07/2025 inclus
TARIFS_TTC_APRES = {"HC": 0.1635, "HP": 0.2081}  # à partir du 01/08/2025
DATE_BASCULE = pd.Timestamp(2025, 8, 1).date()

def tarifs_ttc_pour(date_obj):
    return TARIFS_TTC_APRES if date_obj >= DATE_BASCULE else TARIFS_TTC_AVANT

def tarifs_ht_depuis_ttc(tarifs_ttc):
    return {k: v / DIV_TVA for k, v in tarifs_ttc.items()}

# =========================
# 📁 Persistance locale des annexes (PDF)
# =========================
STORAGE_DIR = os.path.join(os.getcwd(), "storage")
DEFAULT_CERT_PATH = os.path.join(STORAGE_DIR, "default_certificat.pdf")
DEFAULT_EDF_PATH  = os.path.join(STORAGE_DIR, "default_facture_electricite.pdf")
os.makedirs(STORAGE_DIR, exist_ok=True)

def save_default_pdf(uploaded_file, dest_path):
    if uploaded_file is None:
        return False
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return True

def load_default_pdf(path):
    return path if os.path.exists(path) and os.path.getsize(path) > 0 else None

# =========================
# 🔧 Utilitaires
# =========================
def parse_minutes(val):
    """'6 hr 26 min' / '5 min 3 sec' -> minutes (arrondi à la minute sup si sec > 0)."""
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
    """HC : 00:06–06:06 et 15:06–17:06 (inclusifs)."""
    h, m = dt.hour, dt.minute
    if (h > 0 or (h == 0 and m >= 6)) and (h < 6 or (h == 6 and m <= 6)):
        return True
    if (h > 15 or (h == 15 and m >= 6)) and (h < 17 or (h == 17 and m <= 6)):
        return True
    return False

def calcul_hp_hc(start_time, end_time, active_minutes, energy_kwh):
    """
    Ventile l'énergie totale E sur la fenêtre [start_time, end_time] proportionnellement
    au nombre de minutes en HC/HP. Robuste si la charge active est morcelée.
    Renvoie (kWh_HP, kWh_HC).
    """
    if energy_kwh <= 0:
        return 0.0, 0.0
    # minutes totales sur la fenêtre (au moins 1 minute)
    total_minutes = int(max(1, (end_time - start_time).total_seconds() // 60))
    t = pd.to_datetime(start_time).floor("min")
    hc_minutes = 0
    for _ in range(total_minutes):
        if est_hc(t):
            hc_minutes += 1
        t += pd.Timedelta(minutes=1)
    hp_minutes = total_minutes - hc_minutes
    kwh_hc = round(energy_kwh * (hc_minutes / total_minutes), 2)
    kwh_hp = round(energy_kwh - kwh_hc, 2)  # absorbe l'arrondi
    return kwh_hp, kwh_hc

def co2_evite_from_kwh(total_kwh: float):
    """Estimation simple : Scenic ~16.5 kWh/100 km ; gain vs diesel ~75 g CO2/km."""
    km = int(round(total_kwh / 0.165))      # km ≈ kWh / 0.165
    co2_kg = int(round(km * 0.075))         # 75 g/km -> 0.075 kg/km
    arbres = max(1, int(round(co2_kg / 25.0)))  # ~25 kgCO2/an par arbre
    return km, co2_kg, arbres

def safe_wh_to_kwh(val):
    """Convertit un champ 'Énergie consommée (Wh)' en kWh (float) en tolérant virgules/strings."""
    if pd.isna(val):
        return 0.0
    try:
        # remplace éventuelle virgule décimale
        x = float(str(val).replace(",", "."))
    except:
        x = 0.0
    return x / 1000.0

# =========================
# 🧾 Génération PDF (mise en page alignée)
# =========================
def generate_facture(df, vehicule, mois, certif_path=None, edf_path=None):
    tmpdir = tempfile.mkdtemp()
    out_name = f"facture_complete_{vehicule}_{mois}.pdf"
    pdf_path = os.path.join(tmpdir, out_name)

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=24, leftMargin=24, topMargin=28, bottomMargin=28)
    elements = []

    # Titre
    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", TITLE))
    elements.append(Spacer(1, 10))

    # Émetteur / Client
    emetteur = Paragraph("<b>Émetteur :</b><br/>Wesley MARSTON<br/>5 clairière des vernedes<br/>83480 Puget sur Argens", NORMAL)
    client = Paragraph("<b>Facture à :</b><br/>ALKERN France<br/>Rue André Bigotte<br/>Z.I. Parc de la motte au bois<br/>62440 Harnes", NORMAL)
    t_info = Table([[emetteur, client]], colWidths=[260, 260])  # 520
    t_info.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BOX",(0,0),(-1,-1),0.5,colors.black),
        ("BACKGROUND",(0,0),(-1,-1), colors.whitesmoke)
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 8))

    # Infos facture
    infos = [
        [Paragraph(f"<b>Facture n°:</b> {datetime.now().strftime('%Y%m%d')}-{vehicule}", NORMAL),
         Paragraph(f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}", NORMAL)],
        [Paragraph(f"<b>Période :</b> {mois}", NORMAL),
         Paragraph(f"<b>Véhicule :</b> {vehicule}", NORMAL)],
    ]
    t_infos = Table(infos, colWidths=[260, 260])  # 520
    t_infos.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#f2f2f2")),
        ("GRID",(0,0),(-1,-1),0.5, colors.black)
    ]))
    elements.append(t_infos)
    elements.append(Spacer(1, 12))

    # ========= 1) HISTORIQUE DES CHARGES =========
    headers_hist = ["Date", "Début", "Fin", "Durée", "kWh HP", "kWh HC", "Total kWh"]
    rows_hist = [headers_hist]

    total_hp_kwh = 0.0
    total_hc_kwh = 0.0
    total_kwh    = 0.0

    for _, row in df.iterrows():
        d_deb = row["Date/heure de début"]
        if pd.isna(d_deb):
            continue

        # Durée effective -> minutes
        duree_min = parse_minutes(row["Temps de charge active"])
        # Heure de fin = début + durée effective (IGNORER la colonne fin d'origine)
        d_fin = d_deb + pd.Timedelta(minutes=int(duree_min))

        debut_txt = d_deb.strftime("%Hh%M")
        fin_txt   = d_fin.strftime("%Hh%M")
        h, m = divmod(int(duree_min), 60)
        duree_txt = f"{h}h{m:02d}"

        # Énergie totale de la session (kWh)
        kwh_total = safe_wh_to_kwh(row["Énergie consommée (Wh)"])

        # Ventilation proportionnelle sur la fenêtre [début -> fin]
        kwh_hp, kwh_hc = calcul_hp_hc(d_deb, d_fin, duree_min, kwh_total)

        rows_hist.append([
            d_deb.strftime("%d/%m/%Y"), debut_txt, fin_txt, duree_txt,
            f"{kwh_hp:.2f}", f"{kwh_hc:.2f}", f"{kwh_total:.2f}"
        ])
        total_hp_kwh += kwh_hp
        total_hc_kwh += kwh_hc
        total_kwh    += kwh_total

    colw_hist = [100, 60, 60, 70, 75, 75, 80]  # somme 520
    t_hist = Table(rows_hist, repeatRows=1, colWidths=colw_hist)
    t_hist.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#8DC63F")),
        ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("FONTNAME",(0,0),(-1,0), "Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.whitesmoke, colors.white]),
        ("ALIGN",(0,0),(3,-1),"LEFT"),
        ("ALIGN",(4,0),(6,-1),"RIGHT"),
        ("FONTSIZE",(0,0),(-1,0),10.5),
        ("FONTSIZE",(0,1),(-1,-1),10),
    ]))
    elements.append(Paragraph("<b>Historique des charges</b>", HEADER))
    elements.append(t_hist)
    elements.append(Spacer(1, 12))

    # ========= 2) DÉTAIL DE LA FACTURATION =========
    # Tarifs du mois (on prend la date du 1er enregistrement filtré)
    first_date = df.iloc[0]["Date/heure de début"].date() if not df.empty else DATE_BASCULE
    tarifs_ttc = tarifs_ttc_pour(first_date)
    tarifs_ht  = tarifs_ht_depuis_ttc(tarifs_ttc)

    montant_ht_hc = total_hc_kwh * tarifs_ht["HC"]
    montant_ht_hp = total_hp_kwh * tarifs_ht["HP"]

    detail_headers = ["Détail", "Total (kWh)", "PU HT (€/kWh)", "Total HT (€)"]
    rows_detail = [
        detail_headers,
        ["Heures creuses (HC)", f"{total_hc_kwh:.2f}", f"{tarifs_ht['HC']:.5f}", f"{montant_ht_hc:.2f}"],
        ["Heures pleines (HP)", f"{total_hp_kwh:.2f}", f"{tarifs_ht['HP']:.5f}", f"{montant_ht_hp:.2f}"],
    ]
    colw_detail = [220, 90, 100, 110]  # 520
    t_detail = Table(rows_detail, repeatRows=1, colWidths=colw_detail)
    t_detail.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#8DC63F")),
        ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("FONTNAME",(0,0),(-1,0), "Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.whitesmoke, colors.white]),
        ("ALIGN",(0,0),(0,-1),"LEFT"),
        ("ALIGN",(1,0),(3,-1),"RIGHT"),
        ("FONTSIZE",(0,0),(-1,0),10.5),
        ("FONTSIZE",(0,1),(-1,-1),10),
    ]))
    elements.append(Paragraph("<b>Détail de la facturation</b>", HEADER))
    elements.append(t_detail)
    elements.append(Spacer(1, 10))

    # ========= 3) Totaux =========
    total_ht = montant_ht_hc + montant_ht_hp
    tva_amount = total_ht * TVA_RATE
    total_ttc  = total_ht + tva_amount

    recap = [
        ["Total HT",                f"{total_ht:.2f} €"],
        [f"TVA ({int(TVA_RATE*100)}%)", f"{tva_amount:.2f} €"],
        ["Total TTC",               f"{total_ttc:.2f} €"],
    ]
    t_recap = Table(recap, colWidths=[350, 170])  # 520
    t_recap.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
        ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#fff2cc")),
        ("TEXTCOLOR",(0,-1),(-1,-1), colors.HexColor("#b30000")),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
    ]))
    elements.append(t_recap)
    elements.append(Spacer(1, 12))

    # ========= 4) Conditions tarifaires =========
    conditions = [
        [Paragraph("<b>Conditions tarifaires</b>", HEADER)],
        [Paragraph("Heures creuses : 00h06–06h06 et 15h06–17h06", NORMAL)],
        [Paragraph("Tarifs fournis TTC (HC/HP). Les montants HT sont calculés avec PU HT = PU TTC / 1,20 ; puis TVA 20 %.", NORMAL)],
        [Paragraph("Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh (TTC)", NORMAL)],
        [Paragraph("À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh (TTC)", NORMAL)],
    ]
    t_conditions = Table(conditions, colWidths=[TOTAL_WIDTH])
    t_conditions.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
    ]))
    elements.append(t_conditions)
    elements.append(Spacer(1, 10))

    # ========= 5) Chargeur =========
    chargeur = [
        [Paragraph("<b>Chargeur</b>", HEADER)],
        [Paragraph("Enphase IQ-EVSE-EU-3032", NORMAL)],
        [Paragraph("Numéro de série : 202451008197", NORMAL)],
        [Paragraph("Conforme aux directives MID, LVD, EMC, RED, RoHS", NORMAL)],
    ]
    t_chargeur = Table(chargeur, colWidths=[TOTAL_WIDTH])
    t_chargeur.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
    ]))
    elements.append(t_chargeur)
    elements.append(Spacer(1, 10))

    # ========= 6) Impact CO2 =========
    km, co2kg, arbres = co2_evite_from_kwh(total_kwh)
    co2_tab = [
        [Paragraph("Impact CO<sub>2</sub> évité", HEADER)],
        [Paragraph(f"Distance estimée parcourue : {km} km", NORMAL)],
        [Paragraph(f"CO<sub>2</sub> évité : {co2kg} kg", NORMAL)],
        [Paragraph(f"Arbres équivalents : {arbres}", NORMAL)],
    ]
    t_co2 = Table(co2_tab, colWidths=[TOTAL_WIDTH])
    t_co2.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5, colors.black),
    ]))
    elements.append(t_co2)

    # Génération du PDF principal
    doc.build(elements)

    # Fusion avec annexes si présentes
    merger = PdfMerger()
    merger.append(pdf_path)
    if certif_path and os.path.exists(certif_path):
        merger.append(certif_path)
    if edf_path and os.path.exists(edf_path):
        merger.append(edf_path)
    final_path = pdf_path.replace(".pdf", "_final.pdf")
    merger.write(final_path); merger.close()
    return final_path

# =========================
# 🚀 Interface Streamlit (sélection par MOIS + mémoire annexes)
# =========================
st.title("⚡ Facturation des recharges VE — Sélection par MOIS")

uploaded_csv = st.file_uploader("Chargez le fichier CSV", type=["csv"])

st.subheader("📎 Annexes (facultatif)")
colA, colB = st.columns(2)
with colA:
    uploaded_certif = st.file_uploader("Certificat de conformité (PDF)", type=["pdf"], key="cert")
with colB:
    uploaded_edf = st.file_uploader("Facture d’électricité (PDF)", type=["pdf"], key="edf")

memo = st.checkbox("Mémoriser ces fichiers comme défaut", value=False, help="Ils seront réutilisés automatiquement la prochaine fois.")
if memo:
    if uploaded_certif: save_default_pdf(uploaded_certif, DEFAULT_CERT_PATH)
    if uploaded_edf:    save_default_pdf(uploaded_edf, DEFAULT_EDF_PATH)

default_cert = load_default_pdf(DEFAULT_CERT_PATH)
default_edf  = load_default_pdf(DEFAULT_EDF_PATH)
st.caption(
    f"Certificat mémorisé : {'✅' if default_cert else '—'}  •  "
    f"Facture électricité mémorisée : {'✅' if default_edf else '—'}"
)

if uploaded_csv:
    df = pd.read_csv(uploaded_csv)

    # Conversions dates (on ignore la colonne "fin" d'origine et on la recalculera)
    df["Date/heure de début"] = pd.to_datetime(df["Date/heure de début"], errors="coerce")

    # Sélecteur véhicule
    vehicules = df["Authentification"].dropna().unique().tolist()
    if not vehicules:
        st.error("Aucun véhicule détecté (colonne 'Authentification').")
        st.stop()
    vehicule = st.selectbox("Choisissez le véhicule", vehicules)

    # Sélecteur mois (YYYY-MM)
    mois_dispos = sorted(df["Date/heure de début"].dt.strftime("%Y-%m").dropna().unique())
    mois = st.selectbox("Choisissez le mois de consommation", mois_dispos)

    # Filtrage par véhicule + mois + consommation > 0
    df_filtre = df[
        (df["Authentification"] == vehicule) &
        (df["Date/heure de début"].dt.strftime("%Y-%m") == mois) &
        (pd.to_numeric(df["Énergie consommée (Wh)"].astype(str).str.replace(",", "."), errors="coerce").fillna(0) > 0)
    ].copy()

    # Aperçu utile
    if not df_filtre.empty:
        apercu = df_filtre[["Date/heure de début","Énergie consommée (Wh)","Temps de charge active"]].copy()
        st.write("🔎 Aperçu des sessions filtrées", apercu.head())
    else:
        st.warning("Aucune session trouvée pour ce véhicule et ce mois.")

    if st.button("📄 Générer la facture PDF"):
        if df_filtre.empty:
            st.error("Aucune session trouvée pour ce véhicule et ce mois.")
        else:
            # Annexes : upload courant prioritaire, sinon défaut mémorisé
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
