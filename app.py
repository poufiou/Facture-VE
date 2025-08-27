
import streamlit as st
import pandas as pd
import unicodedata, re, io, os, tempfile
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Rect, Polygon
from PyPDF2 import PdfMerger

VERSION = "v8.0"

# --- Styles & couleurs (inspiré Alkern) ---
ALKERN_GREEN = colors.HexColor("#8DC63F")
ALKERN_GRAY  = colors.HexColor("#4D4D4D")
LIGHT_GRAY   = colors.HexColor("#f2f2f2")

styles = getSampleStyleSheet()
TITLE  = ParagraphStyle("Title", parent=styles["Title"], textColor=ALKERN_GREEN, fontSize=18, alignment=1)
NORMAL = ParagraphStyle("Normal", parent=styles["Normal"], textColor=ALKERN_GRAY, fontSize=10)
HEADER = ParagraphStyle("Header", parent=styles["Heading2"], textColor=ALKERN_GREEN, fontSize=12, spaceAfter=6)
CENTER = ParagraphStyle("Center", parent=styles["Normal"], alignment=1, fontSize=11, textColor=ALKERN_GRAY)

# --- Utilitaires CSV ---
def normalize_txt(x: str) -> str:
    if x is None:
        return ""
    x = str(x).replace("\\xa0", " ")
    x = "".join(c for c in unicodedata.normalize("NFKD", x) if not unicodedata.combining(c))
    return x.strip().lower()

def read_csv_safely(uploaded):
    for sep in [",",";","\\t"]:
        try:
            uploaded.seek(0)
            df = pd.read_csv(uploaded, sep=sep, engine="python")
            if df.shape[1] > 1:
                return df
        except Exception:
            pass
    uploaded.seek(0)
    return pd.read_csv(uploaded, engine="python")

def find_column(cols, *keywords):
    cols_norm = {normalize_txt(c): c for c in cols}
    for key in keywords:
        k = normalize_txt(key)
        for cn, co in cols_norm.items():
            if k in cn:
                return co
    return None

def parse_temps_actif(s: str) -> int:
    if pd.isna(s): return 0
    s = str(s).lower()
    total = 0
    hr = re.search(r"(\\d+)\\s*hr", s)
    mn = re.search(r"(\\d+)\\s*min", s)
    sc = re.search(r"(\\d+)\\s*sec", s)
    if hr: total += int(hr.group(1))*3600
    if mn: total += int(mn.group(1))*60
    if sc: total += int(sc.group(1))
    return total

def fmt_hhmm(seconds: int) -> str:
    if seconds <= 0: return "0h00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h{m:02d}"

# --- Tarifs / HC ---
def get_tarifs(date):
    seuil = datetime(2025,8,1)
    return {"HC":0.1635,"HP":0.2081} if date>=seuil else {"HC":0.1696,"HP":0.2146}

def is_hc(time):
    minutes = time.hour*60 + time.minute
    return (6 <= minutes < 366) or (906 <= minutes < 1026)  # 00:06-06:06 et 15:06-17:06

def compute_cost(start, active_seconds, kWh_total):
    if kWh_total<=0 or pd.isna(start) or active_seconds<=0:
        return 0.0, 0.0, 0.0
    kwh_per_sec = kWh_total / active_seconds
    kwh_hc = kwh_hp = 0.0
    cur = start
    remaining = active_seconds
    while remaining>0:
        step = min(60, remaining)     # résolution: 1 minute
        chunk = kwh_per_sec*step
        if is_hc(cur.time()): kwh_hc += chunk
        else:                  kwh_hp += chunk
        cur += timedelta(seconds=step)
        remaining -= step
    tarifs = get_tarifs(start)
    return kwh_hc, kwh_hp, kwh_hc*tarifs["HC"] + kwh_hp*tarifs["HP"]

