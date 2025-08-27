import streamlit as st
import pandas as pd
import unicodedata
import re
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from PyPDF2 import PdfMerger
import tempfile
import os

# === Paramètres fixes ===
IMMATRICULATION = "HD-803-PZ"

# === Fonctions utilitaires ===
def normalize_txt(x: str) -> str:
    if x is None:
        return ""
    x = str(x)
    x = x.replace("\xa0", " ")  # NBSP -> space
    x = "".join(c for c in unicodedata.normalize("NFKD", x) if not unicodedata.combining(c))
    return x.strip().lower()

def read_csv_safely(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file, sep=",", quotechar='"', encoding="utf-8")
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    uploaded_file.seek(0)
    try:
        df = pd.read_csv(uploaded_file, sep=";", encoding="utf-8")
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    uploaded_file.seek(0)
    return pd.read_csv(uploaded_file, engine="python")

def find_column(cols, *keywords):
    cols_norm = {normalize_txt(c): c for c in cols}
    for key in keywords:
        k = normalize_txt(key)
        for cnorm, corig in cols_norm.items():
            if k in cnorm:
                return corig
    return None

def parse_temps_actif(s: str) -> int:
    if pd.isna(s):
        return 0
    s = str(s).lower()
    total = 0
    hr = re.search(r"(\d+)\s*hr", s)
    mn = re.search(r"(\d+)\s*min", s)
    sc = re.search(r"(\d+)\s*sec", s)
    if hr:
        total += int(hr.group(1)) * 3600
    if mn:
        total += int(mn.group(1)) * 60
    if sc:
        total += int(sc.group(1))
    return total

def get_tarifs(date):
    seuil = datetime(2025, 8, 1)
    if date >= seuil:
        return {"HC": 0.1635, "HP": 0.2081}
    else:
        return {"HC": 0.1696, "HP": 0.2146}

def is_hc(time):
    minutes = time.hour * 60 + time.minute
    return (6 <= minutes < 366) or (906 <= minutes < 1026)

def compute_cost(start, active_seconds, kWh_total):
    if kWh_total <= 0 or pd.isna(start) or active_seconds <= 0:
        return 0.0, 0.0, 0.0
    kWh_per_sec = kWh_total / active_seconds
    kWh_hc, kWh_hp = 0.0, 0.0
    cur = start
    remaining = active_seconds
    while remaining > 0:
        step = min(60, remaining)
        kwh_chunk = kWh_per_sec * step
        if is_hc(cur.time()):
            kWh_hc += kwh_chunk
        else:
            kWh_hp += kwh_chunk
        cur += timedelta(seconds=step)
        remaining -= step
    tarifs = get_tarifs(start)
    cost = kWh_hc * tarifs["HC"] + kWh_hp * tarifs["HP"]
    return kWh_hc, kWh_hp, cost

