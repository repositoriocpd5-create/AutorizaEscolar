"""Ponto de entrada WSGI (flask run / gunicorn / waitress)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
