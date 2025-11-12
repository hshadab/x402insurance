# Future Improvements for Agent Adoption

**Date:** 2025-11-08
**Status:** Design Phase - Not Yet Implemented

This document details 5 major improvements to make x402 Insurance easier for agents to discover and use.

---

## 1. 🚀 Async Proof Generation (HIGH IMPACT)

### Problem
Agents must wait 15-30 seconds synchronously for claim processing:
- 10-20s for zkEngine proof generation (blocking)
- 2-5s for blockchain refund transaction
- Timeout risk if network is slow
- No way to recover if connection drops mid-processing

### Current Flow
```python
# Synchronous (current):
response = requests.post('/claim', json=claim_data, timeout=45)
# ⏳ Waits 15-30 seconds...
# Returns: {"claim_id": "...", "proof": "...", "refund_tx_hash": "..."}
```

### Proposed Solution: Job Queue Architecture

#### Architecture
```
Agent Request → API Server → Job Queue → Background Worker
     ↓              ↓
  Returns        Creates
  202 Accepted   claim record
  immediately    (status: processing)
                      ↓
                 Background worker:
                 1. Generate zkEngine proof
                 2. Issue blockchain refund
                 3. Update claim status → "paid"
```

#### New Flow
```python
# Step 1: Submit claim (returns immediately)
response = requests.post('/claim', json=claim_data)
# Status: 202 Accepted
# Response:
# {
#   "claim_id": "uuid",
#   "status": "processing",
#   "estimated_completion": "2025-11-08T10:00:20Z",
#   "poll_url": "/claims/uuid",
#   "message": "Claim is being processed. Poll /claims/{claim_id} for status."
# }

# Step 2: Poll for status (agent chooses when to check)
import time
for attempt in range(30):  # Poll for up to 60 seconds
    status = requests.get(f'/claims/{claim_id}').json()

    if status['status'] == 'paid':
        print(f"✅ Refund issued! TX: {status['refund_tx_hash']}")
        break
    elif status['status'] == 'failed':
        print(f"❌ Claim failed: {status['error']}")
        break

    time.sleep(2)  # Poll every 2 seconds
```

#### Implementation Details

**Technology Options:**

**Option A: Redis + RQ (Simple)**
```python
# Install: pip install redis rq

# server.py
from redis import Redis
from rq import Queue

redis_conn = Redis.from_url(config.REDIS_URL or 'redis://localhost:6379')
claim_queue = Queue('claims', connection=redis_conn)

@app.route('/claim', methods=['POST'])
def claim():
    # ... validate policy ...

    # Create claim record with status "processing"
    claim_id = str(uuid.uuid4())
    claim_record = {
        "claim_id": claim_id,
        "policy_id": policy_id,
        "status": "processing",  # ← New status
        "http_response": http_response,
        "created_at": iso_utc_now(),
        "idempotency_key": idempotency_key
    }

    # Save claim
    claims = load_data(CLAIMS_FILE)
    claims[claim_id] = claim_record
    save_data(CLAIMS_FILE, claims)

    # Enqueue background job
    job = claim_queue.enqueue(
        process_claim_async,
        claim_id=claim_id,
        timeout='60s'
    )

    # Return immediately
    return jsonify({
        "claim_id": claim_id,
        "status": "processing",
        "estimated_completion_seconds": 20,
        "poll_url": f"/claims/{claim_id}",
        "message": "Claim is being processed. Poll for status."
    }), 202  # 202 Accepted


# Background worker function
def process_claim_async(claim_id):
    """Background job to process claim"""
    claims = load_data(CLAIMS_FILE)
    claim = claims[claim_id]

    try:
        # Load policy
        policies = load_data(POLICIES_FILE)
        policy = policies[claim['policy_id']]

        # Generate proof (10-20s)
        proof_hex, public_inputs, gen_time_ms = zkengine.generate_proof(
            http_status=claim['http_response']['status'],
            http_body=claim['http_response']['body'],
            http_headers=claim['http_response'].get('headers', {})
        )

        # Verify proof
        is_valid = zkengine.verify_proof(proof_hex, public_inputs)
        if not is_valid:
            raise Exception("Proof verification failed")

        # Issue refund (2-5s)
        refund_tx_hash = blockchain.issue_refund(
            to_address=policy['agent_address'],
            amount=policy['coverage_amount_units']
        )

        # Update claim record
        claim['status'] = 'paid'
        claim['proof'] = proof_hex
        claim['public_inputs'] = public_inputs
        claim['refund_tx_hash'] = refund_tx_hash
        claim['paid_at'] = iso_utc_now()

        # Update policy
        policy['status'] = 'claimed'

        # Save
        claims[claim_id] = claim
        policies[claim['policy_id']] = policy
        save_data(CLAIMS_FILE, claims)
        save_data(POLICIES_FILE, policies)

    except Exception as e:
        # Mark claim as failed
        claim['status'] = 'failed'
        claim['error'] = str(e)
        claims[claim_id] = claim
        save_data(CLAIMS_FILE, claims)
        raise


# Run worker (separate process):
# rq worker claims --url redis://localhost:6379
```

