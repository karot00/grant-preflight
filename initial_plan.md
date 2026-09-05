# Grant Scout & Drafter

## This is a suggestion for project scope and implementation plan. It needs refinement and more accuracy. 

## This project is done for DEV Weekend Challenge: https://dev.to/devteam/join-our-dev-weekend-challenge-generosity-edition-1000-in-prizes-across-five-winners-20en?bb=264290

Objective
Build a Streamlit Python web application called Grant Scout & Drafter. The app helps non-profits (specifically health/charity organizations like the Heart Association) discover grant opportunities, match them against organizational profiles, and generate AI-driven application drafts.

Target Deployment Domain: grant-preflight.karotammela.fi

Tech Stack

Frontend & UI: Streamlit (Python)

LLM Engine: Google AI / Gemini API (google-genai SDK using gemini-2.5-flash)

Database & Data Warehouse: Snowflake (snowflake-connector-python or st.connection("snowflake"))

Scraping: requests, beautifulsoup4

Data Handling: pandas

App Architecture & Key Features

Tab 1: 🕵️‍♂️ Grant Scout (Web Agent)

User Action: User inputs a URL of a foundation or funding organization's website.

Scraper Module: Fetches HTML, strips scripts/styles, extracts clean prose text.

Gemini Extraction: Prompts Gemini API to parse raw text into structured JSON:
{ "foundation_name": str, "grant_title": str, "deadline": str, "funding_amount": str, "focus_areas": list, "eligibility": str }

UI Output: Displays extracted metadata in clean Streamlit components (st.metric, st.json, st.dataframe) with a button: "Save to Snowflake Database".

Tab 2: 📊 Matcher & Database

Data Source: Fetch all saved grants from Snowflake table GRANTS.

Org Context: Load a local mock profile (org_profile.json representing a health non-profit focusing on cardiovascular health, prevention, peer support, and research).

Gemini Evaluation: Compares grant requirements vs. org profile. Returns:

Compatibility Score (0–100%)

Strategic Alignment Pros & Cons

Recommendation (Pursue / Skip)

UI Output: Streamlit data cards sorted by highest match score.

Tab 3: ✍️ Grant Application Drafter

User Action: Select a high-matching grant from Tab 2 and click "Draft Proposal".

Gemini Generation: Synthesizes grant requirements + org profile history to write a complete 1st draft of a grant proposal (Executive Summary, Project Goals, Target Group, Expected Impact, Budget Justification).

UI Output: Interactive text box (st.text_area) for manual editing + "Download Draft (.txt)" button (st.download_button).

Database Schema (Snowflake)

Create table GRANTS:

id VARCHAR PRIMARY KEY

foundation_name VARCHAR

grant_title VARCHAR

deadline VARCHAR

funding_amount VARCHAR

focus_areas VARCHAR

source_url VARCHAR

created_at TIMESTAMP_NTZ

Addendum: Salesforce Nonprofit Cloud Integration (Mock Service)

Add a dedicated module to simulate fetching non-profit project history, past grants, and impact metrics directly from Salesforce Nonprofit Success Pack (NPSP).

Updated Architecture & Files

services/salesforce_service.py:

Simulates a Salesforce REST API / SOQL query client.

Loads data/salesforce_npsp_data.json containing mock records:

Campaigns / Projects (e.g., past cardiac research grants, community health campaigns, outcomes).

Impact_Metrics (e.g., number of patients served, workshops conducted).

Exposes methods: get_organization_history(), get_past_grants(), get_active_initiatives().

Integration in Tab 2 & Tab 3:

Tab 2 (Matcher): Pulls live project data from salesforce_service.py alongside Snowflake grant data to calculate compatibility.

Tab 3 (Drafter): Feeds both Salesforce project history and Snowflake grant requirements into Gemini to ground the grant proposal in real organizational track record data.

Project File Structure to Generate

Plaintext
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── services/
│   ├── __init__.py
│   ├── db_service.py       # Snowflake connection + SessionState mock fallback
│   ├── gemini_service.py   # Google AI Gemini API calls
│   └── scraper_service.py  # Web page scraper
├── data/
│   └── org_profile.json    # Mock profile for Suomen Sydänliitto
├── app.py                  # Main Streamlit UI entry point
├── requirements.txt
└── README.md
Critical Implementation Requirements

Fallback Logic (Crucial for Demos): In db_service.py, if Snowflake credentials are missing or connection fails, automatically fall back to an in-memory st.session_state SQLite database. The UI must never crash.

Modern Gemini SDK: Use from google import genai and client = genai.Client(api_key=...).

UX polish: Use Streamlit spinners (st.spinner), success toasts (st.toast), and clean typography.

Provide the complete python code for all files listed in the file structure above.
