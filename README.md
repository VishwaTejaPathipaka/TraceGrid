# TraceGrid – API Monitoring & Analytics Platform

TraceGrid is a web-based API monitoring platform that allows users to register API endpoints, monitor their availability, track response times, and view monitoring history and analytics.

## Features

- User registration and login with JWT authentication
- Add, view, update, and delete API endpoints
- Manual API health checks
- Automated health checks at regular intervals
- UP/DOWN status detection
- HTTP status code and response-time tracking
- Monitoring history stored in PostgreSQL
- Endpoint analytics and uptime percentage
- Dashboard with monitoring statistics
- Automated backend tests using Pytest

## Technologies Used

**Backend:** Python, FastAPI, SQLAlchemy

**Frontend:** React, Vite, JavaScript, CSS

**Database:** PostgreSQL

**Authentication:** JWT, Argon2 password hashing

**Testing:** Pytest, FastAPI TestClient

**Monitoring:** HTTPX, APScheduler

## Project Structure

```text
TraceGrid/
├── app/
│   ├── models/
│   ├── routes/
│   ├── schemas/
│   ├── services/
│   ├── config.py
│   ├── database.py
│   ├── security.py
│   └── main.py
├── frontend/
│   └── src/
│       └── pages/
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_endpoints.py
│   └── test_monitoring.py
├── requirements.txt
└── README.md
```

## Setup and Installation

### 1. Clone the repository

```bash
git clone https://github.com/VishwaTejaPathipaka/TraceGrid.git
cd TraceGrid
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install backend dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/tracegrid
SECRET_KEY=your-secret-key
ALGORITHM=HS256
```

Create the PostgreSQL database named `tracegrid` before starting the application.

### 5. Start the backend

```bash
python -m uvicorn app.main:app --reload
```

Backend: http://127.0.0.1:8000

API documentation: http://127.0.0.1:8000/docs

### 6. Start the frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

## Running Tests

From the project root:

```bash
python -m pytest -v
```

## Project Status

The core application features are implemented and tested. The backend automated test suite currently contains 16 passing tests.

## Author

**Vishwa Teja Pathipaka**

GitHub: https://github.com/VishwaTejaPathipaka