**Option B: Celery (Production-Grade)**
```python
# More robust, supports multiple brokers (Redis, RabbitMQ)
# Install: pip install celery[redis]

from celery import Celery

celery = Celery('x402insurance', broker=config.REDIS_URL)

@celery.task
def process_claim_async(claim_id):
    # Same as above
    pass

# Run worker:
# celery -A server.celery worker --loglevel=info
```

**Option C: Background Thread (Lightweight, No Dependencies)**
```python
# Simple but less robust (no persistence if server crashes)
import threading

def claim():
    # ... create claim record ...

    # Start background thread
    thread = threading.Thread(
        target=process_claim_async,
        args=(claim_id,)
    )
    thread.daemon = True
    thread.start()

    return jsonify({...}), 202
```

#### Claim Status States
```
processing → paid (success)
processing → failed (error during proof generation or refund)
```

#### Benefits
✅ **No timeout risk** - Agent can poll at their own pace
✅ **Better error recovery** - Agent can check status after connection drop
✅ **Scalability** - Background workers can be scaled independently
✅ **Agent experience** - Can do other tasks while waiting

#### Trade-offs
⚠️ **Complexity** - Requires Redis/job queue infrastructure
⚠️ **Monitoring** - Need to monitor worker health
⚠️ **Deployment** - Need to run separate worker process

#### Effort
- **Development:** 2-3 days
- **Testing:** 1 day
- **Infrastructure:** Redis setup (if not using threads)

---

## 2. 🔍 Automatic Failure Detection (MEDIUM-HIGH IMPACT)

### Problem
Agents must manually:
1. Detect merchant failure
2. Capture HTTP response
3. Look up policy_id
4. File claim

This requires sophisticated error handling and state management.

### Proposed Solution: Proactive Health Monitoring

#### Option A: Agent-Registered Watchers

```python
# New endpoint: POST /watch
# Agent registers a merchant to watch

POST /watch
{
  "policy_id": "uuid",
  "merchant_url": "https://api.example.com/endpoint",
  "check_interval_seconds": 60,
  "alert_on": ["5xx", "timeout", "empty_response"]
}

Response: 201 Created
{
  "watch_id": "uuid",
  "status": "active",
  "next_check": "2025-11-08T10:01:00Z",
  "auto_claim": false  // Future: auto-file claims
}
```

**Background monitoring service:**
```python
# tasks/merchant_monitor.py
import asyncio
import httpx

class MerchantMonitor:
    def __init__(self, database, zkengine, blockchain):
        self.database = database
        self.zkengine = zkengine
        self.blockchain = blockchain
        self.watchers = {}

    async def start(self):
        """Run continuous monitoring"""
        while True:
            watches = self.database.get_active_watches()

            for watch in watches:
                # Check merchant health
                is_healthy = await self.check_merchant(watch['merchant_url'])

                if not is_healthy:
                    # Merchant failed! Auto-file claim
                    await self.auto_file_claim(watch)

            await asyncio.sleep(10)  # Check every 10 seconds

    async def check_merchant(self, url):
        """Ping merchant endpoint"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)

                # Check for failure conditions
                if response.status_code >= 500:
                    return False
                if response.status_code >= 400 and len(response.text) == 0:
                    return False
                if len(response.text) == 0:
                    return False

                return True
        except Exception:
            return False

    async def auto_file_claim(self, watch):
        """Automatically file claim when merchant fails"""
        # Fetch full response for proof
        response = await self.capture_failure_response(watch['merchant_url'])

        # File claim on behalf of agent
        claim_id = await self.create_claim(
            policy_id=watch['policy_id'],
            http_response=response
        )

        # Notify agent (webhook, email, etc.)
        await self.notify_agent(watch['agent_address'], claim_id)
```

