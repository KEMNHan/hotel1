#!/usr/bin/env python
import os
import sys
import requests
from time import sleep
def enable_undeadthread():
    cnt = 10
    while cnt:
        try:
            requests.get("http://localhost:8000/undeadthread", )
        except Exception:
            cnt -= 1
            sleep(1)
        else:
            break


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hotel.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    import threading
    threading.Thread(target=enable_undeadthread, daemon=True).start()

    execute_from_command_line(sys.argv)
