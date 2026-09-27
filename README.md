# Dolphin Cashback Reward

This Streamlit application lets customers request cashback after rating and reviewing a purchased product in Meesho. It stores submissions and app configuration in PostgreSQL when a valid database URL is configured, and it falls back to the local SQLite file only when no PostgreSQL connection is available.

## Features

- Customer form with QR-code access on mobile devices
- Yes / No review flow
- Admin-configurable cashback amount
- Configurable order-number validation
- Submission form with order number, phone number, and UPI ID
- Duplicate phone-number and UPI prevention
- Admin dashboard with submission filters, paid/unpaid totals, and bulk payment status updates
- Paid submissions cannot be changed back to unpaid
- Download filtered submissions as an Excel workbook (`.xlsx`)
- Duplicate-scan messaging in English and Hindi
- PostgreSQL-ready database layer with SQLite fallback

## Tech Stack

- Python
- Streamlit
- Pandas
- SQLite fallback
- PostgreSQL
- `psycopg2-binary`
- `python-dotenv`

## Setup

1. Create the project environment and install dependencies:

   ```bash
   py -3 -m venv .venv-1
   .venv-1\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Copy the example environment file and set the real database password:

   ```bash
   copy .env.example .env
   ```

3. Update `.env` with your local PostgreSQL connection string:

   ```env
   DATABASE_URL=postgresql://postgres:your_secure_password@localhost:5432/credit_review
   ```

   The app loads this file automatically using `python-dotenv`.

4. Start the app:

   ```bash
   .venv-1\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0 --server.port 59034
   ```

   Or run `run_app.bat` on Windows.

5. Open the URL shown in the terminal, usually `http://localhost:59034`.

## Database behavior

- If `DATABASE_URL` is present in `.env`, the application uses PostgreSQL.
- If `DATABASE_URL` is missing, it falls back to the local SQLite database file, `cashback_app.db`.
- The app reads the `.env` file automatically on startup, so shell variables are not required.

## Security notes

- `.env` is intentionally ignored by Git and should never be committed to source control.
- Use a strong password for Postgres and keep the file local to the machine running the app.
- The example file `.env.example` exists only as a template.

## Customer flow

For phone entry, connect the phone and computer to the same Wi-Fi, open the Customer page on the host, select **Yes**, and scan the QR code shown under the form. This opens the review form directly in the phone browser.

The QR code uses the computer's local network address by default. A `CUSTOMER_FORM_URL` set to `localhost`, `127.0.0.1`, or `0.0.0.0` is automatically replaced with the detected network address. For a hosted app or a different network setup, set `CUSTOMER_FORM_URL` in `.env` to the phone-accessible base URL before launching.

## Admin configuration

1. Choose **Admin** in the host app's navigation and sign in.
2. Open the **Config** tab.
3. Set the cashback amount and choose whether order numbers must match the approved-order list, then save.

When order validation is enabled, only order numbers in the `valid_orders` table are accepted. When disabled, any non-empty order number is accepted. The order number field remains required. New submissions store a snapshot of the configured cashback amount; changing the amount later does not change amounts already owed. The visitor's English and Hindi messages use the current configured amount. The admin dashboard reports the sum of the stored submission amounts as paid and unpaid.

The current approved-order list is seeded with five demo IDs (`ORD1001` through `ORD1005`) when the table is empty. Add real approved orders via a trusted import workflow before enabling validation for production traffic.

## Admin login

- Username: admin
- Password: admin123

## Notes

This is a prototype, not production-ready payment software. The admin credentials are hard-coded (`admin` / `admin123`), cashback marking is manual and does not initiate a UPI payment, there is no audit trail or customer identity verification, and the database needs a reliable backup strategy. Do not expose this app publicly with the demo credentials.

SQLite does not have a small fixed row-count limit. Its documented theoretical maximum database size is up to 281 TB, depending on page size and build limits; real capacity is constrained by available disk, indexes, query performance, backup/restore time, and hosting. This app is not load-tested, so no specific record count is claimed. SQLite is suitable for a small prototype, but PostgreSQL is the recommended database for concurrent production traffic.