**Agent flow:**
```python
# Step 1: Buy insurance
policy = x402.post('/insure', json={
    'merchant_url': 'https://api.example.com',
    'coverage_amount': 0.01
})

# Step 2: Register watcher (NEW!)
watcher = requests.post('/watch', json={
    'policy_id': policy['policy_id'],
    'merchant_url': 'https://api.example.com',
    'check_interval_seconds': 60
})

# Step 3: Go about your business...
# Service monitors merchant automatically

# Step 4: If merchant fails, service auto-files claim
# Agent receives webhook notification or polls /claims?wallet=0x...
```

#### Option B: Passive Monitoring (Simpler)

Don't actively ping merchants, but provide a reporting endpoint:

```python
# Agents report failures when they encounter them
POST /report-failure
{
  "merchant_url": "https://api.example.com",
  "http_response": {...}
}

# Service tracks failure patterns
# If 3+ agents report same merchant within 1 hour → broadcast alert
# Agents can subscribe to alerts for their insured merchants
```

#### Benefits
✅ **Reduced agent complexity** - No manual failure detection needed
✅ **Faster claims** - Auto-filed when failures detected
✅ **Better UX** - Agents can "set and forget"
✅ **Network effect** - Multiple agents can benefit from shared failure data

#### Trade-offs
⚠️ **Privacy concerns** - Service learns which merchants agents use
⚠️ **Infrastructure cost** - Continuous monitoring is expensive
⚠️ **False positives** - Temporary outages might trigger unnecessary claims
⚠️ **Merchant relationship** - Merchants might not appreciate constant pinging

#### Effort
- **Development:** 3-5 days
- **Testing:** 2 days
- **Infrastructure:** Background monitoring service + alerting

---

## 3. 🔌 AgentKit Integration (HIGH IMPACT)

### Problem
Agents need to manually integrate x402 Insurance using HTTP requests. No plug-and-play solution.

### Proposed Solution: Official Coinbase AgentKit Plugin

#### What is AgentKit?
Coinbase's framework for building AI agents with crypto capabilities. Provides:
- Wallet management
- Network interactions (Base, Ethereum)
- Tool/action system for agents to use

#### Plugin Architecture

**File: `agentkit-plugin-x402insurance/`**
```
agentkit-plugin-x402insurance/
├── pyproject.toml
├── README.md
├── x402insurance/
│   ├── __init__.py
│   ├── actions.py       # AgentKit actions
│   ├── client.py        # API client
│   └── schemas.py       # Pydantic models
└── examples/
    └── basic_usage.py
```

**Implementation:**

```python
# x402insurance/actions.py
from cdp_agentkit_core.actions import CdpAction
from pydantic import Field

class BuyInsuranceAction(CdpAction):
    """
    Buy micropayment insurance to protect against merchant fraud.

    Covers x402 API calls with instant refunds if merchant fails.
    """

    name: str = "buy_insurance"
    description: str = "Purchase insurance for a merchant API call"
    args_schema: type[BaseModel] = BuyInsuranceInput

    async def run(
        self,
        merchant_url: str,
        coverage_amount: float
    ) -> str:
        """Buy insurance policy"""
        from x402insurance.client import X402InsuranceClient

        # Auto-discovery via agent card
        client = X402InsuranceClient.from_discovery()

        # Purchase with agent's wallet
        policy = await client.buy_insurance(
            wallet=self.wallet_address,
            merchant_url=merchant_url,
            coverage_amount=coverage_amount
        )

        return f"✅ Insurance purchased! Policy ID: {policy['policy_id']}, Coverage: {coverage_amount} USDC"


class FileClaimAction(CdpAction):
    """
    File an insurance claim when a merchant fails to deliver.

    Automatically generates zero-knowledge proof and receives USDC refund.
    """

    name: str = "file_insurance_claim"
    description: str = "File claim when insured merchant fails"

    async def run(
        self,
        merchant_url: str,
        http_status: int,
        http_body: str
    ) -> str:
        """File claim for failed merchant"""
        from x402insurance.client import X402InsuranceClient

        client = X402InsuranceClient.from_discovery()

        # Auto-lookup policy by wallet + merchant
        policies = await client.get_policies(self.wallet_address)
        policy = next(
            p for p in policies
            if p['merchant_url'] == merchant_url
        )

        # File claim
        claim = await client.file_claim(
            policy_id=policy['policy_id'],
            http_response={
                'status': http_status,
                'body': http_body,
                'headers': {}
            }
        )

        return f"✅ Claim approved! Refund: {claim['payout_amount']} USDC, TX: {claim['refund_tx_hash']}"


# Register actions
def register_actions(agentkit):
    """Register x402insurance actions with AgentKit"""
    agentkit.register_action(BuyInsuranceAction())
    agentkit.register_action(FileClaimAction())
    agentkit.register_action(GetPoliciesAction())
    agentkit.register_action(VerifyProofAction())
```

