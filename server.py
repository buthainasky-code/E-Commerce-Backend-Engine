"""
Waitress production server for Windows.
Replaces Django's single-threaded dev server with a fixed-size thread pool.
"""
from waitress import serve
from ecommerce_engine.wsgi import application

# 'threads' defines the size of the thread pool.
# Here we use 4 threads – just like Gunicorn's 4 workers.
serve(application, host='127.0.0.1', port=8000, threads=4)