# --- Dessin d'arbres (vectoriel, pas d'emoji) ---
def make_trees_flowable(n: int):
    if n<=0: n=1
    n = int(min(max(n,1), 30))  # limiter pour rester lisible
    w = 14*n
    h = 18
    d = Drawing(w, h)
    for i in range(n):
        x = i*14 + 2
        # tronc
        d.add(Rect(x+4, 2, 4, 6, strokeColor=ALKERN_GRAY, fillColor=colors.brown))
        # feuillage (triangle)
        d.add(Polygon(points=[x+6,16, x,8, x+12,8], strokeColor=ALKERN_GREEN, fillColor=ALKERN_GREEN))
    return d

# --- Génération de la facture PDF ---
def build_pdf(df, mois_selection, selected_auth, annexe_file=None):
    # Colonnes
    c_start = find_column(df.columns, "date/heure de debut", "date/heure de début", "start")
    c_end   = find_column(df.columns, "date/heure de fin", "fin", "end")
    c_energy= find_column(df.columns, "energie", "énergie", "wh", "kwh")
    c_auth  = find_column(df.columns, "authentification", "auth")
    c_active= find_column(df.columns, "temps de charge active", "active")

    if None in [c_start, c_end, c_energy, c_auth]:
        return None, "Colonnes manquantes dans le CSV. Il faut au minimum: Début, Fin, Énergie, Authentification."

    # Normalisations
    df[c_start]  = pd.to_datetime(df[c_start], errors="coerce")
    df[c_end]    = pd.to_datetime(df[c_end],   errors="coerce")
    df[c_energy] = pd.to_numeric(df[c_energy], errors="coerce")
    if c_active:
        df["active_sec"] = df[c_active].apply(parse_temps_actif)
    else:
        # fallback sur différence fin - début
        df["active_sec"] = (df[c_end]-df[c_start]).dt.total_seconds().fillna(0).astype(int)

    # Filtres
    auth_norm = df[c_auth].astype(str).map(normalize_txt)
    veh_norm = normalize_txt(selected_auth or "")
    mask_vehicle = auth_norm.str.contains(veh_norm, na=False) if veh_norm else (auth_norm!="")
    dfv = df[mask_vehicle & (df[c_energy]>0) & (df["active_sec"]>0)].copy()
    dfv["YYYY-MM"] = dfv[c_start].dt.strftime("%Y-%m")
    dfv = dfv[dfv["YYYY-MM"]==mois_selection]
    if dfv.empty:
        return None, "Aucune session pour ce mois et ce véhicule."

    # Sessions calculées
    sessions = []
    total_HT = 0.0
    for _, r in dfv.iterrows():
        start = r[c_start]
        active = int(r["active_sec"])
        end = r[c_end] if pd.notna(r[c_end]) else (start + timedelta(seconds=active))
        kwh = (r[c_energy] or 0)/1000.0
        kwh_hc, kwh_hp, cost = compute_cost(start, active, kwh)
        tar = get_tarifs(start)
        sessions.append({
            "date": start.strftime("%d/%m/%Y"),
            "debut": start.strftime("%Hh%M"),
            "fin": end.strftime("%Hh%M"),
            "duree": fmt_hhmm(active),
            "kWh_total": kwh, "kWh_HC": kwh_hc, "kWh_HP": kwh_hp,
            "tarif_HC": tar["HC"], "tarif_HP": tar["HP"], "cout": cost
        })
        total_HT += cost

    total_kWh = sum(s["kWh_total"] for s in sessions)
    tva = total_HT*0.20
    total_TTC = total_HT + tva

    # CO2
    km_estimes = total_kWh / 0.165          # 16.5 kWh / 100 km
    co2_diesel = km_estimes*120/1000        # kg
    co2_ev     = km_estimes*4.5/1000        # kg
    gain_co2   = max(co2_diesel - co2_ev, 0)
    arbres_eq  = int(round(gain_co2/25))

    # --- Build PDF ---
    tmpdir = tempfile.mkdtemp()
    pdf_path = os.path.join(tmpdir, f"facture_complete_HD-803-PZ_{mois_selection}.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)

    elements = []
    elements.append(Paragraph("FACTURE DE RECHARGE VEHICULE ELECTRIQUE", TITLE))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(f"<i>Version facture : {VERSION}</i>", ParagraphStyle("small", parent=NORMAL, fontSize=8, textColor=ALKERN_GRAY)))
    elements.append(Spacer(1, 14))

    # Emétteur / Client
    emetteur = Paragraph("<b>Émetteur :</b><br/>Wesley MARSTON<br/>5 clairière des vernedes<br/>83480 Puget sur Argens", NORMAL)
    client = Paragraph("<b>Facture à :</b><br/>ALKERN France<br/>Rue André Bigotte<br/>Z.I. Parc de la motte au bois<br/>62440 Harnes", NORMAL)
    table_info = Table([[emetteur, client]], colWidths=[250, 250])
    table_info.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                                    ("BOX",(0,0),(-1,-1),0.5,colors.black),
                                    ("BACKGROUND",(0,0),(-1,-1), colors.whitesmoke)]))
    elements.append(table_info)
    elements.append(Spacer(1, 12))

    # Infos générales
    infos = [
        [Paragraph(f"<b>Facture n°:</b> {mois_selection}-HD-803-PZ", NORMAL),
         Paragraph(f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y')}", NORMAL)],
        [Paragraph(f"<b>Période :</b> {mois_selection}", NORMAL),
         Paragraph("<b>Véhicule :</b> Scenic HD-803-PZ", NORMAL)],
    ]
    t_infos = Table(infos, colWidths=[250,250])
    t_infos.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1), LIGHT_GRAY),
                                 ("GRID",(0,0),(-1,-1),0.5, colors.black)]))
    elements.append(t_infos)
    elements.append(Spacer(1, 12))

    # Tableau sessions
    headers = ["Date","Début","Fin","Durée","kWh total","kWh HC","kWh HP","Tarif HC","Tarif HP","Montant (€)"]
    data = [headers]
    for s in sessions:
        data.append([s["date"], s["debut"], s["fin"], s["duree"],
                     f"{s['kWh_total']:.2f}", f"{s['kWh_HC']:.2f}", f"{s['kWh_HP']:.2f}",
                     f"{s['tarif_HC']:.4f}", f"{s['tarif_HP']:.4f}", f"{s['cout']:.2f}"])
    t = Table(data, repeatRows=1, colWidths=[60,50,50,50,55,55,55,55,55,60])
    ts = TableStyle([("BACKGROUND",(0,0),(-1,0), ALKERN_GREEN),
                     ("TEXTCOLOR",(0,0),(-1,0), colors.white),
                     ("ALIGN",(4,1),(-1,-1),"RIGHT"),
                     ("GRID",(0,0),(-1,-1),0.5, colors.black)])
    for i in range(1, len(data)):
        if i%2==0: ts.add("BACKGROUND",(0,i),(-1,i), LIGHT_GRAY)
    t.setStyle(ts)
    elements.append(t)
    elements.append(Spacer(1, 12))

    # Récap
    recap = [["Total énergie consommée", f"{total_kWh:.2f} kWh"],
             ["Total HT", f"{total_HT:.2f} €"],
             ["TVA (20%)", f"{(total_HT*0.20):.2f} €"],
             ["Total TTC", f"{(total_HT*1.20):.2f} €"]]
    t_recap = Table(recap, colWidths=[220,120])
    t_recap.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5, colors.black),
                                 ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#fff2cc")),
                                 ("TEXTCOLOR",(0,-1),(-1,-1), colors.HexColor("#b30000")),
                                 ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold")]))
    elements.append(t_recap)
    elements.append(Spacer(1, 10))

    # Conditions
    elements.append(Paragraph("Conditions tarifaires", HEADER))
    elements.append(Paragraph("Heures creuses : 00h06 - 06h06 et 15h06 - 17h06<br/>"
                              "Tarifs appliqués :<br/>"
                              "Avant 01/08/2025 → HC : 0,1696 €/kWh | HP : 0,2146 €/kWh<br/>"
                              "À partir du 01/08/2025 → HC : 0,1635 €/kWh | HP : 0,2081 €/kWh", NORMAL))
    elements.append(Spacer(1, 8))

    # Chargeur
    elements.append(Paragraph("Chargeur", HEADER))
    elements.append(Paragraph("Enphase IQ-EVSE-EU-3032<br/>Numéro de série : 202451008197<br/>"
                              "Conforme aux directives MID, LVD, EMC, RED, RoHS", NORMAL))
    elements.append(Spacer(1, 10))

    # Impact CO2
    elements.append(Paragraph("🌍 Impact CO₂ évité", HEADER))
    elements.append(Paragraph(f"Distance estimée parcourue : {km_estimes:,.0f} km", NORMAL))
    elements.append(Paragraph(f"CO₂ évité : {gain_co2:,.0f} kg", NORMAL))
    elements.append(Spacer(1, 6))
    elements.append(make_trees_flowable(arbres_eq))
    elements.append(Paragraph(f"({arbres_eq} arbres équivalents)", CENTER))

    doc.build(elements)

    # Fusion avec annexe si fournie
    final_pdf = pdf_path
    if annexe_file is not None:
        ann_tmp = os.path.join(tmpdir, "annexe.pdf")
        with open(ann_tmp, "wb") as out:
            out.write(annexe_file.read())
        merged = os.path.join(tmpdir, f"facture_complete_HD-803-PZ_{mois_selection}.pdf")
        merger = PdfMerger()
        merger.append(pdf_path)
        merger.append(ann_tmp)
        merger.write(merged)
        merger.close()
        final_pdf = merged

    return final_pdf, None