**Client wrapper:**

```python
# x402insurance/client.py
import httpx
from typing import Optional, List, Dict

class X402InsuranceClient:
    """High-level client for x402 Insurance with agent-friendly features"""

    def __init__(self, base_url: str, wallet):
        self.base_url = base_url
        self.wallet = wallet
        self.agent_card = None

    @classmethod
    async def from_discovery(cls, base_url: Optional[str] = None):
        """Auto-discover service via A2A agent card"""
        if not base_url:
            # TODO: Query x402 Bazaar for insurance services
            base_url = "https://x402insurance.onrender.com"

        async with httpx.AsyncClient() as client:
            card = await client.get(f"{base_url}/.well-known/agent-card.json")
            instance = cls(base_url, wallet=None)
            instance.agent_card = card.json()
            return instance

    async def buy_insurance(
        self,
        wallet,
        merchant_url: str,
        coverage_amount: float
    ) -> Dict:
        """Purchase insurance with automatic x402 payment handling"""
        self.wallet = wallet

        # First request (will get 402)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/insure",
                json={
                    "merchant_url": merchant_url,
                    "coverage_amount": coverage_amount
                }
            )

            if response.status_code == 402:
                # Handle x402 payment
                payment_req = response.json()['payment']
                payment_header = await self._sign_x402_payment(payment_req)

                # Retry with payment
                response = await client.post(
                    f"{self.base_url}/insure",
                    headers={
                        'X-Payment': payment_header,
                        'X-Payer': self.wallet.address
                    },
                    json={
                        "merchant_url": merchant_url,
                        "coverage_amount": coverage_amount
                    }
                )

            response.raise_for_status()
            return response.json()

    async def get_policies(self, wallet_address: str) -> List[Dict]:
        """Get all active policies for wallet"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/policies",
                params={"wallet": wallet_address}
            )
            response.raise_for_status()
            return response.json()['active_policies']

    async def file_claim(
        self,
        policy_id: str,
        http_response: Dict,
        idempotency_key: Optional[str] = None
    ) -> Dict:
        """File insurance claim with idempotency support"""
        headers = {}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{self.base_url}/claim",
                headers=headers,
                json={
                    "policy_id": policy_id,
                    "http_response": http_response
                }
            )
            response.raise_for_status()
            return response.json()
```

**Usage Example:**

```python
# examples/basic_usage.py
from cdp_agentkit_core import CdpAgentkitWrapper
from x402insurance import register_actions

# Initialize AgentKit
agentkit = CdpAgentkitWrapper(
    cdp_wallet_data="...",
    network_id="base"
)

# Register x402 Insurance actions
register_actions(agentkit)

# Now agent can use natural language:
agent.run("Buy insurance for https://api.merchant.com with 0.01 USDC coverage")
# Agent automatically:
# 1. Discovers service via agent card
# 2. Signs x402 payment
# 3. Purchases policy
# 4. Returns policy_id

agent.run("The merchant at https://api.merchant.com returned 503 error, file a claim")
# Agent automatically:
# 1. Looks up policy by wallet + merchant URL
# 2. Files claim with captured response
# 3. Waits for proof generation
# 4. Reports refund transaction
```

#### Benefits
✅ **Zero manual integration** - Just install plugin
✅ **Natural language interface** - Agents use plain English
✅ **Automatic x402 handling** - Plugin manages payment signing
✅ **Official support** - Listed in AgentKit marketplace
✅ **Network effect** - More agents discover and use service

#### Trade-offs
⚠️ **AgentKit dependency** - Only works with Coinbase agents
⚠️ **Maintenance burden** - Must keep plugin updated
⚠️ **Review process** - Coinbase approval required for official listing

#### Effort
- **Development:** 3-5 days
- **Testing:** 2 days
- **Documentation:** 1 day
- **Coinbase review:** 1-2 weeks

