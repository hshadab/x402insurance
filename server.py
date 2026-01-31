"""
x402 Insurance Service — Entry Point
"""
from app import create_app
from config import get_config

app = create_app()

if __name__ == '__main__':
    config = get_config()
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
