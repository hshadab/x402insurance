"""
Unit tests for blockchain client.
Mock mode removed — private key is now required.
"""
import pytest
from unittest.mock import patch, MagicMock
from blockchain import BlockchainClient


class TestBlockchainClient:
    """Test blockchain client requires private key"""

    def test_missing_private_key_raises_error(self):
        """BlockchainClient must raise RuntimeError without a private key."""
        with patch("blockchain.Web3"):
            with pytest.raises(RuntimeError, match="BACKEND_WALLET_PRIVATE_KEY is required"):
                BlockchainClient(
                    rpc_url="https://sepolia.base.org",
                    usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                    private_key=None
                )

    def test_empty_private_key_raises_error(self):
        """Empty string private key must also raise RuntimeError."""
        with patch("blockchain.Web3"):
            with pytest.raises(RuntimeError, match="BACKEND_WALLET_PRIVATE_KEY is required"):
                BlockchainClient(
                    rpc_url="https://sepolia.base.org",
                    usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                    private_key=""
                )

    def test_valid_private_key_initializes(self):
        """With a valid private key, BlockchainClient should initialize."""
        with patch("blockchain.Web3") as MockWeb3:
            mock_w3 = MagicMock()
            MockWeb3.return_value = mock_w3
            MockWeb3.to_checksum_address = lambda addr: addr
            mock_w3.eth.account.from_key.return_value = MagicMock(address="0xTest")

            client = BlockchainClient(
                rpc_url="https://sepolia.base.org",
                usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                private_key="0x" + "ab" * 32
            )
            assert client.account.address == "0xTest"
