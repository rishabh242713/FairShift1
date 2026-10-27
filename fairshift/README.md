# FairShift — unfinished prototype

Existing work handed over as requested. This is not a finished or verified competition submission.

## Included
- Python Flask backend and SQLAlchemy database models
- Worker/admin web interface for construction and college workplaces
- Shift tracking, pay estimates, reporting and skill-record functionality
- Dockerfile and Gunicorn entry point

## Local setup (Python 3.12 recommended)
```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows instead: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app seed
flask --app app run --port 8080
```
Visit http://localhost:8080.

Demo usernames: worker.site, admin.site, worker.campus, admin.campus
Demo password for all four accounts: FairShift-demo-2026!
These are public demonstration credentials, not production accounts.

## Container
```sh
docker build -t fairshift .
docker run --rm -p 8080:8080 fairshift
```
The container starts without demo data. Run `flask --app app seed` in the running container to populate its database. Its default SQLite database is ephemeral; do not use it for real employee records or durable Cloud Run storage.

## Configuration
- SECRET_KEY: set a strong, stable secret before deployment.
- DATABASE_URL: defaults to local SQLite; use a persistent database for deployment.
- COOKIE_SECURE=1: set when serving over HTTPS.
- PORT: server port (container default 8080).

## Verification performed for this handover
Application initialization, demo database seeding and GET / (login page) passed in an isolated temporary database. No comprehensive workflow, browser, security or deployment tests have been completed.

## Outstanding work / limitations
- No unit-test suite included; end-to-end workflows remain unverified.
- Not published to GitHub or deployed to Cloud Run.
- Submission-rule and problem-statement compliance has not been fully audited.
- Reporting privacy must be reviewed before real use; do not promise anonymity.
- Pay values are prototype estimates, not validated payroll or legal calculations.
- Demo accounts, authorization, concurrency, rate limiting, persistent storage and production configuration require review before using real worker data.
- No LinkedIn submission post is included.

The database and Python cache files are intentionally excluded from this source archive. Seed a fresh demo database locally.
