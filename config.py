"""
Configuration management for x402 Insurance

Handles environment-specific configuration with secure defaults.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration"""

    # App
    DEBUG = False
    TESTING = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Server
    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "0.0.0.0")

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")  # If set, uses PostgreSQL
    DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

    # Blockchain
    BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://sepolia.base.org")
    USDC_CONTRACT_ADDRESS = os.getenv(
        "USDC_CONTRACT_ADDRESS",
        "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # Base Sepolia USDC
    )
    BACKEND_WALLET_PRIVATE_KEY = os.getenv("BACKEND_WALLET_PRIVATE_KEY")
    BACKEND_WALLET_ADDRESS = os.getenv("BACKEND_WALLET_ADDRESS")

    # Blockchain limits
    MAX_GAS_PRICE_GWEI = int(os.getenv("MAX_GAS_PRICE_GWEI", 100))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

    # zkEngine
    ZKENGINE_BINARY_PATH = os.getenv("ZKENGINE_BINARY_PATH", "./zkengine/zkengine-binary")

    # Insurance parameters
    PREMIUM_PERCENTAGE = float(os.getenv("PREMIUM_PERCENTAGE", "0.01"))  # 1%
    MAX_COVERAGE_USDC = float(os.getenv("MAX_COVERAGE_USDC", "0.1"))
    POLICY_DURATION_HOURS = int(os.getenv("POLICY_DURATION_HOURS", "24"))

    # Rate limiting
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ["1", "true", "yes"]
    RATE_LIMIT_STORAGE_URL = os.getenv("RATE_LIMIT_STORAGE_URL")  # Redis URL (optional)

    # Payment verification
    PAYMENT_VERIFICATION_MODE = os.getenv(
        "PAYMENT_VERIFICATION_MODE",
        "simple"  # "simple" or "full"
    )
    PAYMENT_MAX_AGE_SECONDS = int(os.getenv("PAYMENT_MAX_AGE_SECONDS", 300))

    # Reserve monitoring
    MIN_RESERVE_RATIO = float(os.getenv("MIN_RESERVE_RATIO", "1.5"))

    # Security
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")  # Comma-separated


class DevelopmentConfig(Config):
    """Development configuration"""

    DEBUG = True
    LOG_LEVEL = "DEBUG"

    # Use testnet by default
    BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://sepolia.base.org")

    # Simple payment verification for easier testing
    PAYMENT_VERIFICATION_MODE = "simple"


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Require mainnet configuration
    BASE_RPC_URL = os.getenv("BASE_RPC_URL")

    # Require wallet configuration (validated at runtime, not import time)
    # Validation happens in get_config() or when config is used

    # Full payment verification in production
    PAYMENT_VERIFICATION_MODE = "full"

    # Stricter CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")


class TestingConfig(Config):
    """Testing configuration"""

    TESTING = True
    DEBUG = True
    LOG_LEVEL = "DEBUG"

    # Use mock services for testing
    DATABASE_URL = None  # Use JSON files
    PAYMENT_VERIFICATION_MODE = "simple"
    RATE_LIMIT_ENABLED = False


# Config selection
config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}

def get_config(env: str = None) -> Config:
    """Get configuration based on environment"""
    if env is None:
        env = os.getenv('FLASK_ENV', os.getenv('ENV', 'development'))

    config_class = config_map.get(env.lower(), DevelopmentConfig)
    config = config_class()

    # Validate production config
    if isinstance(config, ProductionConfig):
        if not config.BASE_RPC_URL:
            raise ValueError("BASE_RPC_URL must be set in production")
        if not config.BACKEND_WALLET_PRIVATE_KEY:
            raise ValueError("BACKEND_WALLET_PRIVATE_KEY must be set in production")
        if not config.BACKEND_WALLET_ADDRESS:
            raise ValueError("BACKEND_WALLET_ADDRESS must be set in production")

    return config
