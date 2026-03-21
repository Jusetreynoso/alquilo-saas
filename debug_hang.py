import os
import faulthandler
import threading
import sys

def dump_and_exit():
    print("Dumping traceback...", file=sys.stderr)
    faulthandler.dump_traceback(file=sys.stderr)
    os._exit(1)

faulthandler.enable()
timer = threading.Timer(4.0, dump_and_exit)
timer.start()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alquilo_core.settings')
import django
django.setup()
print("Setup finished")

from django.core.management import call_command
call_command('check')
timer.cancel()
print("Check finished")
