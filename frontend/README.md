# TraceGrid – API Monitoring & Analytics Platform

TraceGrid is a web-based API monitoring platform built to check API availability, track response times, and maintain monitoring history. It provides a dashboard where users can manage endpoints and view monitoring results and analytics.

## Features

- User registration, email verification, sign-in, and password recovery
- JWT-based authentication
- Add, edit, and delete API endpoints
- Manual API health checks
- Durable automatic API monitoring with a 30-second target interval
- UP/DOWN status detection
- HTTP status code tracking
- API response-time measurement
- Monitoring history with timestamps
- Endpoint analytics
- Dashboard summary and recent activity
- Automatic dashboard refresh

## Technologies Used

**Backend**
- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic
- JWT Authentication
- HTTPX
- APScheduler

**Frontend**
- React
- JavaScript
- Vite
- React Router
- CSS

## Project Structure

```text
TraceGrid/
│
├── app/
│   ├── models/
│   ├── routes/
│   ├── schemas/
│   ├── services/
│   │   ├── monitor.py
│   │   └── scheduler.py
│   ├── main.py
│   ├── database.py
│   └── security.py
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── api.js
│   │   ├── App.jsx
│   │   └── App.css
│   └── package.json
│
├── requirements.txt
└── README.md
```

## Installation and Setup

Use the registration form to request a verification link, then open the message and enter your account password on the verification page. Sign-in links to **Forgot password?** and **Resend verification**. For local testing, open the messages in the backend's `.tracegrid-mail/` outbox. The backend documentation covers the database migration and production email settings.

### 1. Clone the repository

```bash
git clone <your-github-repository-url>
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

### 4. Configure the database

Create a PostgreSQL database and configure the database connection in your environment settings.

### 5. Start the backend

```bash
python -m app.serve --reload
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

## Monitoring Process

TraceGrid uses APScheduler to dispatch due checks from PostgreSQL. The endpoint table shows upcoming and overdue checks and the last probe timing.

For each active endpoint, the system:
1. Sends an HTTP request.
2. Measures response time.
3. Determines whether the endpoint is UP or DOWN.
4. Records the HTTP status code.
5. Stores the monitoring result and timestamp in PostgreSQL.

## Purpose

This project was developed to understand API development, backend integration, database management, authentication, scheduled tasks, and frontend-backend communication.
