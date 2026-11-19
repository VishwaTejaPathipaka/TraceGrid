from apscheduler.schedulers.background import BackgroundScheduler
from app.database import SessionLocal
from app.models import APIEndpoint, MonitoringHistory
from app.services.monitor import check_api


def monitor_all_endpoints():
    db = SessionLocal()

    try:
        endpoints = db.query(APIEndpoint).filter(
            APIEndpoint.is_active == True
        ).all()

        for endpoint in endpoints:
            try:
                result = check_api(endpoint.url, endpoint.method)

                history = MonitoringHistory(
                    endpoint_id=endpoint.id,
                    status=result["status"],
                    status_code=result["status_code"],
                    response_time=result["response_time"]
                )

                db.add(history)

            except Exception as error:
                print(f"Monitoring failed for {endpoint.name}: {error}")

        db.commit()

    finally:
        db.close()


scheduler = BackgroundScheduler()


def start_scheduler():
    scheduler.add_job(
        monitor_all_endpoints,
        trigger="interval",
        seconds=60,
        id="automatic_monitoring",
        replace_existing=True
    )

    scheduler.start()