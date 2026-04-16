"""Base blockchain platform field group specifications.

Covers all 4 subdatasets: transactions, addresses, contracts, defi.
Total: 33 field groups.
"""

from __future__ import annotations

from crawler.enrich.schemas.field_group_registry import (
    FieldGroupSpec,
    GenerativeConfig,
    OutputFieldSpec,
)

# ---------------------------------------------------------------------------
# 5.1 Transactions Dataset  (9 field groups)
# ---------------------------------------------------------------------------

_base_transactions_basic = FieldGroupSpec(
    name="base_transactions_basic",
    description="Basic transaction value and fee calculations",
    required_source_fields=["value", "gas_used", "gas_price"],
    output_fields=[
        OutputFieldSpec(name="value_usd", field_type="number", description="Transaction value in USD"),
        OutputFieldSpec(name="gas_fee_usd", field_type="number", description="Gas fee in USD"),
        OutputFieldSpec(name="tx_fee_tier", field_type="string", description="Fee tier classification (low/medium/high)"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_basic.jinja2"),
    platform="base",
    subdataset="transactions",
)

_base_transactions_input_data = FieldGroupSpec(
    name="base_transactions_input_data",
    description="Decode transaction input data into human-readable function calls and parameters",
    required_source_fields=["input", "to_address"],
    output_fields=[
        OutputFieldSpec(name="function_name", field_type="string", description="Decoded function name"),
        OutputFieldSpec(name="function_signature", field_type="string", description="Full function signature"),
        OutputFieldSpec(name="decoded_parameters", field_type="object", description="Decoded function parameters"),
        OutputFieldSpec(name="human_readable_action", field_type="string", description="Plain-English description of what the transaction does"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_input_data.jinja2", max_tokens=1024),
    platform="base",
    subdataset="transactions",
)

_base_transactions_classification = FieldGroupSpec(
    name="base_transactions_classification",
    description="Classify transaction type and identify protocol interaction",
    required_source_fields=["input", "to_address", "value"],
    output_fields=[
        OutputFieldSpec(name="tx_type", field_type="string", description="Transaction type (transfer, swap, mint, bridge, etc.)"),
        OutputFieldSpec(name="protocol_name", field_type="string", description="Protocol name if applicable"),
        OutputFieldSpec(name="protocol_category", field_type="string", description="Protocol category (DEX, lending, bridge, NFT, etc.)"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_classification.jinja2"),
    platform="base",
    subdataset="transactions",
)

_base_transactions_token_transfers = FieldGroupSpec(
    name="base_transactions_token_transfers",
    description="Extract and enrich token transfer events from transaction logs",
    required_source_fields=["logs", "tx_hash"],
    output_fields=[
        OutputFieldSpec(
            name="token_transfers",
            field_type="array<object>",
            description="Array of token transfers with token_address, token_symbol, token_name, decimals, from, to, amount, amount_usd, transfer_type",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_token_transfers.jinja2", max_tokens=2048),
    platform="base",
    subdataset="transactions",
)

_base_transactions_context = FieldGroupSpec(
    name="base_transactions_context",
    description="Detect MEV activity, contract interactions, and related transactions",
    required_source_fields=["tx_hash", "block_number", "from_address", "to_address", "input", "value", "gas_price"],
    output_fields=[
        OutputFieldSpec(name="is_mev", field_type="boolean", description="Whether this transaction involves MEV"),
        OutputFieldSpec(name="mev_type", field_type="string", description="MEV type (frontrun, backrun, sandwich, liquidation, arbitrage)", required=False),
        OutputFieldSpec(name="is_contract_interaction", field_type="boolean", description="Whether this transaction interacts with a smart contract"),
        OutputFieldSpec(name="is_internal_tx_parent", field_type="boolean", description="Whether this transaction spawns internal transactions"),
        OutputFieldSpec(name="related_tx_hashes", field_type="array<string>", description="Related transaction hashes (e.g. sandwich pair)", required=False),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_context.jinja2", max_tokens=1024),
    platform="base",
    subdataset="transactions",
)

_base_transactions_risk = FieldGroupSpec(
    name="base_transactions_risk",
    description="Assess sender/receiver risk labels, anomaly flags, and fund source tracing",
    required_source_fields=["from_address", "to_address", "value", "tx_hash"],
    output_fields=[
        OutputFieldSpec(name="sender_risk_label", field_type="string", description="Risk label for the sender address"),
        OutputFieldSpec(name="receiver_risk_label", field_type="string", description="Risk label for the receiver address"),
        OutputFieldSpec(name="anomaly_flags", field_type="array<string>", description="Detected anomaly flags"),
        OutputFieldSpec(name="fund_source_trace", field_type="string", description="Brief fund source trace narrative"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_risk.jinja2", max_tokens=1024),
    platform="base",
    subdataset="transactions",
)

_base_transactions_summary = FieldGroupSpec(
    name="base_transactions_summary",
    description="Generate multi-level narrative summaries for compliance and investor audiences",
    required_source_fields=["tx_hash", "from_address", "to_address", "value", "input"],
    output_fields=[
        OutputFieldSpec(name="compliance_narrative", field_type="string", description="Compliance-oriented transaction narrative"),
        OutputFieldSpec(name="investor_narrative", field_type="string", description="Investor-oriented transaction narrative"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_summary.jinja2", max_tokens=1024),
    platform="base",
    subdataset="transactions",
)

_base_transactions_strategy_detection = FieldGroupSpec(
    name="base_transactions_strategy_detection",
    description="Detect trading strategies and on-chain patterns in the transaction",
    required_source_fields=["tx_hash", "from_address", "to_address", "input", "value", "logs"],
    output_fields=[
        OutputFieldSpec(
            name="strategy_signal",
            field_type="object",
            description="Strategy signals: dca_pattern_hint, arbitrage_signal, sandwich_component, flash_loan_detected, batch_operation, governance_action_type",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_strategy_detection.jinja2", max_tokens=1024),
    platform="base",
    subdataset="transactions",
)

_base_transactions_linkable_ids = FieldGroupSpec(
    name="base_transactions_linkable_ids",
    description="Extract cross-dataset linkable identifiers for protocol attribution",
    required_source_fields=["to_address", "input"],
    output_fields=[
        OutputFieldSpec(
            name="linkable_identifiers",
            field_type="object",
            description="Cross-dataset links: protocol_website_hint, protocol_github_hint, protocol_wikipedia_hint",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_transactions_linkable_ids.jinja2"),
    platform="base",
    subdataset="transactions",
)

# ---------------------------------------------------------------------------
# 5.2 Addresses / Wallets Dataset  (9 field groups)
# ---------------------------------------------------------------------------

_base_addresses_basic = FieldGroupSpec(
    name="base_addresses_basic",
    description="Basic wallet balance and portfolio composition",
    required_source_fields=["address", "balance", "token_balances"],
    output_fields=[
        OutputFieldSpec(name="balance_usd", field_type="number", description="Total balance in USD"),
        OutputFieldSpec(name="total_value_locked_usd", field_type="number", description="Total value locked in DeFi protocols"),
        OutputFieldSpec(
            name="portfolio_composition",
            field_type="array<object>",
            description="Portfolio breakdown: token, amount, usd_value, percentage",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_basic.jinja2", max_tokens=1024),
    platform="base",
    subdataset="addresses",
)

_base_addresses_identity = FieldGroupSpec(
    name="base_addresses_identity",
    description="Resolve address identity: labels, ENS names, contract detection, and entity attribution",
    required_source_fields=["address", "code"],
    output_fields=[
        OutputFieldSpec(name="label", field_type="string", description="Address label (e.g. Uniswap V3 Router)"),
        OutputFieldSpec(name="entity_name", field_type="string", description="Entity name if known"),
        OutputFieldSpec(name="ens_name", field_type="string", description="ENS domain name if available", required=False),
        OutputFieldSpec(name="is_contract", field_type="boolean", description="Whether the address is a smart contract"),
        OutputFieldSpec(name="contract_type", field_type="string", description="Contract type if applicable (ERC20, ERC721, proxy, etc.)", required=False),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_identity.jinja2"),
    platform="base",
    subdataset="addresses",
)

_base_addresses_activity = FieldGroupSpec(
    name="base_addresses_activity",
    description="Summarize wallet activity: volume, frequency, primary activities, and protocol usage",
    required_source_fields=["address", "transactions"],
    output_fields=[
        OutputFieldSpec(
            name="activity_summary",
            field_type="object",
            description="Activity metrics: total_volume_usd, avg_tx_per_day, active_days, primary_activities, most_used_protocols",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_activity.jinja2", max_tokens=1024),
    platform="base",
    subdataset="addresses",
)

_base_addresses_defi = FieldGroupSpec(
    name="base_addresses_defi",
    description="Enumerate DeFi positions held by the address",
    required_source_fields=["address", "defi_positions_raw"],
    output_fields=[
        OutputFieldSpec(
            name="defi_positions",
            field_type="array<object>",
            description="DeFi positions: protocol, pool, position_type, token_pair, value_usd, apy_at_entry, pnl_estimated",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_defi.jinja2", max_tokens=2048),
    platform="base",
    subdataset="addresses",
)

_base_addresses_nft = FieldGroupSpec(
    name="base_addresses_nft",
    description="Enumerate NFT holdings and calculate trading P&L",
    required_source_fields=["address", "nft_transfers"],
    output_fields=[
        OutputFieldSpec(
            name="nft_holdings",
            field_type="array<object>",
            description="NFT holdings: collection, token_id, acquired_date, acquired_price_usd, current_floor_usd",
        ),
        OutputFieldSpec(name="nft_trading_pnl", field_type="number", description="Net NFT trading profit/loss in USD"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_nft.jinja2", max_tokens=2048),
    platform="base",
    subdataset="addresses",
)

_base_addresses_behavioral = FieldGroupSpec(
    name="base_addresses_behavioral",
    description="Classify wallet archetype, trading patterns, and sophistication metrics",
    required_source_fields=["address", "transactions"],
    output_fields=[
        OutputFieldSpec(name="wallet_archetype", field_type="string", description="Wallet archetype (whale, retail, bot, institution, etc.)"),
        OutputFieldSpec(name="trading_pattern", field_type="string", description="Dominant trading pattern (HODLer, day-trader, yield-farmer, etc.)"),
        OutputFieldSpec(name="risk_appetite_score", field_type="number", description="Risk appetite score 0-100"),
        OutputFieldSpec(name="sophistication_score", field_type="number", description="On-chain sophistication score 0-100"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_behavioral.jinja2"),
    platform="base",
    subdataset="addresses",
)

_base_addresses_risk = FieldGroupSpec(
    name="base_addresses_risk",
    description="Assess address risk: sanctions screening, mixer interactions, high-risk counterparties",
    required_source_fields=["address", "transactions"],
    output_fields=[
        OutputFieldSpec(name="risk_score", field_type="number", description="Composite risk score 0-100"),
        OutputFieldSpec(name="sanctions_match", field_type="boolean", description="Whether the address matches any sanctions list"),
        OutputFieldSpec(name="mixer_interaction_count", field_type="integer", description="Number of interactions with known mixers"),
        OutputFieldSpec(name="high_risk_counterparties", field_type="array<string>", description="Addresses of high-risk counterparties"),
        OutputFieldSpec(name="fund_flow_risk_path", field_type="array<string>", description="Risk-relevant fund flow path"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_risk.jinja2", max_tokens=1024),
    platform="base",
    subdataset="addresses",
)

_base_addresses_summary = FieldGroupSpec(
    name="base_addresses_summary",
    description="Generate multi-level wallet summaries for quick overview, compliance, and investor profiles",
    required_source_fields=["address", "balance", "transactions"],
    output_fields=[
        OutputFieldSpec(name="wallet_one_liner", field_type="string", description="One-line wallet summary"),
        OutputFieldSpec(name="compliance_profile_summary", field_type="string", description="Compliance-oriented wallet profile"),
        OutputFieldSpec(name="investor_profile_summary", field_type="string", description="Investor-oriented wallet profile"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_summary.jinja2", max_tokens=1024),
    platform="base",
    subdataset="addresses",
)

_base_addresses_intelligence = FieldGroupSpec(
    name="base_addresses_intelligence",
    description="Advanced address intelligence: cross-chain hints, deployer analysis, token approval risks",
    required_source_fields=["address", "transactions", "code"],
    output_fields=[
        OutputFieldSpec(
            name="cross_chain_address_hint",
            field_type="object",
            description="Cross-chain presence hints: same_nonce_pattern_chains",
        ),
        OutputFieldSpec(name="deployer_analysis", field_type="string", description="Analysis of contracts deployed by this address"),
        OutputFieldSpec(
            name="token_approval_risk",
            field_type="object",
            description="Token approval risks: unlimited_approvals_count, high_risk_approvals",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_addresses_intelligence.jinja2", max_tokens=1024),
    platform="base",
    subdataset="addresses",
)

# ---------------------------------------------------------------------------
# 5.3 Smart Contracts Dataset  (8 field groups)
# ---------------------------------------------------------------------------

_base_contracts_basic = FieldGroupSpec(
    name="base_contracts_basic",
    description="Basic contract metadata: name, verification status, compiler version",
    required_source_fields=["address", "code"],
    output_fields=[
        OutputFieldSpec(name="contract_name", field_type="string", description="Contract name"),
        OutputFieldSpec(name="is_verified", field_type="boolean", description="Whether the source code is verified"),
        OutputFieldSpec(name="compiler_version", field_type="string", description="Solidity compiler version"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_basic.jinja2"),
    platform="base",
    subdataset="contracts",
)

_base_contracts_code = FieldGroupSpec(
    name="base_contracts_code",
    description="Classify contract type, identify protocol, and detect implemented standards",
    required_source_fields=["address", "source_code", "abi"],
    output_fields=[
        OutputFieldSpec(name="contract_type_classified", field_type="string", description="Contract type (ERC20, ERC721, DEX, lending, etc.)"),
        OutputFieldSpec(name="protocol_name", field_type="string", description="Protocol name if identifiable"),
        OutputFieldSpec(name="implements_standards", field_type="array<string>", description="Implemented standards (ERC20, ERC721, ERC1155, etc.)"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_code.jinja2"),
    platform="base",
    subdataset="contracts",
)

_base_contracts_analysis = FieldGroupSpec(
    name="base_contracts_analysis",
    description="Analyze contract functions, admin privileges, upgrade mechanisms, and access controls",
    required_source_fields=["address", "source_code", "abi"],
    output_fields=[
        OutputFieldSpec(
            name="functions_summary",
            field_type="array<object>",
            description="Function summaries: name, purpose, access_control, state_mutability",
        ),
        OutputFieldSpec(name="admin_functions", field_type="array<string>", description="Functions restricted to admin/owner"),
        OutputFieldSpec(name="upgrade_mechanism", field_type="string", description="Upgrade mechanism (none, transparent proxy, UUPS, beacon, diamond)"),
        OutputFieldSpec(name="has_pausable", field_type="boolean", description="Whether the contract can be paused"),
        OutputFieldSpec(name="has_blacklist", field_type="boolean", description="Whether the contract has blacklist functionality"),
        OutputFieldSpec(name="owner_privileges", field_type="array<string>", description="Enumeration of owner/admin privileges"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_analysis.jinja2", max_tokens=2048),
    platform="base",
    subdataset="contracts",
)

_base_contracts_security = FieldGroupSpec(
    name="base_contracts_security",
    description="Security assessment: vulnerabilities, audit status, reentrancy risk, centralization risk",
    required_source_fields=["address", "source_code", "abi"],
    output_fields=[
        OutputFieldSpec(name="known_vulnerabilities", field_type="array<string>", description="Known vulnerability patterns detected"),
        OutputFieldSpec(name="audit_status", field_type="string", description="Audit status (audited, unaudited, partially audited)"),
        OutputFieldSpec(name="audit_firms", field_type="array<string>", description="Auditing firms if known"),
        OutputFieldSpec(name="reentrancy_risk", field_type="string", description="Reentrancy risk level (none, low, medium, high)"),
        OutputFieldSpec(name="centralization_risk_score", field_type="number", description="Centralization risk score 0-100"),
        OutputFieldSpec(name="proxy_implementation_history", field_type="array<string>", description="History of proxy implementation addresses"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_security.jinja2", max_tokens=1024),
    platform="base",
    subdataset="contracts",
)

_base_contracts_usage = FieldGroupSpec(
    name="base_contracts_usage",
    description="Contract usage metrics: interaction counts, unique users, TVL, and activity trends",
    required_source_fields=["address", "transactions"],
    output_fields=[
        OutputFieldSpec(name="total_interactions", field_type="integer", description="Total number of interactions"),
        OutputFieldSpec(name="unique_users", field_type="integer", description="Number of unique interacting addresses"),
        OutputFieldSpec(name="tvl_current_usd", field_type="number", description="Current total value locked in USD"),
        OutputFieldSpec(name="tvl_30d_trend", field_type="string", description="TVL trend over 30 days (increasing, decreasing, stable)"),
        OutputFieldSpec(name="daily_active_users_avg", field_type="number", description="Average daily active users"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_usage.jinja2"),
    platform="base",
    subdataset="contracts",
)

_base_contracts_code_comprehension = FieldGroupSpec(
    name="base_contracts_code_comprehension",
    description="Deep code comprehension: plain-English function explanations, admin risk narrative, code quality",
    required_source_fields=["address", "source_code"],
    output_fields=[
        OutputFieldSpec(name="contract_purpose_summary", field_type="string", description="Plain-English summary of what the contract does"),
        OutputFieldSpec(
            name="function_explanations",
            field_type="array<object>",
            description="Per-function explanations: function_name, plain_english_description, risk_assessment, risk_reasoning",
        ),
        OutputFieldSpec(name="admin_risk_narrative", field_type="string", description="Narrative assessment of admin/owner risks"),
        OutputFieldSpec(
            name="code_quality_indicators",
            field_type="object",
            description="Quality indicators: has_comments, comment_density, follows_style_guide, uses_safe_math, has_reentrancy_guards, has_access_control, notable_patterns",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_code_comprehension.jinja2", max_tokens=4096, temperature=0.1),
    platform="base",
    subdataset="contracts",
)

_base_contracts_summary = FieldGroupSpec(
    name="base_contracts_summary",
    description="Multi-level contract summaries: one-liner, security overview, developer-oriented analysis",
    required_source_fields=["address", "source_code", "abi"],
    output_fields=[
        OutputFieldSpec(name="contract_one_liner", field_type="string", description="One-line contract summary"),
        OutputFieldSpec(name="security_summary", field_type="string", description="Security-focused summary"),
        OutputFieldSpec(name="developer_summary", field_type="string", description="Developer-oriented technical summary"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_summary.jinja2", max_tokens=1024),
    platform="base",
    subdataset="contracts",
)

_base_contracts_linkable_ids = FieldGroupSpec(
    name="base_contracts_linkable_ids",
    description="Extract cross-dataset linkable identifiers for smart contracts",
    required_source_fields=["address", "source_code"],
    output_fields=[
        OutputFieldSpec(
            name="linkable_identifiers",
            field_type="object",
            description="Cross-dataset links: github_source_url, audit_report_urls, protocol_website, author_github_hint, license_type",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_contracts_linkable_ids.jinja2"),
    platform="base",
    subdataset="contracts",
)

# ---------------------------------------------------------------------------
# 5.4 DeFi Protocol Aggregated Dataset  (7 field groups)
# ---------------------------------------------------------------------------

_base_defi_protocol = FieldGroupSpec(
    name="base_defi_protocol",
    description="Core protocol metadata: name, category, contracts, governance token, and links",
    required_source_fields=["protocol_id"],
    output_fields=[
        OutputFieldSpec(name="protocol_name", field_type="string", description="Protocol name"),
        OutputFieldSpec(name="protocol_category", field_type="string", description="Category (DEX, lending, yield, bridge, etc.)"),
        OutputFieldSpec(name="main_contracts", field_type="array<string>", description="Main contract addresses"),
        OutputFieldSpec(name="website", field_type="string", description="Protocol website URL"),
        OutputFieldSpec(name="documentation_url", field_type="string", description="Documentation URL"),
        OutputFieldSpec(name="governance_token", field_type="string", description="Governance token symbol or address"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_protocol.jinja2"),
    platform="base",
    subdataset="defi",
)

_base_defi_metrics = FieldGroupSpec(
    name="base_defi_metrics",
    description="Protocol-level metrics: TVL, volume, users, fees, and revenue",
    required_source_fields=["protocol_id", "raw_metrics"],
    output_fields=[
        OutputFieldSpec(name="tvl_usd", field_type="number", description="Total value locked in USD"),
        OutputFieldSpec(name="tvl_change_24h_7d_30d", field_type="string", description="TVL change percentages over 24h, 7d, 30d"),
        OutputFieldSpec(name="total_volume_24h", field_type="number", description="24-hour trading volume in USD"),
        OutputFieldSpec(name="total_users", field_type="integer", description="Total unique users"),
        OutputFieldSpec(name="daily_active_users", field_type="number", description="Daily active user count"),
        OutputFieldSpec(name="total_fees_24h", field_type="number", description="Total fees collected in 24h in USD"),
        OutputFieldSpec(name="total_revenue_24h", field_type="number", description="Total protocol revenue in 24h in USD"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_metrics.jinja2"),
    platform="base",
    subdataset="defi",
)

_base_defi_pools = FieldGroupSpec(
    name="base_defi_pools",
    description="Enumerate protocol liquidity pools with key metrics",
    required_source_fields=["protocol_id", "pools_raw"],
    output_fields=[
        OutputFieldSpec(
            name="pools",
            field_type="array<object>",
            description="Pool details: pool_address, token_pair, tvl, volume_24h, apy, fee_tier, utilization_rate",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_pools.jinja2", max_tokens=4096),
    platform="base",
    subdataset="defi",
)

_base_defi_risk = FieldGroupSpec(
    name="base_defi_risk",
    description="Protocol risk assessment: smart contract risk, centralization, oracle dependency, insurance",
    required_source_fields=["protocol_id"],
    output_fields=[
        OutputFieldSpec(name="protocol_risk_score", field_type="number", description="Composite protocol risk score 0-100"),
        OutputFieldSpec(name="smart_contract_risk", field_type="string", description="Smart contract risk level (low, medium, high)"),
        OutputFieldSpec(name="centralization_risk", field_type="string", description="Centralization risk level"),
        OutputFieldSpec(name="oracle_dependency", field_type="string", description="Oracle dependency description"),
        OutputFieldSpec(name="insurance_coverage", field_type="string", description="Insurance coverage status"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_risk.jinja2"),
    platform="base",
    subdataset="defi",
)

_base_defi_llm_enhanced = FieldGroupSpec(
    name="base_defi_llm_enhanced",
    description="LLM-generated protocol intelligence: summary, competitive analysis, differentiators, risk narrative, governance",
    required_source_fields=["protocol_id"],
    output_fields=[
        OutputFieldSpec(name="protocol_summary", field_type="string", description="Comprehensive protocol summary"),
        OutputFieldSpec(name="competitive_landscape", field_type="string", description="Competitive landscape analysis"),
        OutputFieldSpec(name="key_differentiators", field_type="array<string>", description="Key protocol differentiators"),
        OutputFieldSpec(name="risk_narrative", field_type="string", description="Risk-focused narrative"),
        OutputFieldSpec(name="recent_governance_decisions", field_type="array<string>", description="Recent governance decisions and their impact"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_llm_enhanced.jinja2", max_tokens=2048),
    platform="base",
    subdataset="defi",
)

_base_defi_governance_analysis = FieldGroupSpec(
    name="base_defi_governance_analysis",
    description="Analyze governance proposals: plain-English summaries, impact assessment, risk and controversy",
    required_source_fields=["protocol_id", "governance_proposals_raw"],
    output_fields=[
        OutputFieldSpec(
            name="governance_proposal_analysis",
            field_type="object",
            description="Proposal analysis: proposal_id, plain_english_summary, impact_assessment, risk_implications, controversy_indicators",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_governance_analysis.jinja2", max_tokens=2048),
    platform="base",
    subdataset="defi",
)

_base_defi_linkable_ids = FieldGroupSpec(
    name="base_defi_linkable_ids",
    description="Extract cross-dataset linkable identifiers for DeFi protocols",
    required_source_fields=["protocol_id"],
    output_fields=[
        OutputFieldSpec(
            name="linkable_identifiers",
            field_type="object",
            description="Cross-dataset links: team_linkedin_hints, arxiv_paper_hints, github_org_url, wikipedia_hint",
        ),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="base_defi_linkable_ids.jinja2"),
    platform="base",
    subdataset="defi",
)

# ---------------------------------------------------------------------------
# Public registry — 33 field groups total
# ---------------------------------------------------------------------------

BASE_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    # Transactions (9)
    _base_transactions_basic.name: _base_transactions_basic,
    _base_transactions_input_data.name: _base_transactions_input_data,
    _base_transactions_classification.name: _base_transactions_classification,
    _base_transactions_token_transfers.name: _base_transactions_token_transfers,
    _base_transactions_context.name: _base_transactions_context,
    _base_transactions_risk.name: _base_transactions_risk,
    _base_transactions_summary.name: _base_transactions_summary,
    _base_transactions_strategy_detection.name: _base_transactions_strategy_detection,
    _base_transactions_linkable_ids.name: _base_transactions_linkable_ids,
    # Addresses (9)
    _base_addresses_basic.name: _base_addresses_basic,
    _base_addresses_identity.name: _base_addresses_identity,
    _base_addresses_activity.name: _base_addresses_activity,
    _base_addresses_defi.name: _base_addresses_defi,
    _base_addresses_nft.name: _base_addresses_nft,
    _base_addresses_behavioral.name: _base_addresses_behavioral,
    _base_addresses_risk.name: _base_addresses_risk,
    _base_addresses_summary.name: _base_addresses_summary,
    _base_addresses_intelligence.name: _base_addresses_intelligence,
    # Contracts (8)
    _base_contracts_basic.name: _base_contracts_basic,
    _base_contracts_code.name: _base_contracts_code,
    _base_contracts_analysis.name: _base_contracts_analysis,
    _base_contracts_security.name: _base_contracts_security,
    _base_contracts_usage.name: _base_contracts_usage,
    _base_contracts_code_comprehension.name: _base_contracts_code_comprehension,
    _base_contracts_summary.name: _base_contracts_summary,
    _base_contracts_linkable_ids.name: _base_contracts_linkable_ids,
    # DeFi (7)
    _base_defi_protocol.name: _base_defi_protocol,
    _base_defi_metrics.name: _base_defi_metrics,
    _base_defi_pools.name: _base_defi_pools,
    _base_defi_risk.name: _base_defi_risk,
    _base_defi_llm_enhanced.name: _base_defi_llm_enhanced,
    _base_defi_governance_analysis.name: _base_defi_governance_analysis,
    _base_defi_linkable_ids.name: _base_defi_linkable_ids,
}
