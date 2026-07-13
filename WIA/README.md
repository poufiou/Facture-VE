# WIA — Wesley Investment Analytics

WIA est un projet Python 3.12 destiné à devenir un logiciel d'analyse patrimoniale spécialisé dans les cryptomonnaies.

## Objectif

Fournir une base professionnelle, propre, documentée et évolutive pour :

- importer des données issues de plateformes crypto ;
- normaliser et consolider les transactions ;
- analyser un portefeuille patrimonial crypto ;
- visualiser les performances via une interface Streamlit ;
- produire des rapports exploitables.

> À ce stade, le projet contient uniquement l'architecture initiale. Aucune fonctionnalité métier n'est implémentée.

## Stack prévue

- Python 3.12
- Streamlit
- Pandas
- Plotly
- SQLite
- Pytest

## Structure du projet

```text
WIA/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── .gitignore
├── imports/
├── engine/
├── database/
├── dashboard/
├── reports/
├── tests/
└── data/
```

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
streamlit run app.py
```

## Tests

```bash
pytest
```
