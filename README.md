# 🚀 Burn-in Intelligence: AI-Driven Anomaly Detection in Component Burn-In & Screening

![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688)
![SIH](https://img.shields.io/badge/Smart_India_Hackathon-2024-orange)

> **Live Demo:** [sih-anomaly-detection.onrender.com](https://sih-anomaly-detection.onrender.com/)  
> **Problem Statement:** SIH 26170 (ISRO)  
> **Domain:** High-Reliability Space Electronics / Smart Automation

## 🛰️ Project Overview
In high-reliability sectors like space exploration, electronic components undergo rigorous Environmental Stress Screening (ESS) and Burn-In testing. Traditional screening relies on static pass/fail thresholds. However, **latent defects**—components that pass the absolute limits but exhibit subtle, anomalous drift over time—often escape into final payloads, leading to catastrophic field failures.

**Burn-in Intelligence** is a predictive machine learning platform that shifts the paradigm from static thresholds to **dynamic, evidence-based AI screening**. It analyzes time-series parametric data (0h, 24h, 168h) to detect subtle anomalies, forecast end-state failures, and provide human-readable Explainable AI (XAI) justifications to QA engineers.

---

## 🧠 Core ML Modules

### 1. Module A: Dynamic Outlier Detection (Calibration)
*   **The Approach:** Replaces static datasheet limits with robust, lot-specific statistical baselines.
*   **How it Works:** Ingests data from known-good reference devices to train a Gaussian Mixture Model (GMM). It calculates the Median and Median Absolute Deviation (MAD) to establish a dynamic probability distribution. Incoming production devices are scored using a **Robust Z-score**; anything falling outside the lot's unique baseline is flagged.

### 2. Module B: Time-Series Drift Predictor (Forecasting)
*   **The Approach:** Predicts the 168-hour parameter state using minimal early data points (0h, 24h).
*   **How it Works:** Implements a **directional pinball-loss quantile regression model**. The loss function is intentionally *asymmetric*—it penalizes the model 10x heavier for under-predicting parameter drift. This eliminates false negatives and ensures maximum safety. It dynamically calculates the drift velocity (Safety Slope) to trigger early rejection flags.

### 3. Module C: Explainable AI (XAI) & Audit
*   **The Approach:** Eliminates "Black Box" AI for QA Inspectors.
*   **How it Works:** Utilizes **SHAP (SHapley Additive exPlanations)** to deconstruct anomaly scores and visualize exact feature contributions. This data is fed into an air-gapped, local **Ollama LLM Copilot**, which generates a deterministic, human-readable justification for every rejected component.

---

## 🛠️ Technology Stack

| Architecture Layer | Technologies Used |
| :--- | :--- |
| **Frontend** | React, Next.js, Tailwind CSS, Recharts |
| **Backend API** | Python, FastAPI, Uvicorn, Pandas |
| **Machine Learning** | Scikit-Learn, PyTorch, SHAP, NumPy |
| **Local LLM / XAI** | Ollama (Llama 3 / Qwen) |
| **Database & Auth** | Supabase (PostgreSQL), NextAuth / OAuth |
| **Hosting & CI/CD** | Render, GitHub Actions |

---

## 🚦 System Workflow

1.  **Reference Calibration:** Upload `c.csv` (known-good devices). The system learns the normal behavior and establishes the mathematical baseline.
2.  **Burn-In Screening:** Upload the production lot `screening.csv`. 
3.  **Real-Time Forecasting:** The ML pipeline calculates robust Z-scores, projects the 168h drift, and identifies safety slope breaches.
4.  **Engineering Review:** Flagged devices populate a prioritized queue.
5.  **XAI Justification & Audit:** QA Inspectors review SHAP visual evidence, chat with the AI Copilot, and record a traceable Approve/Override decision in the PostgreSQL database.

---

## 💻 Local Setup & Installation

### Prerequisites
*   Node.js (v18+)
*   Python (3.10+)
*   [Ollama](https://ollama.com/) (For local XAI Copilot)

### 1. Clone the Repository
```bash
git clone [https://github.com/theabhishekkk/sih-anomaly-detection.git](https://github.com/theabhishekkk/sih-anomaly-detection.git)
cd sih-anomaly-detection

```

### 2. Backend Setup (FastAPI & ML Engine)

```bash
cd backend
python -m venv venv
# Activate venv: `source venv/bin/activate` (Mac/Linux) or `venv\Scripts\activate` (Windows)
pip install -r requirements.txt

```

*Create a `.env` file in the `/backend` folder:*

```env
DATABASE_URL=your_supabase_connection_string
QA_ALLOWLIST=your_email@example.com

```

*Run the backend server:*

```bash
uvicorn app:app --reload

```

### 3. Frontend Setup (Next.js)

```bash
cd ../frontend
npm install

```

*Create a `.env.local` file in the `/frontend` folder:*

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXTAUTH_SECRET=generate_a_random_32_char_string
OIDC_CLIENT_ID=your_entra_client_id
OIDC_CLIENT_SECRET=your_entra_secret

```

*Run the frontend server:*

```bash
npm run dev

```

### 4. Local LLM Setup

Ensure Ollama is installed and running on your machine:

```bash
ollama run qwen:0.5b

```

---

## 🔐 Security & Compliance

* **Role-Based Access Control:** Secure OAuth authentication ensures only authorized QA personnel can access the platform.
* **Immutable Audit Logging:** All human-in-the-loop decisions (Overrides, Approvals) are written to a Supabase PostgreSQL database with strict Row Level Security (RLS) policies.
* **Air-Gapped LLM:** The XAI Copilot is designed to run locally, ensuring highly classified component data never leaves the ISRO internal network.

---

## 👨‍💻 Developed By

**Abhishek Ranjan** & Team Code Catalysts
*Pursuing MCA at Amity University Noida | Participant, Smart India Hackathon*

[LinkedIn](https://www.linkedin.com/in/abhishek-ranjan-2ab9971a9/) | [GitHub](https://github.com/theabhishekkk)