#### Next Steps
1. Study AgentKit plugin architecture: https://github.com/coinbase/agentkit
2. Create plugin repository
3. Implement actions (buy, claim, get_policies, verify)
4. Write examples and tests
5. Submit to Coinbase for review

---

## 4. 🔄 Policy Renewal (MEDIUM IMPACT)

### Problem
Policies expire after 24 hours with no grace period. If agent needs longer coverage, they must:
1. Monitor expiration
2. Buy new policy before old expires
3. Risk gap in coverage

### Proposed Solution: Renewal Endpoint

```python
# New endpoint: POST /renew
POST /renew
{
  "policy_id": "uuid",
  "extend_hours": 24  // Add 24 more hours
}

Response: 200 OK
{
  "policy_id": "uuid",  // Same policy_id
  "old_expires_at": "2025-11-08T10:00:00Z",
  "new_expires_at": "2025-11-09T10:00:00Z",
  "extension_fee": 0.0001,  // 1% of coverage (same as original premium)
  "total_coverage": 0.01,
  "status": "active"
}
```

#### Implementation

```python
@app.route('/renew', methods=['POST'])
@limiter.limit("20 per hour")
def renew_policy():
    """
    Renew/extend an existing policy before expiration.

    Requires x402 payment for renewal fee (same as original premium).
    """
    data = request.json
    policy_id = data.get('policy_id')
    extend_hours = data.get('extend_hours', 24)

    if not policy_id:
        return jsonify({"error": "Missing policy_id"}), 400

    if extend_hours < 1 or extend_hours > 168:  # Max 7 days
        return jsonify({"error": "extend_hours must be between 1 and 168"}), 400

    # Load policy
    policies = load_data(POLICIES_FILE)
    policy = policies.get(policy_id)

    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    if policy['status'] != 'active':
        return jsonify({"error": "Can only renew active policies"}), 400

    # Calculate renewal fee (percentage of coverage for extended duration)
    hours_per_day = 24
    days_extended = extend_hours / hours_per_day
    renewal_fee = policy['coverage_amount'] * config.PREMIUM_PERCENTAGE * days_extended
    renewal_fee_units = to_micro(renewal_fee)

    # Check x402 payment (same as /insure endpoint)
    payment_header = request.headers.get('X-Payment')
    payer_header = request.headers.get('X-Payer')

    if not payment_header or not payer_header:
        # Return 402 with renewal fee
        return jsonify({
            "x402Version": 1,
            "payment": {
                "scheme": "exact",
                "network": "base",
                "amount": str(renewal_fee_units),
                "asset": config.USDC_CONTRACT_ADDRESS,
                "pay_to": config.BACKEND_WALLET_ADDRESS,
                "description": f"Policy renewal fee for {extend_hours} hours",
                "maxTimeoutSeconds": 60
            },
            "policy_id": policy_id,
            "extend_hours": extend_hours,
            "renewal_fee": renewal_fee,
            "current_expires_at": policy['expires_at']
        }), 402

    # Verify payment
    payment_details = payment_verifier.verify_payment(
        payment_header=payment_header,
        payer_address=payer_header,
        required_amount=renewal_fee_units,
        max_age_seconds=config.PAYMENT_MAX_AGE_SECONDS
    )

    if not payment_details.is_valid:
        return jsonify({"error": "Payment verification failed"}), 402

    # Extend policy
    old_expires_at = parse_utc(policy['expires_at'])
    new_expires_at = old_expires_at + timedelta(hours=extend_hours)

    policy['expires_at'] = new_expires_at.isoformat()
    policy['renewed_at'] = iso_utc_now()
    policy['renewal_count'] = policy.get('renewal_count', 0) + 1

    # Save
    policies[policy_id] = policy
    save_data(POLICIES_FILE, policies)

    return jsonify({
        "policy_id": policy_id,
        "old_expires_at": old_expires_at.isoformat(),
        "new_expires_at": policy['expires_at'],
        "extension_hours": extend_hours,
        "renewal_fee": renewal_fee,
        "renewal_count": policy['renewal_count'],
        "status": "active",
        "message": f"Policy extended by {extend_hours} hours"
    }), 200
```

#### Agent Usage

