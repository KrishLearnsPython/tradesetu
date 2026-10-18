# TradeSetu

**Live Demo:** https://tradesetu-un4f.onrender.com

TradeSetu is a web-based supply-chain tracking prototype designed to
help Indian MSMEs record and follow shipments across stakeholders. It
provides role-based workflows, QR-assisted shipment lookup, and
hash-based shipment verification backed by PostgreSQL.

> **Project status:** Academic project / prototype. The live demo may
> experience cold starts or interruptions depending on hosting
> availability. Use test data when exploring the application.

## Overview

TradeSetu aims to make shipment handoffs easier to track by maintaining
shipment records and providing a QR code that carries the shipment
identifier and its associated hash. Authorized users can use the
application to follow shipment progress and verify the stored shipment
hash.

## Key Features

-   **Stakeholder-based workflows** for manufacturers, distributors,
    storage stakeholders, and retailers.
-   **Shipment creation and assignment** through the manufacturer
    workflow.
-   **QR-code generation and scanning** to identify shipments.
-   **Hash-based verification** using SHA-256-derived shipment hashes.
-   **Shipment status and history views** for tracking workflow
    progress.
-   **Authentication and session handling** with Flask.
-   **CSRF protection** using Flask-WTF.
-   **PostgreSQL persistence** through Supabase.
-   **Responsive web interface** designed for desktop and mobile-sized
    screens.
-   **Automated tests** covering key application behavior.

## Live Demo

**https://tradesetu-un4f.onrender.com**

Use test accounts and test shipment data. Do not enter sensitive
business or personal information into a public demo.

## Technology Stack

  -----------------------------------------------------------------------
  Layer                               Technology
  ----------------------------------- -----------------------------------
  Backend                             Python, Flask

  Database                            PostgreSQL (Supabase)

  Database driver                     Psycopg

  Templates and interface             HTML, CSS, JavaScript, Jinja

  QR codes                            `qrcode` with Pillow

  Application security                Flask-WTF CSRF protection, session
                                      cookies, server-side validation

  Production server                   Gunicorn

  Tests                               pytest
  -----------------------------------------------------------------------

## Application Workflow

1.  A stakeholder signs in to the application.
2.  A manufacturer creates a shipment with the required shipment
    details.
3.  TradeSetu generates a shipment identifier and a SHA-256-based hash,
    then creates a QR code containing the shipment identifier and hash.
4.  The manufacturer can view shipments and assign a shipment to a
    distributor.
5.  Downstream stakeholders use the relevant workflow and QR scanning to
    identify and process shipments.
6.  The verification workflow compares the QR-provided hash with the
    stored shipment hash.

**Integrity note:** Hash-based verification helps detect mismatches
against the stored record. It is not, by itself, proof of end-to-end
authenticity. Blockchain integration is not part of the current version.

## Run Locally

### Prerequisites

-   Python 3.10 or newer (use a version compatible with the installed
    dependencies)
-   Git
-   A PostgreSQL database, such as a Supabase project
-   A terminal

### 1. Clone the repository

``` bash
git clone https://github.com/KrishLearnsPython/tradesetu.git
cd tradesetu
```

### 2. Create and activate a virtual environment

On macOS or Linux:

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

``` powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

The Flask application and its requirements are inside the `tradesetu/`
directory.

``` bash
python -m pip install -r tradesetu/requirements.txt
```

### 4. Configure environment variables

Create a local `.env` file inside the `tradesetu/` directory if that is
where your `db_config.py` loads environment variables from. Set the
following values:

``` dotenv
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
SESSION_COOKIE_SECURE=False
```

Replace the database URL with your own PostgreSQL connection string. Do
not commit `.env` or share its contents. Use a unique, strong
`SECRET_KEY`; never use the example text above as a real secret.

`SESSION_COOKIE_SECURE=False` is for local HTTP development only. In
production behind HTTPS, set `SESSION_COOKIE_SECURE=True`.

### 5. Start the development server

From the repository root:

``` bash
python tradesetu/app.py
```

Then open **http://127.0.0.1:5003**.

### 6. Run tests

From the repository root:

``` bash
PYTHONPATH=. python -m pytest -q
```

The project test suite was reported as passing **26 tests** during
preparation of this README. Run the command in your own environment to
confirm the current result.

## Production Deployment

The live demo is hosted on Render, with PostgreSQL provided by Supabase.

Recommended Render service configuration when the repository root is the
Git repository:

  Setting          Value
  ---------------- -----------------------------------------
  Root Directory   `tradesetu`
  Build Command    `pip install -r requirements.txt`
  Start Command    `gunicorn --bind 0.0.0.0:$PORT app:app`
  Branch           `phase1-foundation`

Configure these environment variables in Render's service settings:

-   `SECRET_KEY` --- a strong, stable random secret.
-   `DATABASE_URL` --- the PostgreSQL connection string for the
    database.
-   `SESSION_COOKIE_SECURE` --- `True` for HTTPS production.

Never place secrets in source code, README files, screenshots, or Git
commits. Review deployment logs for errors without sharing credentials.

### QR image storage

QR images are generated under `tradesetu/static/qr_codes/`. The
deployment includes logic to recreate missing QR images when a
manufacturer opens the shipment list. This is a recovery measure, not
persistent file storage; ephemeral hosting filesystems may clear
generated images during restarts or redeployments.

## Security Notes

-   Keep CSRF protection enabled.
-   Use HTTPS in production and enable secure session cookies.
-   Keep `SECRET_KEY` and `DATABASE_URL` in environment variables.
-   Never commit `.env`, virtual environments, or generated local files.
-   Use test data in the public demo.
-   Treat shipment hashes as a verification aid, not a substitute for a
    complete security audit or trusted audit trail.

## Repository Structure

``` text
tradesetu/
├── .gitignore
├── tradesetu/
│   ├── app.py
│   ├── db_config.py
│   ├── requirements.txt
│   ├── templates/
│   └── static/
│       └── qr_codes/
└── tests/
```

The exact repository may contain additional assets and test files; this
diagram highlights the main application components.

## Known Limitations

-   The application is an academic prototype and has not been
    represented as a fully audited production supply-chain platform.
-   QR image files may need to be regenerated on ephemeral hosting.
-   Hash comparison does not independently prove that all shipment data
    has remained unchanged unless the verification logic recomputes the
    expected hash from trusted source fields.
-   Blockchain integration is deferred and is not included in the
    current version.

## Contributors

-   **Krish Gupta**
-   **Atharva Jagtap**

**Institution:** MIT ADT University

## License

No license has been specified in this repository. Unless a license is
added, reuse and redistribution are subject to applicable default
copyright rules.
