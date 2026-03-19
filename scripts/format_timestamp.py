from datetime import datetime


def format_timestamp(ts_data):
    if not ts_data:
        return ""

    try:
        if isinstance(ts_data, str) and "T" in ts_data:
            clean_str = ts_data.replace("T", " ").replace("Z", "")
            if "." in clean_str:
                clean_str = clean_str.split(".")[0]
            return clean_str

        if isinstance(ts_data, dict):
            ts_str = ts_data.get("$date", {}).get("$numberLong")
            if ts_str:
                ts_float = float(ts_str) / 1000
                return datetime.fromtimestamp(ts_float).strftime("%Y-%m-%d %H:%M:%S")

        if str(ts_data).replace(".", "").isdigit():
            ts_float = float(ts_data)
            if ts_float > 1e12:
                ts_float /= 1000
            return datetime.fromtimestamp(ts_float).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_data)[:19]

    return str(ts_data)
