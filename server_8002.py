from waitress import serve
from ecommerce_engine.wsgi import application
serve(application, host='127.0.0.1', port=8002, threads=4)