# ---------------- Interface ----------------
st.title("📄 Générateur de factures de recharge VE")
st.caption(f"Version de l'outil : {VERSION}")

csv_file = st.file_uploader("Déposez votre CSV (export Enphase)", type=["csv"])
annexe = st.file_uploader("Déclaration de conformité (PDF) — optionnel", type=["pdf"])

if csv_file is not None:
    df = read_csv_safely(csv_file)

    # Détection des colonnes
    c_auth = find_column(df.columns, "authentification", "auth")
    c_start_guess = find_column(df.columns, "date/heure de debut", "date/heure de début", "start")

    st.write("Colonnes détectées :", list(df.columns))

    # Sélecteur de véhicule / badge
    veh_options = []
    if c_auth:
        veh_options = sorted(df[c_auth].dropna().astype(str).unique().tolist())
    selected_auth = st.selectbox("Véhicule / badge à facturer", options=veh_options or ["Tous"], index=(veh_options.index("Scenic") if "Scenic" in veh_options else 0))

    # Mois disponible
    if c_start_guess:
        dates = pd.to_datetime(df[c_start_guess], errors="coerce")
        mois = sorted(dates.dt.strftime("%Y-%m").dropna().unique().tolist())
    else:
        mois = [datetime.now().strftime("%Y-%m")]
    mois_selection = st.selectbox("Mois de consommation", options=mois or [datetime.now().strftime("%Y-%m")])

    # Aperçu
    if c_auth and c_start_guess:
        mask = df[c_auth].astype(str).str.contains(selected_auth, na=False) if selected_auth!="Tous" else (df[c_auth].astype(str)!="")
        df_preview = df.loc[mask, [c_start_guess, find_column(df.columns,"date/heure de fin","fin","end"), find_column(df.columns,"energie","énergie","wh","kwh"), c_auth]].head(20)
        st.subheader("🔎 Aperçu des sessions filtrées")
        st.dataframe(df_preview)

    if st.button("📄 Générer la facture PDF"):
        output, err = build_pdf(df, mois_selection, selected_auth if selected_auth!="Tous" else "", annexe_file=annexe)
        if err:
            st.error("⚠️ " + err)
        else:
            with open(output, "rb") as f:
                st.download_button("⬇️ Télécharger la facture PDF", f, file_name=os.path.basename(output), mime="application/pdf")
