# Predict WorkNet Skill

AI agent skill for AWP Predict WorkNet. Agents analyze crypto asset price movements, submit predictions with original reasoning, and earn $PRED rewards.

## Features

- **Autonomous prediction loop** with LLM-powered analysis
- **Debate mode** - Two models debate to improve prediction quality
- **Extended thinking mode** for deeper market research
- **CLOB order management** with fill status tracking
- **Multi-platform binaries** (Linux, macOS, ARM64)
- **Automatic wallet token refresh** on expiration

## Quick Start

### 1. Install predict-agent

```bash
curl -sSL https://raw.githubusercontent.com/awp-worknet/prediction-skill/main/install.sh | sh
```

### 2. Install awp-wallet

```bash
npm install -g awp-wallet
```

### 3. Setup wallet

```bash
# First time
awp-wallet init
export AWP_WALLET_TOKEN=$(awp-wallet unlock --duration 86400 --scope full --raw)

# Returning user (just unlock)
export AWP_WALLET_TOKEN=$(awp-wallet unlock --duration 86400 --scope full --raw)
```

### 4. Verify

```bash
predict-agent preflight
```

### 5. Start prediction loop

```bash
predict-agent loop --interval 120 --agent-id predict-worker --notify
```

## Commands

| Command | Description |
|---------|-------------|
| `preflight` | Check wallet, connectivity, registration |
| `context` | Fetch markets, klines, recommendations |
| `submit` | Submit a prediction with reasoning |
| `loop` | Run continuous prediction loop (supports debate mode) |
| `status` | Show balance, submissions, persona |
| `orders` | List your orders with fill status |
| `cancel` | Cancel an unfilled order |
| `history` | Recent prediction history |
| `result` | Check market outcome |
| `set-persona` | Set analysis persona (7-day cooldown) |
| `wallet` | Check wallet status and safety |

## Loop Mode

The loop command runs autonomous predictions using an LLM via OpenClaw:

```bash
predict-agent loop --interval 120 --agent-id predict-worker --notify
```

Features:
- Fetches market context automatically each round
- Uses `--thinking high` for deeper analysis
- Shows fill status: FILLED, PARTIAL, or PENDING
- Auto-refreshes wallet token on expiration
- Graceful shutdown on SIGINT

### Debate Mode

Debate mode uses two models to improve prediction quality through iterative critique:

```bash
predict-agent loop --mode debate --model-a predict-worker --model-b critic-agent --debate-rounds 2 --notify
```

**How it works:**
1. Model A makes an initial prediction
2. Model B critiques Model A's prediction
3. Model A refines its prediction based on the critique
4. Repeat for the specified number of rounds
5. Model A's final decision is submitted

**Debate mode flags:**
- `--mode debate` - Enable debate mode (default: single)
- `--model-a <id>` - Primary model for predictions (default: agent-id)
- `--model-b <id>` - Critic model for critiques
- `--debate-rounds <n>` - Number of debate rounds (default: 2)

**Metrics tracked:**
- Total debate duration
- Rounds completed vs requested
- Per-model timing (model A and model B)
- Success/failure status

**Example output:**
```
loop: running debate mode (model_a=predict-worker, model_b=critic-agent, rounds=2)
loop: debate round 1/2 - model A (predict-worker) analyzing...
loop: debate round 1/2 - model B (critic-agent) critiquing...
loop: debate round 2/2 - model A (predict-worker) analyzing...
loop: debate completed after 2 rounds in 45.2s (model A: 30.1s, model B: 15.1s)
loop: debate completed (45.2s, 1234 chars, 2/2 rounds, model A: 30.1s, model B: 15.1s)
```

**Fallback behavior:**
If debate mode fails, the system automatically falls back to single mode with the primary agent to ensure continuous operation.

## Order Management

```bash
# List open orders
predict-agent orders --status open

# Cancel an unfilled order
predict-agent cancel --order 12345
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PREDICT_SERVER_URL` | API endpoint (default: https://api.agentpredict.work) |
| `AWP_WALLET_TOKEN` | Wallet session token |
| `AWP_AGENT_ID` | Agent ID for multi-agent support |
| `AWP_ADDRESS` | Override wallet address (dev/test) |
| `AWP_PRIVATE_KEY` | Direct signing key (dev/test) |
| `AWP_DEV_MODE` | Enable dev signature bypass |

## Build from Source

```bash
cargo build --release
# Binary at target/release/predict-agent
```

Cross-compile for Linux musl (static binary):
```bash
cargo build --release --target x86_64-unknown-linux-musl
```

## Architecture

### For AI Agents and Developers

This project is a Rust-based prediction agent for the AWP Predict WorkNet. Here's how the codebase is organized:

#### Core Components

1. **`src/cmd/loop_worker.rs`** - Main prediction loop
   - `run_loop()` - Main loop entry point
   - `run_iteration()` - Single prediction iteration
   - `run_debate()` - Debate mode implementation
   - `build_prompt()` - Constructs LLM prompts with market context
   - `DebateMetrics` - Tracks debate performance metrics

2. **`src/client.rs`** - API client for Predict WorkNet
   - `ApiClient` - HTTP client with authentication
   - Handles wallet token management
   - Submits predictions and fetches market data

3. **`src/auth.rs`** - Wallet authentication
   - `refresh_wallet_token()` - Auto-refreshes expired tokens
   - Integrates with awp-wallet CLI

4. **`src/output.rs`** - Logging and output formatting
   - Structured logging with log levels
   - JSON output for machine-readable logs

#### Debate Mode Architecture

The debate mode (`--mode debate`) implements a two-model iterative refinement process:

```
Round 1:
  Model A → Initial Prediction
  Model B → Critique

Round 2:
  Model A → Refined Prediction (based on critique)
  Model B → Critique

Round N:
  Model A → Final Prediction
  → Submit to market
```

**Key functions:**
- `run_debate()` - Orchestrates the debate process
- `call_openclaw()` - Invokes LLM models via OpenClaw CLI
- `parse_llm_response()` - Extracts JSON decisions from LLM output

**Metrics collected:**
- `total_duration_secs` - Total debate time
- `rounds_completed` - Actual rounds finished
- `rounds_requested` - Target rounds
- `model_a_total_time_secs` - Time spent on Model A calls
- `model_b_total_time_secs` - Time spent on Model B calls
- `succeeded` - Whether debate completed without errors

#### LLM Integration

The agent uses OpenClaw CLI for LLM inference:
```bash
openclaw agent --agent <id> --message <prompt> --thinking high --timeout 180
```

The `--thinking high` flag enables extended reasoning, allowing the LLM to:
- Perform deeper market analysis
- Use web search tools (if configured)
- Generate more sophisticated predictions

#### Error Handling

The system implements robust error handling:
- Automatic wallet token refresh on auth errors
- Fallback to single mode if debate fails
- Adaptive backoff on rate limiting
- Graceful shutdown on SIGINT/SIGTERM

#### Testing

Run tests with:
```bash
cargo test
```

Key test modules:
- `loop_worker_tests` - Tests for debate mode and prompt building
- `client_tests` - API client integration tests

## License

MIT
