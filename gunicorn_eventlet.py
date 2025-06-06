import eventlet
eventlet.monkey_patch(all=True)
# Gunicorn configuration settings.
import multiprocessing
import os

try:
    port = int(os.environ["PORT"])
except:
    port = 8080
bind = ":{}".format(port)

# Don't start too many workers:
try:
    workers = int(os.environ["AUTH2_WORKERS"])
except:
    workers = 0

if not workers or workers < 1:
    workers = multiprocessing.cpu_count() + 2

worker_class = "eventlet"
worker_connections = 50000
# Give workers an expiry:
max_requests = 100000
max_requests_jitter = 5000
preload_app = True
# Set longer timeout for workers
timeout = 180
# Disable access logging.
accesslog = None