def generate_facture(df, annexe_file, mois_selection, vehicule_value, cols):
    col_start, col_end, col_energy, col_auth, col_active = cols
    df[col_start] = pd.to_datetime(df[col_start], errors="coerce")
    df[col_energy] = pd.to_numeric(df[col_energy], errors="coerce")
    df["active_sec"] = df[col_active].apply(parse_temps_actif)
    auth_norm = df[col_auth].astype(str).apply(normalize_txt)
    veh_norm = normalize_txt(vehicule_value)
    mask_vehicle = auth_norm.str.contains(veh_norm, na=False)
    dfv = df[mask_vehicle & (df[col_energy] > 0) & (df["active_sec"] > 0)].copy()
    dfv["YYYY-MM"] = dfv[col_start].dt.strftime("%Y-%m")
    dfv = dfv[dfv["YYYY-MM"] == mois_selection]
    if dfv.empty:
        return None
    dfv["kWh"] = dfv[col_energy] / 1000.0
    sessions, total_HT = [], 0.0
    for _, row in dfv.iterrows():
        kwh_hc, kwh_hp, cost = compute_cost(row[col_start], row["active_sec"], row["kWh"])
        sessions.append({
            "debut": row[col_start].strftime("%d/%m/%Y %Hh%M") if not pd.isna(row[col_start]) else "",
            "fin": row[col_end] if not pd.isna(row[col_end]) else "",
            "duree": str(timedelta(seconds=row["active_sec"])),
            "kWh_total": row["kWh"],
            "kWh_HC": kwh_hc,
            "kWh_HP": kwh_hp,
            "tarif_HC": get_tarifs(row[col_start])["HC"],
            "tarif_HP": get_tarifs(row[col_start])["HP"],
            "cout": cost
        })
        total_HT += cost
    total_kWh = sum(s["kWh_total"] for s in sessions)
    tva, total_TTC = total_HT * 0.20, total_HT * 1.20

    # === Estimation CO2 évité ===
    km_estimes = total_kWh / 0.165
    co2_diesel = km_estimes * 120 / 1000
    co2_ev = km_estimes * 4.5 / 1000
    gain_co2 = co2_diesel - co2_ev
    arbres_eq = int(round(gain_co2 / 25))

    # === Génération PDF ===
    tmpdir = tempfile.mkdtemp()
    facture_file = os.path.join(tmpdir, f"facture_{IMMATRICULATION}_{mois_selection}.pdf")
    doc = SimpleDocTemplate(facture_file, pagesize=A4)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], textColor=colors.HexColor("#8DC63F"), fontSize=18, alignment=1)
    normal_style = ParagraphStyle("Normal", parent=styles["Normal"], textColor=colors.HexColor("#4D4D4D"), fontSize=10)
    header_style = ParagraphStyle("Header", parent=styles["Heading2"], textColor=colors.HexColor("#8DC63F"), fontSize=11, spaceAfter=6)

    elements = []
    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", title_style))
    elements.append(Spacer(1, 18))

    table_info = Table([[
        "<b>Émetteur :</b><br/>Wesley MARSTON<br/>5 clairière des vernedes<br/>83480 Puget sur Argens",
        "<b>Facture à :</b><br/>ALKERN France<br/>Rue André Bigotte<br/>Z.I. Parc de la motte au bois<br/>62440 Harnes"
    ]], colWidths=[250, 250])
    table_info.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    elements.append(table_info)
    elements.append(Spacer(1, 18))

    infos = [[f"<b>Facture n°:</b> {mois_selection}-{IMMATRICULATION}",
              f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}",
              f"<b>Période :</b> {mois_selection}",
              f"<b>Véhicule :</b> Scenic {IMMATRICULATION}"]]
    table_infos = Table(infos, colWidths=[120, 100, 150, 150])
    table_infos.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f2f2f2")),
                                     ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#4D4D4D")),
                                     ("GRID", (0,0), (-1,-1), 0.5, colors.black)]))
    elements.append(table_infos)
    elements.append(Spacer(1, 18))

    table_data = [["Début", "Fin", "Durée", "kWh total", "kWh HC", "kWh HP", "Tarif HC", "Tarif HP", "Montant (€)"]]
    for s in sessions:
        table_data.append([s["debut"], s["fin"], s["duree"], f"{s['kWh_total']:.2f}", f"{s['kWh_HC']:.2f}",
                           f"{s['kWh_HP']:.2f}", f"{s['tarif_HC']:.4f}", f"{s['tarif_HP']:.4f}", f"{s['cout']:.2f}"])
    table = Table(table_data, repeatRows=1, colWidths=[75,75,55,55,55,55,55,55,65])
    table_style = TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#8DC63F")),
                              ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                              ("ALIGN", (3,1), (-1,-1), "RIGHT"),
                              ("GRID", (0,0), (-1,-1), 0.5, colors.black)])
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            table_style.add("BACKGROUND", (0,i), (-1,i), colors.HexColor("#f2f2f2"))
    table.setStyle(table_style)
    elements.append(table)
    elements.append(Spacer(1, 18))

    recap = [["Total énergie consommée", f"{total_kWh:.2f} kWh"],
             ["Total HT", f"{total_HT:.2f} €"],
             ["TVA (20%)", f"{tva:.2f} €"],
             ["Total TTC", f"{total_TTC:.2f} €"]]
    recap_table = Table(recap, colWidths=[220, 120])
    recap_table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.black),
                                     ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#fff2cc")),
                                     ("TEXTCOLOR", (0,-1), (-1,-1), colors.HexColor("#b30000")),
                                     ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold")]))
    elements.append(recap_table)
    elements.append(Spacer(1, 18))

    elements.append(Paragraph("Conditions tarifaires", header_style))
    elements.append(Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06<br/>"
                              "Tarifs appliqués :<br/>"
                              "Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh<br/>"
                              "À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh", normal_style))
    elements.append(Spacer(1, 18))

    elements.append(Paragraph("Chargeur", header_style))
    elements.append(Paragraph("Enphase IQ-EVSE-EU-3032<br/>"
                              "Numéro de série : 202451008197<br/>"
                              "Conforme aux directives MID, LVD, EMC, RED, RoHS", normal_style))
    elements.append(Spacer(1, 18))

    elements.append(Paragraph("🌍 Impact CO₂ évité", header_style))
    elements.append(Paragraph(f"Distance estimée parcourue : {km_estimes:,.0f} km<br/>"
                              f"CO₂ évité : {gain_co2:,.0f} kg", normal_style))
    elements.append(Paragraph("🌳" * arbres_eq + f" ({arbres_eq} arbres équivalents)", normal_style))

    doc.build(elements)

    final_pdf = os.path.join(tmpdir, f"facture_complete_{IMMATRICULATION}_{mois_selection}.pdf")
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
    st.subheader("🗂️ Colonnes détectées")
    st.write(list(df.columns))
    col_start = find_column(df.columns, "debut", "start")
    col_end = find_column(df.columns, "fin", "end")
    col_energy = find_column(df.columns, "energie", "énergie", "wh", "kwh")
    col_auth = find_column(df.columns, "auth")
    col_active = find_column(df.columns, "temps de charge active", "active")
    if None in [col_start, col_end, col_energy, col_auth, col_active]:
        st.error("Colonnes manquantes. Vérifiez le fichier CSV.")
    else:
        uniques = sorted(df[col_auth].dropna().astype(str).unique().tolist())
        vehicule_value = st.selectbox("Choisissez le véhicule", options=uniques)
        df_dates = pd.to_datetime(df[col_start], errors="coerce")
        mois_dispo = sorted(df_dates.dt.strftime("%Y-%m").dropna().unique().tolist())
        mois_selection = st.selectbox("Mois de consommation", options=mois_dispo or [datetime.now().strftime("%Y-%m")])
        st.subheader("🔎 Aperçu sessions du véhicule")
        mask_vehicle = df[col_auth].astype(str).str.contains(vehicule_value, na=False)
        st.dataframe(df.loc[mask_vehicle, [col_start, col_end, col_energy, col_auth, col_active]].head(50))
        if uploaded_annexe is not None and st.button("📄 Générer la facture"):
            output_pdf = generate_facture(df, uploaded_annexe, mois_selection, vehicule_value,
                                          (col_start, col_end, col_energy, col_auth, col_active))
            if output_pdf is None:
                st.error("⚠️ Aucune session trouvée pour ce mois et ce véhicule avec énergie > 0.")
            else:
                with open(output_pdf, "rb") as f:
                    st.download_button("⬇️ Télécharger la facture PDF", f, file_name=os.path.basename(output_pdf))
