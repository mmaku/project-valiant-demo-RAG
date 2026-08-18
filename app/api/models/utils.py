import datetime


def format_datetime_into_isoformat(date_time: datetime.datetime) -> str:
    return date_time.replace(tzinfo=datetime.UTC).isoformat().replace("+00:00", "Z")