```python
# Scenario 1: Manual renewal before expiration
policies = requests.get(f'/policies?wallet={wallet_address}').json()
for policy in policies['active_policies']:
    expires_at = datetime.fromisoformat(policy['expires_at'].replace('Z', '+00:00'))
    time_remaining = expires_at - datetime.now(timezone.utc)

    if time_remaining < timedelta(hours=2):
        # Renew before expiration
        print(f"Renewing policy {policy['policy_id']}...")
        renewal = x402.post('/renew', json={
            'policy_id': policy['policy_id'],
            'extend_hours': 24
        })
        print(f"✅ Extended until {renewal['new_expires_at']}")

# Scenario 2: Auto-renewal (agent decision)
def should_renew(policy):
    # Agent logic: renew if merchant is still being used
    return merchant_still_in_use(policy['merchant_url'])
```

#### Benefits
✅ **No coverage gaps** - Extend before expiration
✅ **Cost-effective** - Don't need to buy new policy
✅ **Preserves policy_id** - Agents don't need to track new IDs
✅ **Flexible duration** - Extend by hours, not forced to 24h

#### Trade-offs
⚠️ **Unlimited extension risk** - Policies could be extended indefinitely
⚠️ **Pricing complexity** - Pro-rated fees might confuse agents

#### Effort
- **Development:** 1-2 days
- **Testing:** 1 day

---

## 5. 🔔 Webhook Notifications (MEDIUM IMPACT)

### Problem
Agents must poll `/claims/{claim_id}` to check status. Wasteful and adds latency.

### Proposed Solution: Webhook System

#### Architecture

```python
# New endpoints:
POST /webhooks - Register webhook
GET /webhooks - List agent's webhooks
DELETE /webhooks/{webhook_id} - Unregister webhook

# Events:
- claim.processing
- claim.paid
- claim.failed
- policy.expiring (1 hour before expiration)
- policy.expired
```

#### Registration

```python
POST /webhooks
{
  "url": "https://agent.example.com/webhooks/x402insurance",
  "events": ["claim.paid", "claim.failed", "policy.expiring"],
  "secret": "webhook_secret_for_signature_verification",
  "wallet_address": "0x..."  // Only receive events for this wallet
}

Response: 201 Created
{
  "webhook_id": "uuid",
  "url": "https://agent.example.com/webhooks/x402insurance",
  "events": ["claim.paid", "claim.failed", "policy.expiring"],
  "created_at": "2025-11-08T10:00:00Z",
  "status": "active"
}
```

#### Webhook Payloads

```python
# Event: claim.paid
POST https://agent.example.com/webhooks/x402insurance
Headers:
  X-X402Insurance-Signature: sha256=abc123...
  X-X402Insurance-Event: claim.paid
  X-X402Insurance-Delivery: uuid

Body:
{
  "event": "claim.paid",
  "timestamp": "2025-11-08T10:00:15Z",
  "data": {
    "claim_id": "uuid",
    "policy_id": "uuid",
    "payout_amount": 0.01,
    "refund_tx_hash": "0x...",
    "wallet_address": "0x...",
    "proof_url": "https://x402insurance.com/proofs/uuid"
  }
}

# Event: policy.expiring
{
  "event": "policy.expiring",
  "timestamp": "2025-11-08T09:00:00Z",
  "data": {
    "policy_id": "uuid",
    "merchant_url": "https://api.example.com",
    "expires_at": "2025-11-08T10:00:00Z",
    "time_remaining_seconds": 3600,
    "wallet_address": "0x...",
    "renewal_url": "https://x402insurance.com/renew"
  }
}
```

#### Implementation

```python
# tasks/webhook_dispatcher.py
import httpx
import hmac
import hashlib

class WebhookDispatcher:
    def __init__(self, database):
        self.database = database

    async def dispatch_event(self, event_type: str, data: dict):
        """Send webhook to all registered listeners"""
        webhooks = self.database.get_webhooks_for_event(event_type)

        for webhook in webhooks:
            # Filter by wallet address
            if webhook['wallet_address'] != data.get('wallet_address'):
                continue

            await self._send_webhook(webhook, event_type, data)

    async def _send_webhook(self, webhook, event_type, data):
        """Send individual webhook with retry"""
        payload = {
            "event": event_type,
            "timestamp": iso_utc_now(),
            "data": data
        }

        # Generate signature
        signature = self._generate_signature(
            payload=payload,
            secret=webhook['secret']
        )

        # Send with retries
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        webhook['url'],
                        json=payload,
                        headers={
                            'X-X402Insurance-Signature': signature,
                            'X-X402Insurance-Event': event_type,
                            'X-X402Insurance-Delivery': str(uuid.uuid4())
                        }
                    )

                    if response.status_code == 200:
                        break  # Success
            except Exception as e:
                if attempt == 2:
                    # Mark webhook as failing
                    self.database.increment_webhook_failure(webhook['webhook_id'])

    def _generate_signature(self, payload, secret):
        """Generate HMAC signature for webhook verification"""
        message = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(
            secret.encode(),
            message,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"


# Trigger webhooks in claim processing
async def process_claim_async(claim_id):
    # ... process claim ...

    # Trigger webhook
    await webhook_dispatcher.dispatch_event('claim.paid', {
        'claim_id': claim_id,
        'policy_id': policy['policy_id'],
        'payout_amount': claim['payout_amount'],
        'refund_tx_hash': claim['refund_tx_hash'],
        'wallet_address': policy['agent_address']
    })
```

