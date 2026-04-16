# Render / Heroku / Railway deployment
# Production: gunicorn with gevent worker for SocketIO
web: gunicorn --worker-class eventlet -w 1 --threads 4 --bind 0.0.0.0:$PORT "app:app"
