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
    ENV = os.getenv("ENV", "development")
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
    BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
    USDC_CONTRACT_ADDRESS = os.getenv(
        "USDC_CONTRACT_ADDRESS",
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base Mainnet USDC
    )
    BACKEND_WALLET_PRIVATE_KEY = os.getenv("BACKEND_WALLET_PRIVATE_KEY")
    BACKEND_WALLET_ADDRESS = os.getenv("BACKEND_WALLET_ADDRESS")

    # Blockchain limits
    MAX_GAS_PRICE_GWEI = int(os.getenv("MAX_GAS_PRICE_GWEI", 100))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

    # Jolt Atlas Prover
    JOLT_BINARY_PATH = os.getenv("JOLT_BINARY_PATH", "./jolt-atlas/jolt_claims_prover")
    ONNX_MODEL_PATH = os.getenv("ONNX_MODEL_PATH", "./models/claim_classifier.onnx")

    # Insurance parameters
    PREMIUM_PERCENTAGE = float(os.getenv("PREMIUM_PERCENTAGE", "0.01"))  # 1%
    MAX_COVERAGE_USDC = float(os.getenv("MAX_COVERAGE_USDC", "0.1"))
    POLICY_DURATION_HOURS = int(os.getenv("POLICY_DURATION_HOURS", "24"))

    # Rate limiting
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ["1", "true", "yes"]
    RATE_LIMIT_STORAGE_URL = os.getenv("RATE_LIMIT_STORAGE_URL")  # Redis URL (optional)
    RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "200 per day")
    RATE_LIMIT_INSURE = os.getenv("RATE_LIMIT_INSURE", "50 per hour")
    RATE_LIMIT_CLAIM = os.getenv("RATE_LIMIT_CLAIM", "10 per hour")
    RATE_LIMIT_RENEW = os.getenv("RATE_LIMIT_RENEW", "5 per hour")

    # Payment verification
    PAYMENT_MAX_AGE_SECONDS = int(os.getenv("PAYMENT_MAX_AGE_SECONDS", 300))

    # Reserve monitoring
    MIN_RESERVE_RATIO = float(os.getenv("MIN_RESERVE_RATIO", "1.5"))
    ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

    # Security
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")  # Comma-separated
    REQUIRE_CLAIM_AUTHENTICATION = True

    # Timeouts (in seconds)
    JOLT_TIMEOUT = int(os.getenv("JOLT_TIMEOUT", 60))
    BLOCKCHAIN_CONFIRMATION_TIMEOUT = int(os.getenv("BLOCKCHAIN_CONFIRMATION_TIMEOUT", 120))

    # Chain configuration
    CHAIN_ID = int(os.getenv("CHAIN_ID", 8453))  # Base Mainnet default

    # CAIP-2 network identifier (derived from CHAIN_ID)
    @property
    def CAIP2_NETWORK(self):
        return f"eip155:{self.CHAIN_ID}"

    # x402 V2 Facilitator
    FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")

    # Monitoring
    SENTRY_DSN = os.getenv("SENTRY_DSN")
    SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "development")
    SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    # Redis / Huey task queue
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    HUEY_IMMEDIATE = os.getenv("HUEY_IMMEDIATE", "false").lower() in ["1", "true", "yes"]

    # AgentCore service URL (used by dashboard to link/display)
    AGENTCORE_SERVICE_URL = os.getenv(
        "AGENTCORE_SERVICE_URL",
        "https://4axkjkepdx.us-east-1.awsapprunner.com"
    )



class DevelopmentConfig(Config):
    """Development configuration"""

    ENV = "development"
    DEBUG = True
    LOG_LEVEL = "DEBUG"

    BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")


class ProductionConfig(Config):
    """Production configuration"""

    ENV = "production"
    DEBUG = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
    USDC_CONTRACT_ADDRESS = os.getenv(
        "USDC_CONTRACT_ADDRESS",
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base Mainnet USDC
    )
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
    CHAIN_ID = int(os.getenv("CHAIN_ID", 8453))  # Base Mainnet
    SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "production")
    SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2"))


class TestingConfig(Config):
    """Testing configuration"""

    ENV = "testing"
    TESTING = True
    DEBUG = True
    LOG_LEVEL = "DEBUG"

    DATABASE_URL = None
    RATE_LIMIT_ENABLED = False
    HUEY_IMMEDIATE = True


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
        import logging
        _log = logging.getLogger("x402insurance.config")
        if not config.BASE_RPC_URL:
            _log.warning("BASE_RPC_URL not set — blockchain operations will fail")
        if not config.BACKEND_WALLET_PRIVATE_KEY:
            _log.warning("BACKEND_WALLET_PRIVATE_KEY not set — blockchain operations will fail")
        if not config.BACKEND_WALLET_ADDRESS:
            _log.warning("BACKEND_WALLET_ADDRESS not set — blockchain operations will fail")

    return config