#### Agent Webhook Receiver

```python
# Agent's webhook endpoint
from flask import Flask, request
import hmac
import hashlib

app = Flask(__name__)

WEBHOOK_SECRET = "your_webhook_secret"

@app.route('/webhooks/x402insurance', methods=['POST'])
def handle_webhook():
    """Receive webhook from x402 Insurance"""

    # Verify signature
    signature = request.headers.get('X-X402Insurance-Signature')
    if not verify_signature(request.data, signature):
        return {"error": "Invalid signature"}, 401

    # Process event
    event = request.json
    event_type = event['event']
    data = event['data']

    if event_type == 'claim.paid':
        print(f"✅ Claim paid! Received {data['payout_amount']} USDC")
        print(f"   TX: {data['refund_tx_hash']}")
        # Update agent's internal state

    elif event_type == 'policy.expiring':
        print(f"⚠️  Policy expiring in {data['time_remaining_seconds']}s")
        # Maybe renew automatically

    return {"status": "received"}, 200

def verify_signature(payload, signature_header):
    """Verify webhook signature"""
    expected_sig = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    received_sig = signature_header.replace('sha256=', '')
    return hmac.compare_digest(expected_sig, received_sig)
```

#### Benefits
✅ **Real-time notifications** - No polling needed
✅ **Reduced traffic** - Agents only notified when relevant
✅ **Better UX** - Immediate feedback
✅ **Proactive alerts** - Policy expiring warnings

#### Trade-offs
⚠️ **Complexity** - Webhook infrastructure + retry logic
⚠️ **Reliability** - What if agent's endpoint is down?
⚠️ **Security** - Need signature verification
⚠️ **Privacy** - Service needs agent's endpoint URL

#### Effort
- **Development:** 3-4 days
- **Testing:** 2 days (including retry logic)
- **Infrastructure:** Background webhook dispatcher service

---

## Summary Comparison

| Feature | Impact | Effort | ROI | Priority |
|---------|--------|--------|-----|----------|
| **Async Proof Generation** | HIGH | Medium (2-4 days) | Very High | 1 |
| **AgentKit Integration** | HIGH | Medium (4-7 days) | Very High | 2 |
| **Policy Renewal** | MEDIUM | Low (2-3 days) | High | 3 |
| **Automatic Failure Detection** | MEDIUM-HIGH | High (5-7 days) | Medium | 4 |
| **Webhook Notifications** | MEDIUM | Medium (4-6 days) | Medium | 5 |

## Recommended Implementation Order

### Phase 1 (Weeks 1-2): Quick Wins
1. **Policy Renewal** - Low effort, immediate value
2. **Async Proof Generation** (threading version) - Start with simple implementation

### Phase 2 (Weeks 3-4): Agent Adoption
3. **AgentKit Integration** - Biggest adoption driver
4. **Async Proof Generation** (Redis/Celery) - Upgrade to production version

### Phase 3 (Month 2): Advanced Features
5. **Webhook Notifications** - For power users
6. **Automatic Failure Detection** - If demand exists

---

## Questions to Consider

Before implementing, think about:

1. **Infrastructure:** Do you want to manage Redis/Celery/workers?
2. **Target audience:** Are most users using AgentKit? Or custom agents?
3. **Privacy:** Are agents comfortable with proactive monitoring?
4. **Cost:** Can you afford to monitor merchants continuously?
5. **Maintenance:** Can you support webhooks, background workers, etc.?

---

**Next Steps:**
1. Choose 1-2 features to start with
2. I can implement them if you'd like
3. Test with real agents
4. Iterate based on feedback

Which features interest you most? Want me to implement any?
