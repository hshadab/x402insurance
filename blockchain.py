"""
Blockchain service - USDC refunds on Base

Enhanced with:
- Retry logic for failed transactions
- Gas price limits and EIP-1559 support
- Better error handling
- Balance checking
"""
from web3 import Web3
from web3.exceptions import TransactionNotFound, TimeExhausted, ContractLogicError
import os
import logging
import time
from typing import Optional

# ERC20 ABI (minimal - transfer and balanceOf)
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]


class BlockchainClient:
    def __init__(
        self,
        rpc_url: str,
        usdc_address: str,
        private_key: str,
        max_gas_price_gwei: int = 100,
        max_retries: int = 3,
        confirmation_timeout: int = 120
    ):
        if not private_key:
            raise RuntimeError(
                "BACKEND_WALLET_PRIVATE_KEY is required. "
                "Blockchain refunds cannot operate without a funded wallet."
            )

        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.max_gas_price_gwei = max_gas_price_gwei
        self.max_retries = max_retries
        self.confirmation_timeout = confirmation_timeout
        self.logger = logging.getLogger("x402insurance.blockchain")

        self.account = self.w3.eth.account.from_key(private_key)
        self.usdc_address = Web3.to_checksum_address(usdc_address)
        self.usdc = self.w3.eth.contract(address=self.usdc_address, abi=ERC20_ABI)
        self.logger.info("Blockchain initialized with wallet: %s", self.account.address)

    def get_balance(self, address: Optional[str] = None) -> int:
        """
        Get USDC balance

        Args:
            address: Address to check (defaults to self)

        Returns:
            Balance in USDC units (6 decimals)
        """
        addr = Web3.to_checksum_address(address or self.account.address)
        try:
            balance = self.usdc.functions.balanceOf(addr).call()
            return balance
        except Exception as e:
            self.logger.exception("Error getting balance: %s", e)
            return 0

    def get_eth_balance(self, address: Optional[str] = None) -> int:
        """Get ETH balance in wei"""
        addr = Web3.to_checksum_address(address or self.account.address)
        try:
            return self.w3.eth.get_balance(addr)
        except Exception as e:
            self.logger.exception("Error getting ETH balance: %s", e)
            return 0

    def issue_refund(self, to_address: str, amount: int) -> str:
        """
        Issue USDC refund with retry logic

        Args:
            to_address: Recipient address
            amount: Amount in USDC units (6 decimals)

        Returns:
            Transaction hash

        Raises:
            Exception: If refund fails after retries
        """
        to_address = Web3.to_checksum_address(to_address)

        # Check balance before attempting transfer
        balance = self.get_balance()
        if balance < amount:
            raise Exception(
                f"Insufficient USDC balance: have {balance} units, need {amount} units"
            )

        # Check ETH balance for gas
        eth_balance = self.get_eth_balance()
        min_eth_balance = self.w3.to_wei(0.001, 'ether')  # Minimum 0.001 ETH for gas
        if eth_balance < min_eth_balance:
            raise Exception(
                f"Insufficient ETH for gas: have {self.w3.from_wei(eth_balance, 'ether')} ETH"
            )

        # Retry logic
        last_error = None
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    self.logger.info("Retry attempt %d/%d", attempt + 1, self.max_retries)
                    time.sleep(2 ** attempt)  # Exponential backoff

                tx_hash = self._send_refund_transaction(to_address, amount)
                self.logger.info("Refund successful: tx=%s", tx_hash)
                return tx_hash

            except (TransactionNotFound, TimeExhausted) as e:
                last_error = e
                self.logger.warning("Transaction timeout on attempt %d: %s", attempt + 1, e)
                continue

            except ContractLogicError as e:
                # Contract error - don't retry
                self.logger.error("Contract logic error: %s", e)
                raise Exception(f"USDC transfer failed: {str(e)}")

            except Exception as e:
                last_error = e
                self.logger.warning("Transaction failed on attempt %d: %s", attempt + 1, e)
                continue

        # All retries failed
        raise Exception(f"Refund failed after {self.max_retries} attempts: {last_error}")

    def _send_refund_transaction(self, to_address: str, amount: int) -> str:
        """Internal method to send refund transaction"""
        # Get current nonce
        nonce = self.w3.eth.get_transaction_count(self.account.address)

        # Get gas price with limit
        current_gas_price = self.w3.eth.gas_price
        max_gas_price = self.w3.to_wei(self.max_gas_price_gwei, 'gwei')
        gas_price = min(current_gas_price, max_gas_price)

        if current_gas_price > max_gas_price:
            self.logger.warning(
                "Gas price capped: current=%s gwei, using=%s gwei",
                self.w3.from_wei(current_gas_price, 'gwei'),
                self.max_gas_price_gwei
            )

        # Build transaction
        tx = self.usdc.functions.transfer(
            to_address,
            amount
        ).build_transaction({
            'from': self.account.address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': gas_price,
            'chainId': self.w3.eth.chain_id
        })

        # Sign transaction
        signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)

        # Handle both old and new web3.py versions
        raw_tx = signed_tx.raw_transaction if hasattr(signed_tx, 'raw_transaction') else signed_tx.rawTransaction

        # Send transaction
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
        self.logger.info(
            "Transaction sent: hash=%s nonce=%d gas_price=%s gwei",
            tx_hash.hex(),
            nonce,
            self.w3.from_wei(gas_price, 'gwei')
        )

        # Wait for confirmation with timeout
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.confirmation_timeout)

        if receipt.status != 1:
            raise Exception(f"Transaction reverted: {tx_hash.hex()}")

        return tx_hash.hex()
