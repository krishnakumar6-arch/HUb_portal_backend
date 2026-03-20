# Hub Portal — Backend API

FastAPI backend for the Shadowfax Hub Facility Expense Intelligence Portal.

## Stack
- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL (Supabase / Neon / Railway)
- **Cache**: Redis (Upstash)
- **ETL**: Pandas + Google Drive API
- **Auth**: JWT (HS256)
- **Hosting**: Railway / Render

---

## Quick Start (Local)

### 1. Clone and install
```bash
git clone https://github.com/krishnakumar6-arch/hubportal-backend
cd hubportal-backend
pip install -r requirements.txt
```

### 2. Set up environment variables
```bash
cp .env.example .env
# Edit .env with your actual values
```

### 3. Set up PostgreSQL (Supabase — free)
1. Go to https://supabase.com → New project
2. Copy the connection string into `.env` as `DATABASE_URL` and `SYNC_DATABASE_URL`
3. Open the SQL editor and run `migrations/001_initial_schema.sql`

### 4. Set up Redis (Upstash — free)
1. Go to https://upstash.com → Create database
2. Copy the Redis URL into `.env` as `REDIS_URL`

### 5. Run the server
```bash
uvicorn main:app --reload
```

Open http://localhost:8000/docs for the interactive API documentation.

---

## Deploy to Railway (one-click from GitHub)

1. Go to https://railway.app
2. New Project → Deploy from GitHub → select `hubportal-backend`
3. Add all environment variables from `.env.example`
4. Railway auto-detects the Procfile and deploys

---

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL async URL (postgresql+asyncpg://...) |
| `SYNC_DATABASE_URL` | PostgreSQL sync URL for ETL (postgresql://...) |
| `REDIS_URL` | Redis connection URL |
| `JWT_SECRET` | Secret key for JWT signing — make this long and random |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON of Google service account |
| `GOOGLE_DRIVE_FILE_ID` | File ID from the Google Drive URL of your Excel |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend URLs |

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | Public | Login, get JWT token |
| GET | `/auth/me` | Any | Current user info |
| POST | `/auth/users` | Admin | Create new user |
| GET | `/hubs` | Any | Search hubs (HI sees own hub only) |
| GET | `/hubs/filters` | Any | Dropdown options for filters |
| GET | `/hubs/{hub_code}` | Any | Hub detail + monthly aggregates |
| GET | `/hubs/{hub_code}/expenses` | Any | Raw expense transactions |
| GET | `/dashboard/kpis` | Admin | Network KPI cards |
| GET | `/dashboard/state-spend` | Admin | Spend by state |
| GET | `/dashboard/category-mix` | Admin | Category pie chart data |
| GET | `/dashboard/top-hubs` | Admin | Leaderboard |
| GET | `/dashboard/flagged-hubs` | Admin | Audit flags |
| GET | `/export/hub/{hub_code}/csv` | Any | Download expenses as CSV |
| POST | `/etl/trigger` | Admin | Manual ETL sync |
| GET | `/etl/logs` | Admin | ETL run history |

---

## Connecting the Frontend

In your React app, set the API base URL:
```js
// In your Vercel project environment variables:
VITE_API_URL=https://your-backend.railway.app
```

Then call the API:
```js
const res = await fetch(`${import.meta.env.VITE_API_URL}/hubs?state=Delhi`, {
  headers: { Authorization: `Bearer ${token}` }
})
```

---

## Adding the Google Drive Connection

1. Go to Google Cloud Console → Create a Service Account
2. Enable the Google Drive API
3. Share your Excel file with the service account email
4. Download the JSON key
5. Paste the entire JSON as `GOOGLE_SERVICE_ACCOUNT_JSON` in your env
6. Copy the file ID from the Google Drive URL and set as `GOOGLE_DRIVE_FILE_ID`

The file ID is in the URL: `https://drive.google.com/file/d/FILE_ID_HERE/view`
# hub portal backend
