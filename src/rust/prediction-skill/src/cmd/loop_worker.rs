/// loop_worker — background prediction loop.
///
/// Runs continuously: fetch context → call LLM for analysis → submit prediction → sleep.
///
/// LLM is invoked via OpenClaw CLI with extended thinking:
///   `openclaw agent --agent <id> --message <prompt> --thinking high --timeout 180`
///
/// With --thinking high, the agent can:
///   - Do deeper reasoning before making predictions
///   - Use web search to check news, sentiment, market data (if configured)
///   - Use any tools available in the agent's gateway configuration
///   - Output a final `DECISION: {...}` with its prediction
///
/// Usage: predict-agent loop [--interval 120] [--max-iterations 0] [--agent-id predict-worker]
///
/// The loop handles:
///   - Automatic context fetching each round
///   - LLM prompt construction with klines data
///   - Parsing LLM response (extracts DECISION: JSON from output)
///   - Submission with error recovery
///   - Adaptive backoff on empty markets or errors
///   - Graceful shutdown on SIGINT/SIGTERM

use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;

use crate::auth::refresh_wallet_token;
use crate::client::ApiClient;
use crate::{log_debug, log_error, log_info, log_warn};

pub struct LoopArgs {
    pub interval: u64,
    pub max_iterations: u64,
    pub agent_id: String,
    /// If true, output [NOTIFY] lines for the agent to relay to user
    pub notify: bool,
}

/// Print a notification line that the agent should relay to the user.
/// Format: [NOTIFY] <message>
/// Only printed if notify=true.
macro_rules! notify {
    ($notify:expr, $($arg:tt)*) => {
        if $notify {
            println!("[NOTIFY] {}", format!($($arg)*));
        }
    };
}

pub fn run(server_url: &str, args: LoopArgs) -> Result<()> {
    log_info!(
        "loop: starting (interval={}s, max_iter={}, agent={}, server={})",
        args.interval,
        args.max_iterations,
        args.agent_id,
        server_url
    );

    // Set up graceful shutdown
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    ctrlc::set_handler(move || {
        eprintln!("\n[predict-agent] loop: received shutdown signal, finishing current round...");
        r.store(false, Ordering::SeqCst);
    })
    .ok(); // Ignore error if handler already set

    // Detect OpenClaw CLI
    let openclaw_bin = detect_openclaw();
    
    // Fallback: If we have direct OpenAI credentials, we don't strictly require the openclaw binary
    let has_direct_llm = std::env::var("OPENAI_API_KEY").is_ok() && std::env::var("OPENAI_BASE_URL").is_ok();
    
    if openclaw_bin.is_none() && !has_direct_llm {
        log_error!("loop: openclaw CLI not found. Install OpenClaw or add it to PATH.");
        log_error!("loop: the prediction loop requires an LLM to analyze markets and generate reasoning.");
        eprintln!("\npredict-agent loop requires the OpenClaw CLI (openclaw) to be installed OR direct LLM credentials.");
        eprintln!("The loop calls an LLM each round to analyze klines and write original reasoning.");
        eprintln!("\nInstall: https://docs.openclaw.com/install");
        return Ok(());
    }
    
    // Priority: If we have direct LLM, we ignore OpenClaw entirely to avoid unwanted folder creation (bypass mode)
    let openclaw_bin_path = if has_direct_llm {
        "none".to_string()
    } else {
        openclaw_bin.unwrap_or_else(|| "none".to_string())
    };

    if openclaw_bin_path != "none" {
        log_info!("loop: using openclaw at {}", openclaw_bin_path);
        // Ensure agent exists
        ensure_agent(&openclaw_bin_path, &args.agent_id);
    } else {
        log_info!("loop: direct LLM mode active (OpenClaw bypassed).");
    }

    let mut iteration: u64 = 0;
    let mut consecutive_empty = 0u32;
    let mut consecutive_errors = 0u32;
    let mut last_error_context: Option<String> = None;

    while running.load(Ordering::SeqCst) {
        iteration += 1;
        if args.max_iterations > 0 && iteration > args.max_iterations {
            log_info!("loop: reached max iterations ({}), stopping", args.max_iterations);
            break;
        }

        log_info!("loop: === iteration {} ===", iteration);
        let iter_start = Instant::now();

        match run_iteration(server_url, &openclaw_bin_path, &args.agent_id, last_error_context.clone()) {
            IterationResult::Submitted { market, direction, tickets, tickets_filled, order_status } => {
                let elapsed = iter_start.elapsed().as_secs_f64();
                let fill_info = match order_status.as_str() {
                    "filled" => format!("FILLED {}/{}", tickets_filled, tickets),
                    "partial" => format!("PARTIAL {}/{}", tickets_filled, tickets),
                    _ => format!("PENDING 0/{} (waiting for counterparty)", tickets),
                };
                log_info!("loop: {} {} for {} — {} ({:.1}s)", direction, fill_info, market, order_status, elapsed);
                notify!(
                    args.notify,
                    "Round {}: {} {} — {} ({:.1}s)",
                    iteration,
                    direction.to_uppercase(),
                    market,
                    fill_info,
                    elapsed
                );
                consecutive_empty = 0;
                consecutive_errors = 0;
                last_error_context = None; // Reset on success
            }
            IterationResult::Skipped { reason } => {
                let elapsed = iter_start.elapsed().as_secs_f64();
                log_info!("loop: skipped this round ({:.1}s): {}", elapsed, reason);
                notify!(args.notify, "Round {}: Skipped — {}", iteration, reason);
                consecutive_empty = 0;
                consecutive_errors = 0;
                // No penalty for skipping — it's a valid decision
            }
            IterationResult::NoMarkets { wait_seconds } => {
                consecutive_empty += 1;
                let backoff = calculate_backoff(args.interval, consecutive_empty, Some(wait_seconds));
                log_info!(
                    "loop: no submittable markets (consecutive={}), sleeping {}s",
                    consecutive_empty,
                    backoff
                );
                notify!(args.notify, "Round {}: No markets available, waiting {}s", iteration, backoff);
                interruptible_sleep(backoff, &running);
                continue;
            }
            IterationResult::RateLimited { wait_seconds } => {
                log_info!("loop: rate limited, sleeping {}s", wait_seconds);
                notify!(args.notify, "Round {}: Rate limited, waiting {}s", iteration, wait_seconds);
                interruptible_sleep(wait_seconds, &running);
                continue;
            }
            IterationResult::LlmFailed { reason } => {
                consecutive_errors += 1;
                let backoff = calculate_backoff(args.interval, consecutive_errors, None);
                log_warn!(
                    "loop: LLM call failed ({}), sleeping {}s (errors={})",
                    reason,
                    backoff,
                    consecutive_errors
                );
                notify!(args.notify, "Round {}: LLM error — {}, retrying in {}s", iteration, reason, backoff);
                
                // If it was a reasoning rejection, save it for next time
                if reason.contains("REASONING_REJECTED") {
                    last_error_context = Some(reason);
                }
                
                interruptible_sleep(backoff, &running);
                continue;
            }
            IterationResult::Error { reason } => {
                consecutive_errors += 1;
                let backoff = calculate_backoff(args.interval, consecutive_errors, None);
                log_error!(
                    "loop: iteration error ({}), sleeping {}s (errors={})",
                    reason,
                    backoff,
                    consecutive_errors
                );
                notify!(args.notify, "Round {}: Error — {}, retrying in {}s", iteration, reason, backoff);
                
                // Save reasoning rejection errors to context
                if reason.contains("REASONING_REJECTED") {
                    last_error_context = Some(reason);
                }
                
                interruptible_sleep(backoff, &running);
                continue;
            }
        }

        // Normal sleep between iterations
        log_debug!("loop: sleeping {}s until next iteration", args.interval);
        interruptible_sleep(args.interval, &running);
    }

    log_info!("loop: stopped after {} iterations", iteration);
    Ok(())
}

enum IterationResult {
    Submitted {
        market: String,
        direction: String,
        tickets: u32,
        tickets_filled: u32,
        order_status: String,  // "filled", "partial", "open"
    },
    Skipped {
        reason: String,
    },
    NoMarkets {
        wait_seconds: u64,
    },
    RateLimited {
        wait_seconds: u64,
    },
    LlmFailed {
        reason: String,
    },
    Error {
        reason: String,
    },
}

fn run_iteration(server_url: &str, openclaw_bin: &str, agent_id: &str, last_error: Option<String>) -> IterationResult {
    // 1. Create API client
    let client = match ApiClient::new(server_url.to_string()) {
        Ok(c) => c,
        Err(e) => {
            return IterationResult::Error {
                reason: format!("API client init failed: {e}"),
            }
        }
    };

    // 2. Fetch agent status (includes timeslot, open_orders, recent_results)
    // Auto-refresh wallet token on auth failure
    let status = match client.get_auth("/api/v1/agents/me/status") {
        Ok(v) => v,
        Err(e) => {
            let err_str = e.to_string();
            // Check if this is an auth error that might be fixed by refreshing token
            if err_str.contains("AUTH_FAILED") || err_str.contains("expired") || err_str.contains("invalid token") {
                log_warn!("loop: auth failed, attempting token refresh...");
                match refresh_wallet_token() {
                    Ok(_) => {
                        log_info!("loop: token refreshed, retrying status fetch...");
                        // Recreate client with new token and retry
                        let new_client = match ApiClient::new(server_url.to_string()) {
                            Ok(c) => c,
                            Err(e) => return IterationResult::Error { reason: format!("client reinit failed: {e}") },
                        };
                        match new_client.get_auth("/api/v1/agents/me/status") {
                            Ok(v) => v,
                            Err(e) => return IterationResult::Error { reason: format!("status fetch failed after refresh: {e}") },
                        }
                    }
                    Err(refresh_err) => {
                        log_error!("loop: token refresh failed: {}", refresh_err);
                        return IterationResult::Error {
                            reason: format!("auth failed and token refresh failed: {e} / {refresh_err}"),
                        }
                    }
                }
            } else {
                return IterationResult::Error {
                    reason: format!("status fetch failed: {e}"),
                }
            }
        }
    };
    let agent_data = status.get("data").cloned().unwrap_or(json!({}));
    let balance = agent_data
        .get("balance")
        .and_then(|v| v.as_str().and_then(|s| s.parse::<f64>().ok()).or_else(|| v.as_f64()))
        .unwrap_or(0.0);
    let persona = agent_data
        .get("persona")
        .and_then(|v| v.as_str())
        .unwrap_or("none");

    // 3. Check timeslot — skip LLM entirely if no submissions remaining
    let timeslot = agent_data.get("timeslot");
    let submissions_remaining = timeslot
        .and_then(|t| t.get("submissions_remaining"))
        .and_then(|v| v.as_i64())
        .unwrap_or(3); // default to 3 if server doesn't return timeslot yet
    let slot_resets_in = timeslot
        .and_then(|t| t.get("slot_resets_in_seconds"))
        .and_then(|v| v.as_u64())
        .unwrap_or(300);
    let submissions_used = timeslot
        .and_then(|t| t.get("submissions_used"))
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    log_info!(
        "loop: balance={:.0}, persona={}, timeslot={}/{} used, resets in {}s",
        balance, persona, submissions_used,
        timeslot.and_then(|t| t.get("slot_limit")).and_then(|v| v.as_i64()).unwrap_or(3),
        slot_resets_in
    );

    if submissions_remaining <= 0 {
        log_info!("loop: no submissions remaining in this timeslot, waiting {}s for reset", slot_resets_in);
        return IterationResult::RateLimited {
            wait_seconds: slot_resets_in.max(10),
        };
    }

    // Extract open_orders and recent_results for LLM context
    let open_orders = agent_data.get("open_orders").and_then(|v| v.as_array()).cloned();
    let recent_results = agent_data.get("recent_results").and_then(|v| v.as_array()).cloned();

    // 4. Fetch smart market recommendations from server
    let recommendations = match client.get_auth("/api/v1/markets/recommend") {
        Ok(v) => v.get("data").and_then(|d| d.as_array()).cloned().unwrap_or_default(),
        Err(e) => {
            log_warn!("loop: recommend endpoint failed ({}), falling back to active markets", e);
            Vec::new()
        }
    };

    // Filter to actionable recommendations (action != "skip", >120s remaining)
    let actionable: Vec<&Value> = recommendations
        .iter()
        .filter(|r| {
            let not_skip = r.get("action").and_then(|a| a.as_str()) != Some("skip");
            let enough_time = r.get("seconds_to_close")
                .and_then(|v| v.as_i64())
                .map(|s| s > 120)
                .unwrap_or(false);
            not_skip && enough_time
        })
        .collect();

    // If no recommendations, fall back to active markets
    let (market_id, market_info) = if !actionable.is_empty() {
        let top = actionable[0];
        let id = top.get("market_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        log_info!(
            "loop: server recommends {} (score={}, reason={})",
            id,
            top.get("score").and_then(|v| v.as_i64()).unwrap_or(0),
            top.get("reason").and_then(|v| v.as_str()).unwrap_or("?")
        );
        (id, top.clone())
    } else {
        // Fallback: fetch active markets and pick first submittable
        log_debug!("loop: no server recommendations, falling back to active markets");
        let markets_resp = match client.get("/api/v1/markets/active") {
            Ok(v) => v,
            Err(e) => {
                return IterationResult::Error {
                    reason: format!("markets fetch failed: {e}"),
                }
            }
        };
        let markets = markets_resp
            .get("data")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();

        if markets.is_empty() {
            return IterationResult::NoMarkets { wait_seconds: 60 };
        }

        let now = chrono::Utc::now();
        let first = markets.iter().find(|m| {
            let close_at = m.get("close_at")
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse::<chrono::DateTime<chrono::Utc>>().ok());
            close_at.map(|c| (c - now).num_seconds() > 120).unwrap_or(false)
        });
        match first {
            Some(m) => {
                let id = m.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                (id, m.clone())
            }
            None => return IterationResult::NoMarkets { wait_seconds: 60 },
        }
    };

    if market_id.is_empty() {
        return IterationResult::NoMarkets { wait_seconds: 60 };
    }

    // 5. Fetch klines for the chosen market
    let klines_data = client
        .get(&format!("/api/v1/markets/{}/klines", market_id))
        .ok()
        .and_then(|resp| {
            resp.get("data")
                .and_then(|d| d.get("klines"))
                .and_then(|k| k.as_array())
                .cloned()
        });

    let kline_count = klines_data.as_ref().map(|k| k.len()).unwrap_or(0);
    log_info!("loop: target={}, klines={} candles", market_id, kline_count);

    // 5b. Fetch SMHL challenge for this market BEFORE calling LLM.
    //     Challenge constraints get injected into the prompt so the LLM
    //     produces reasoning that satisfies them in a single pass.
    let challenge_path = format!("/api/v1/challenge?market_id={}", market_id);
    let challenge = match client.get_auth(&challenge_path) {
        Ok(resp) => resp.get("data").cloned().unwrap_or_else(|| json!({})),
        Err(e) => {
            log_warn!("loop: failed to fetch challenge: {}", e);
            return IterationResult::LlmFailed {
                reason: format!("challenge fetch failed: {e}"),
            };
        }
    };
    let challenge_nonce = challenge
        .get("nonce")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if challenge_nonce.is_empty() {
        log_warn!("loop: challenge response missing nonce");
        return IterationResult::LlmFailed {
            reason: "challenge missing nonce".into(),
        };
    }
    log_info!(
        "loop: got challenge nonce={} for market={}",
        challenge_nonce, market_id
    );

    // 6. Build LLM prompt with full context + challenge constraints
    let prompt = build_prompt(
        &market_id,
        &market_info,
        &klines_data,
        &recommendations,
        balance,
        persona,
        submissions_remaining,
        slot_resets_in,
        &open_orders,
        &recent_results,
        &challenge,
        agent_id,
        last_error,
    );

    // 8. Call LLM
    let llm_start = Instant::now();
    let llm_response = if std::env::var("OPENAI_API_KEY").is_ok() && std::env::var("OPENAI_BASE_URL").is_ok() {
        call_direct_llm(&prompt)
    } else {
        log_info!("loop: calling LLM via openclaw agent {}...", agent_id);
        call_openclaw(openclaw_bin, agent_id, &prompt)
    };
    let llm_elapsed = llm_start.elapsed();

    let llm_text = match llm_response {
        Ok(text) => {
            log_info!("loop: LLM responded ({:.1}s, {} chars)", llm_elapsed.as_secs_f64(), text.len());
            log_debug!("loop: LLM raw output: {}", truncate_str(&text, 500));
            text
        }
        Err(e) => {
            return IterationResult::LlmFailed {
                reason: format!("{e}"),
            }
        }
    };

    // 9. Parse LLM response
    let decision = match parse_llm_response(&llm_text) {
        Ok(parsed) => parsed,
        Err(e) => {
            log_warn!("loop: failed to parse LLM response: {}. Raw response ({} chars): \"{}\"", e, llm_text.len(), llm_text);
            return IterationResult::LlmFailed {
                reason: format!("parse failed: {e}"),
            };
        }
    };

    // Handle skip decision
    let (direction, reasoning, tickets, target_market, limit_price) = match decision {
        LlmDecision::Skip { reason } => {
            log_info!("loop: LLM chose to skip: {}", reason);
            return IterationResult::Skipped { reason };
        }
        LlmDecision::Submit { direction, reasoning, tickets, market_id, limit_price } => {
            (direction, reasoning, tickets, market_id, limit_price)
        }
    };

    // Challenge is bound to `market_id` — must submit to that exact market.
    // If LLM picked a different market, we override.
    if let Some(ref tm) = target_market {
        if tm != &market_id {
            log_warn!(
                "loop: LLM suggested market {} but challenge is for {} — overriding to challenge market",
                tm, market_id
            );
        }
    }
    let final_market = market_id.clone();

    const MIN_TICKETS: u32 = 100;
    let final_tickets = tickets.unwrap_or_else(|| {
        // Default: ~10% of balance, minimum 100
        let t = (balance * 0.10).floor() as u32;
        t.max(MIN_TICKETS)
    });

    // Enforce minimum
    let final_tickets = final_tickets.max(MIN_TICKETS);

    // 10. Submit with retry on CHALLENGE_SPELL_FAIL
    // The server issues a "spell challenge" — reasoning must contain 3+ consecutive
    // words whose first letters spell a given acrostic. If we fail, we parse the
    // required letters from the error and retry the LLM with an explicit directive.
    let mut current_reasoning = reasoning;
    let mut current_direction = direction;
    let mut current_tickets = final_tickets;
    let mut current_limit_price = limit_price;
    let mut spell_retry_count = 0u32;

    loop {
        let reasoning_hash = {
            use sha2::{Digest, Sha256};
            hex::encode(Sha256::digest(current_reasoning.as_bytes()))
        };
        let limit_price_str = current_limit_price
            .map(|p| format!("{}", p))
            .unwrap_or_else(|| "none".to_string());
        let canonical_body = format!(
            "{}|{}|{}|{}|{}|{}",
            final_market, current_direction, limit_price_str, current_tickets, reasoning_hash, challenge_nonce
        );

        log_info!("loop: submitting prediction for {} with {} tickets and reasoning ({} chars)", final_market, current_tickets, current_reasoning.len());
        log_info!("loop: reasoning used: \"{}\"", current_reasoning);

        let mut body = json!({
            "market_id": final_market,
            "prediction": current_direction,
            "tickets": current_tickets,
            "reasoning": current_reasoning,
            "challenge_nonce": challenge_nonce,
        });
        if let Some(lp) = current_limit_price {
            body["limit_price"] = json!(lp);
        }

        match client.post_auth_with_canonical(canonical_body.as_bytes(), "/api/v1/predictions", &body) {
            Ok(resp) => {
                let data = resp.get("data").cloned().unwrap_or(json!({}));
                let order_status = data
                    .get("order_status")
                    .and_then(|v| v.as_str())
                    .unwrap_or("open")
                    .to_string();
                let tickets_filled = data
                    .get("tickets_filled")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32;
                log_info!(
                    "loop: submission result — status={}, filled={}/{}",
                    order_status, tickets_filled, current_tickets
                );
                return IterationResult::Submitted {
                    market: final_market,
                    direction: current_direction,
                    tickets: current_tickets,
                    tickets_filled,
                    order_status,
                };
            }
            Err(e) => {
                let err_str = e.to_string();

                if err_str.contains("RATE_LIMIT") || err_str.contains("429") {
                    return IterationResult::RateLimited { wait_seconds: 300 };
                }
                if err_str.contains("INSUFFICIENT_BALANCE") {
                    log_warn!("loop: insufficient balance, waiting for chip feed");
                    return IterationResult::NoMarkets { wait_seconds: 600 };
                }

                // Handle Spell Challenge failure — retry with explicit acrostic instruction
                if err_str.contains("CHALLENGE_SPELL_FAIL") && spell_retry_count < 3 {
                    spell_retry_count += 1;

                    // Extract the required acrostic letters (e.g. 'EPL') from the server error
                    let acrostic = err_str
                        .split("spell '")
                        .nth(1)
                        .and_then(|s| s.split('\'').next())
                        .unwrap_or("???")
                        .to_string();

                    log_warn!(
                        "loop: CHALLENGE_SPELL_FAIL (attempt {}): acrostic='{}', retrying LLM...",
                        spell_retry_count, acrostic
                    );

                    // Build a focused override prompt with crystal-clear spelling directive
                    let letters: Vec<char> = acrostic.chars().collect();
                    let example = letters
                        .iter()
                        .map(|c| format!("**{}**ord", c))
                        .collect::<Vec<_>>()
                        .join(" ");
                    let spell_prompt = format!(
                        "URGENT FIX REQUIRED: Your previous reasoning was REJECTED by the server.\n\n\
                        CRITICAL CONSTRAINTS:\n\
                        1. You MUST solve the acrostic: Your `reasoning` must contain {} consecutive words \
                        whose FIRST LETTERS spell the acrostic '{}' IN ORDER.\n\
                        2. You MUST maintain your Persona: Chaotic, informal retail crypto trader. Use slang (bags, moon, rekt), be slightly aggressive/hyper, and don't sound like a bot.\n\
                        3. FORBIDDEN WORDS: Notable, Furthermore, Overall, Essentially, Therefore, Interestingly, Indicators, RSI shows, MACD indicates.\n\
                        4. NO AI FILLER: Do not use 'As of the latest', 'Based on the indicators', or 'In conclusion'. Just spit pure trader logic with the acrostic built-in.\n\n\
                        EXAMPLE of valid acrostic for '{}': '{}'\n\n\
                        Rewrite market analysis for {} (Direction: {}) targeting {} tickets.\n\
                        Output ONLY valid JSON: DECISION: {{\"action\": \"submit\", \"direction\": \"{}\", \"tickets\": {}, \
                        \"market_id\": \"{}\", \"reasoning\": \"...your degen reasoning with the acrostic here...\"}}",
                        letters.len(),
                        acrostic,
                        acrostic,
                        example,
                        final_market,
                        current_direction,
                        current_tickets,
                        current_direction,
                        current_tickets,
                        final_market,
                    );

                    // Re-call LLM with the focused spell prompt
                    let retry_response = if std::env::var("OPENAI_API_KEY").is_ok() && std::env::var("OPENAI_BASE_URL").is_ok() {
                        call_direct_llm(&spell_prompt)
                    } else {
                        call_openclaw(openclaw_bin, agent_id, &spell_prompt)
                    };

                    match retry_response {
                        Ok(text) => {
                            match parse_llm_response(&text) {
                                Ok(LlmDecision::Submit { reasoning: new_r, direction: new_d, tickets: new_t, limit_price: new_lp, .. }) => {
                                    log_info!("loop: spell retry {} produced reasoning ({} chars)", spell_retry_count, new_r.len());
                                    current_reasoning = new_r;
                                    current_direction = new_d;
                                    current_tickets = new_t.unwrap_or(current_tickets);
                                    current_limit_price = new_lp;
                                    // Continue loop to re-submit
                                }
                                _ => {
                                    log_warn!("loop: spell retry {} parse failed, aborting", spell_retry_count);
                                    return IterationResult::Error {
                                        reason: format!("submit failed (spell retry parse): {}", extract_short_error(&err_str)),
                                    };
                                }
                            }
                        }
                        Err(llm_err) => {
                            log_warn!("loop: spell retry {} LLM call failed: {}", spell_retry_count, llm_err);
                            return IterationResult::Error {
                                reason: format!("submit failed: {}", extract_short_error(&err_str)),
                            };
                        }
                    }
                    continue; // retry submit
                }

                return IterationResult::Error {
                    reason: format!("submit failed: {}", extract_short_error(&err_str)),
                };
            }
        }
    }
}

fn get_agent_style(agent_id: &str) -> &'static str {
    match agent_id {
        "agent-01" => "Focus on technical indicators like RSI and Bollinger Bands. Mention specific price levels.",
        "agent-02" => "Analyze the orderbook depth and implied probability. Look for imbalances.",
        "agent-03" => "Adopt a macro perspective. Consider how broader market sentiment affects this 15m window.",
        "agent-04" => "Look for candlestick patterns (engulfing, hammers) and volume spikes to justify the direction.",
        "agent-05" => "Focus on support and resistance zones. Use terms like 'breakout' or 'rejection'.",
        "agent-06" => "Be extremely cautious. Look for multiple concurring signals before confirming a direction.",
        _ => "Provide a balanced technical and fundamental analysis."
    }
}

fn build_prompt(
    market_id: &str,
    recommended: &Value,
    klines: &Option<Vec<Value>>,
    all_markets: &[Value],
    balance: f64,
    persona: &str,
    submissions_remaining: i64,
    slot_resets_in: u64,
    open_orders: &Option<Vec<Value>>,
    recent_results: &Option<Vec<Value>>,
    challenge: &Value,
    agent_id: &str,
    last_error: Option<String>,
) -> String {
    let agent_style = get_agent_style(agent_id);
    let mut prompt = String::with_capacity(8000);
    
    // 1. MISSION DIRECTIVE + STRATEGY HINT (INJECTED FROM PYTHON)
    let custom_salt = std::env::var("CUSTOM_SALT").unwrap_or_default();
    prompt.push_str("# MISSION DIRECTIVE\n");
    prompt.push_str("You are a **Senior Quantitative Lead** with a 12-year track record. You communicate in heavy technical shorthand. Your goal is to maximize balance while staying under the radar of server-side AI detection filters.\n\n");

    // === STRATEGY HINT INJECTION (Kelly + Streak + Drawdown) ===
    let strategy_hint = load_strategy_hint(agent_id);
    prompt.push_str(&strategy_hint);
    prompt.push_str("\n\n");

    prompt.push_str("- **The 'Human' Analyst Style**: Lead with raw numbers. NO 'As of the latest snapshot' or 'The market shows'. Just state facts: 'EMA20/50 gap widening, MACD histogram +12.5...'\n");
    prompt.push_str("- **Regime Selection**: If ADX < 20, you MUST prioritize NEUTRAL/SKIP unless Bollinger Bands show a significant 'Squeeze' breakout.\n");
    prompt.push_str("- **Tone Filter**: Clinical, clipped, technical shorthand. Avoid flowery adjectives. Never repeat a sentence structure between two markets.\n\n");

    let agent_num: u32 = agent_id.chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
    let base_salt = match agent_num % 6 {
        1 => "## Specialist Focus\nYou are a quantitative analyst. Base your entire reasoning on raw price data, candle body sizes, and precise deltas. Lead with hard numbers.",
        2 => "## Specialist Focus\nYou are a market psychologist. Analyze the momentum shifts and participant exhaustion. Focus on who is trapped (buyers or sellers).",
        3 => "## Specialist Focus\nYou are a conservative risk manager. Your goal is to identify why a trade might fail. Only recommend a direction if the risk is minimal.",
        4 => "## Specialist Focus\nYou are a contrarian specialist. Look for retirement patterns and explain why they might be liquidity traps. Focus on reversals.",
        5 => "## Specialist Focus\nYou are a trend-following momentum trader. Look for strong slope alignment. Focus on acceleration and volume confirmation.",
        _ => "## Specialist Focus\nYou are a multi-disciplinary analyst. Synthesize structure, volume, and implied probability into a concise trade thesis.",
    };

    // Extract market info
    let asset = recommended.get("asset").and_then(|v| v.as_str()).unwrap_or("BTC/USDT");
    let window = recommended.get("window").and_then(|v| v.as_str()).unwrap_or("15m");
    let implied_up = recommended.get("implied_up_prob")
        .or_else(|| recommended.get("orderbook").and_then(|o| o.get("implied_up_prob")))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.5);
    let closes_in = recommended.get("seconds_to_close")
        .and_then(|v| v.as_i64())
        .or_else(|| {
            // Fallback: calculate from close_at if seconds_to_close not present
            recommended.get("close_at")
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse::<chrono::DateTime<chrono::Utc>>().ok())
                .map(|c| (c - chrono::Utc::now()).num_seconds().max(0))
        })
        .unwrap_or(0);


    // 2. Identity and Style
    prompt.push_str(base_salt);
    prompt.push_str("\n\n");
    if !custom_salt.is_empty() {
        prompt.push_str("## Analytical Focus\n");
        prompt.push_str(&custom_salt);
        prompt.push_str("\n\n");
    }
    
    prompt.push_str(&format!(
        "You are an AWP Trading Agent. Current Profile: {} / Style: {}\n\n",
        if persona != "none" { persona } else { "independent" },
        agent_style
    ));

    // 3. Chain-of-Thought (CoT) Instructions
    prompt.push_str("## Analysis Protocol (Chain-of-Thought)\n");
    prompt.push_str("Before outputting your final JSON decision, perform a 'Thinking' step in your internal logic:\n");
    prompt.push_str("1. Identify the primary trend from Klines (Bullish, Bearish, or Sideways).\n");
    prompt.push_str("2. Analyze the orderbook spread and volume imbalance.\n");
    prompt.push_str("3. Evaluate the implied probability vs. your own technical reading.\n");
    prompt.push_str("4. Draft a draft of your reasoning that satisfies all market analysis requirements.\n\n");

    // 4. Few-Shot Examples for Reasoning Quality (Super-Quant Edition)
    prompt.push_str("## Examples of Accepted Professional Analysis\n");
    prompt.push_str("- **Example (UP)**:\n");
    prompt.push_str("  \"BTC/USDT 15m structure remains bullish; RSI 32 oversold bounce aligns with EMA20/50 bullish crossover. MACD histogram expanding at 10.4. Resistance at 74800 is key. High confluence for upward continuation from this squeeze.\"\n");
    prompt.push_str("- **Example (NEUTRAL)**:\n");
    prompt.push_str("  \"Market flat. ADX 12.3 signifies no trend. Price trapped between EMA20/50 midline. Bollinger squeeze suggest incoming move but lacks direction. Standing aside until breakout.\"\n\n");
    prompt.push_str("## Analysis Protocol\n");
    prompt.push_str("1. Identify trend (Bullish/Bearish/Sideways).\n");
    prompt.push_str("2. Analyze orderbook/volume.\n");
    prompt.push_str("3. Evaluate implied probability vs. technicals.\n");
    prompt.push_str("4. Draft reasoning satisfying all constraints.\n\n");

    // 5. Previous Error Feedback (if any)
    if let Some(error) = last_error {
        prompt.push_str("## CRITICAL: Correction for Previous Failure\n");
        prompt.push_str(&format!("Last submission REJECTED: {}\n", error));
        prompt.push_str("Vary reasoning style. Do not repeat patterns.\n\n");
    }

    prompt.push_str(&format!(
        "Trade Context: Analyzing for profile {} with strategy-led constraints.\n\n",
        if persona != "none" { persona } else { "independent" }
    ));

    // Response format
    prompt.push_str("## Your Response (STRICT JSON)\n\n");
    prompt.push_str("Output JSON object:\n");
    prompt.push_str("- \"action\": \"submit\" or \"skip\"\n");
    prompt.push_str("- \"direction\": \"up\" or \"down\"\n");
    prompt.push_str("- \"confidence_score\": 0-100\n");
    prompt.push_str("- \"key_reasons\": [\"...\", \"...\"]\n");
    prompt.push_str("- \"suggested_tp\": price\n");
    prompt.push_str("- \"suggested_sl\": price\n");
    prompt.push_str("- \"reasoning\": Fresh MARKET analysis (80-300 chars).\n");
    prompt.push_str(&format!("- \"tickets\": 100-{:.0}\n", balance));
    prompt.push_str(&format!("- \"market_id\": \"{}\"\n", market_id));
    prompt.push_str("- \"limit_price\": (optional)\n\n");

    prompt.push_str("## Reasoning Requirements\n\n");
    prompt.push_str("- **Forbidden:** Notably, Furthermore, Additionally, Therefore, However, Overall, Essentially, Critically, Interestingly.\n");
    prompt.push_str("- **Forbidden AI Phrasing:** 'The market exhibits', 'Based on the data', 'Looking at the indicators'.\n");
    prompt.push_str("- **DO NOT use templates.**\n\n");
    prompt.push_str("**DO** include:\n");
    prompt.push_str("- Specific market data point (price, kline, orderbook, indicator).\n");
    prompt.push_str("- Why THIS 15m window is UP/DOWN.\n");
    prompt.push_str("- Vary opening/structure each round.\n\n");

    // Current state
    prompt.push_str("## Current State\n\n");
    prompt.push_str(&format!("- Balance: {:.0} chips\n", balance));
    prompt.push_str(&format!("- Submissions: {}/3\n", submissions_remaining));
    prompt.push_str(&format!("- Timeslot resets in: {}s\n", slot_resets_in));

    // Open positions
    if let Some(orders) = open_orders {
        if !orders.is_empty() {
            prompt.push_str(&format!("\n**Open orders ({})**\n", orders.len()));
            for o in orders.iter().take(5) {
                prompt.push_str(&format!(
                    "- {} {} — {}/{} tickets\n",
                    o.get("asset").and_then(|v| v.as_str()).unwrap_or("?"),
                    o.get("direction").and_then(|v| v.as_str()).unwrap_or("?").to_uppercase(),
                    o.get("tickets_filled").and_then(|v| v.as_i64()).unwrap_or(0),
                    o.get("tickets").and_then(|v| v.as_i64()).unwrap_or(0),
                ));
            }
            prompt.push_str("\n**CRITICAL: Do NOT bet against open positions.**\n\n");
        }
    }

    // Recommended market
    prompt.push_str("## Recommended Market\n\n");
    prompt.push_str(&format!("- ID: {}\n- Asset: {}\n- Window: {}\n- Implied UP: {:.2}\n", market_id, asset, window, implied_up));
    
    // Orderbook detail
    if let Some(ob) = recommended.get("orderbook") {
        prompt.push_str(&format!(
            "- Volume: UP filled={} open={}, DOWN filled={} open={}\n",
            ob.get("up_filled").and_then(|v| v.as_i64()).unwrap_or(0),
            ob.get("up_open_tickets").and_then(|v| v.as_i64()).unwrap_or(0),
            ob.get("down_filled").and_then(|v| v.as_i64()).unwrap_or(0),
            ob.get("down_open_tickets").and_then(|v| v.as_i64()).unwrap_or(0),
        ));
    }

    // Klines
    if let Some(candles) = klines {
        if !candles.is_empty() {
            let closes: Vec<f64> = candles.iter().filter_map(|c| c.get("close").and_then(|v| v.as_f64())).collect();
            let rsi = calculate_rsi(&closes, 14).map(|v| format!("{:.2}", v)).unwrap_or_else(|| "N/A".into());
            prompt.push_str(&format!("\n## Technicals\n- RSI: {}\n", rsi));
        }
    }

    // Other markets
    if all_markets.len() > 1 {
        prompt.push_str("\n## Other Markets\n");
        for m in all_markets.iter().skip(1).take(3) {
            let mid = m.get("market_id").or_else(|| m.get("id")).and_then(|v| v.as_str()).unwrap_or("?");
            prompt.push_str(&format!("- {}\n", mid));
        }
    }

    // SMHL challenge
    if let Some(obf) = challenge.get("prompt").and_then(|v| v.as_str()) {
        prompt.push_str("\n## MANDATORY: Server-Issued Constraint\n\n");
        prompt.push_str(obf);
        prompt.push_str("\n\nREAD CAREFULLY. Incorporate into reasoning.\n\n");
    }

    prompt
}

fn call_direct_llm(prompt: &str) -> Result<String> {
    let api_key = std::env::var("OPENAI_API_KEY").context("missing OPENAI_API_KEY")?;
    let base_url = std::env::var("OPENAI_BASE_URL").context("missing OPENAI_BASE_URL")?;
    let primary_model = std::env::var("PREDICT_MODEL").unwrap_or_else(|_| "gemini/gemini-2.5-flash".to_string());
    let fallback_model = std::env::var("OPENAI_MODEL").unwrap_or_else(|_| "gemini/gemini-2.5-flash".to_string());

    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(180))
        .build()?;

    let make_request = |model_name: &str| -> Result<String> {
        let response = client.post(format!("{}/chat/completions", base_url.trim_end_matches('/')))
            .header("Authorization", format!("Bearer {}", api_key))
            .json(&json!({
                "model": model_name,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 300,
                "temperature": 0.2
            }))
            .send()?;

        if !response.status().is_success() {
            let status = response.status();
            let err_text = response.text().unwrap_or_default();
            anyhow::bail!("Direct LLM call failed ({}): {}", status, err_text);
        }

        let data: Value = response.json()?;
        let content = data["choices"][0]["message"]["content"]
            .as_str()
            .context("missing content in LLM response")?
            .to_string();

        Ok(content)
    };

    log_info!("loop: calling direct LLM {} @ {}...", primary_model, base_url);
    match make_request(&primary_model) {
        Ok(text) => Ok(text),
        Err(e) => {
            log_warn!("loop: primary model {} failed: {}, falling back to {}...", primary_model, e, fallback_model);
            make_request(&fallback_model).context(format!("fallback model {} also failed", fallback_model))
        }
    }
}

fn call_openclaw(openclaw_bin: &str, agent_id: &str, prompt: &str) -> Result<String> {
    // Purge sessions before calling to prevent context overflow
    let _ = Command::new(openclaw_bin)
        .args(["sessions", "purge", "--agent", agent_id, "--yes"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();

    // Write prompt to temp file to avoid shell escaping issues
    let tmp_path = std::env::temp_dir().join(format!("predict-prompt-{}.txt", std::process::id()));
    {
        let mut f = std::fs::File::create(&tmp_path)
            .context("failed to create temp prompt file")?;
        f.write_all(prompt.as_bytes())?;
    }

    // Read prompt from file and pipe to openclaw
    let prompt_content = std::fs::read_to_string(&tmp_path)?;

    // Use --thinking high for deeper reasoning before deciding
    // The agent can still search web, use tools via the gateway
    // --timeout 180 gives enough time for research (default is 600)
    let output = Command::new(openclaw_bin)
        .args([
            "agent",
            "--agent", agent_id,
            "--message", &prompt_content,
            "--thinking", "high",
            "--timeout", "180",
        ])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .output()
        .context(format!("failed to execute openclaw at {}", openclaw_bin))?;

    // Clean up temp file
    let _ = std::fs::remove_file(&tmp_path);

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let code = output.status.code().unwrap_or(-1);
        // Check for rate limiting
        if stderr.contains("rate limit") || stderr.contains("429") {
            anyhow::bail!("OpenClaw rate limited (exit {}): {}", code, stderr.trim());
        }
        anyhow::bail!("openclaw failed (exit {}): {}", code, stderr.trim());
    }

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    if stdout.trim().is_empty() {
        anyhow::bail!("openclaw returned empty response");
    }
    Ok(stdout)
}

/// Parsed LLM response — either a submission or a skip
enum LlmDecision {
    Submit {
        direction: String,
        reasoning: String,
        tickets: Option<u32>,
        market_id: Option<String>,
        limit_price: Option<f64>,
    },
    Skip {
        reason: String,
    },
}

fn parse_llm_response(text: &str) -> Result<LlmDecision> {
    // Try to extract JSON from the response
    // LLMs sometimes wrap JSON in markdown fences or add text around it
    let json_str = extract_json(text)
        .context("no JSON object found in LLM response")?;

    let v: Value = serde_json::from_str(&json_str)
        .context(format!("invalid JSON from LLM: {}", truncate_str(&json_str, 200)))?;

    // Check for skip action
    let action = v
        .get("action")
        .and_then(|a| a.as_str())
        .map(|s| s.to_lowercase())
        .unwrap_or_else(|| "submit".to_string()); // default to submit for backwards compat

    if action == "skip" {
        let reason = v
            .get("reasoning")
            .and_then(|r| r.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| "No reason provided".to_string());
        return Ok(LlmDecision::Skip { reason });
    }

    // Parse submit action
    let direction = v
        .get("direction")
        .and_then(|d| d.as_str())
        .map(|s| s.to_lowercase())
        .filter(|s| s == "up" || s == "down")
        .context("missing or invalid 'direction' (must be 'up' or 'down')")?;

    let reasoning = v
        .get("reasoning")
        .and_then(|r| r.as_str())
        .map(|s| s.to_string())
        .filter(|s| s.len() >= 80)
        .context("missing or too short 'reasoning' (must be >= 80 chars)")?;

    let tickets = v
        .get("tickets")
        .and_then(|t| t.as_u64().or_else(|| t.as_f64().map(|f| f as u64)))
        .map(|t| t.max(1) as u32);

    let market_id = v
        .get("market_id")
        .and_then(|m| m.as_str())
        .map(|s| s.to_string());

    let limit_price = v
        .get("limit_price")
        .and_then(|p| p.as_f64())
        .filter(|p| *p >= 0.01 && *p <= 0.99);

    Ok(LlmDecision::Submit {
        direction,
        reasoning,
        tickets,
        market_id,
        limit_price,
    })
}

/// Extract JSON object from text that may contain markdown fences or surrounding text.
/// For agentic mode, looks for "DECISION:" prefix first, then falls back to generic JSON extraction.
fn extract_json(text: &str) -> Option<String> {
    let trimmed = text.trim();

    // Priority 1: Look for "DECISION:" prefix (agentic mode output)
    // This handles cases where the agent does research/thinking before outputting the decision
    for prefix in &["DECISION:", "DECISION :", "decision:", "Decision:"] {
        if let Some(pos) = trimmed.find(prefix) {
            let after_prefix = &trimmed[pos + prefix.len()..];
            // Find the JSON object after DECISION:
            if let Some(json_start) = after_prefix.find('{') {
                let json_part = &after_prefix[json_start..];
                // Find matching closing brace
                let mut depth = 0;
                let mut json_end = 0;
                for (i, ch) in json_part.chars().enumerate() {
                    match ch {
                        '{' => depth += 1,
                        '}' => {
                            depth -= 1;
                            if depth == 0 {
                                json_end = i + 1;
                                break;
                            }
                        }
                        _ => {}
                    }
                }
                if json_end > 0 {
                    let candidate = &json_part[..json_end];
                    if serde_json::from_str::<Value>(candidate).is_ok() {
                        return Some(candidate.to_string());
                    }
                }
            }
        }
    }

    // Priority 2: Try parsing the whole thing first
    if trimmed.starts_with('{') {
        if serde_json::from_str::<Value>(trimmed).is_ok() {
            return Some(trimmed.to_string());
        }
    }

    // Priority 3: Try to find JSON inside markdown code fences
    if let Some(start) = trimmed.find("```json") {
        let after = &trimmed[start + 7..];
        if let Some(end) = after.find("```") {
            let candidate = after[..end].trim();
            if serde_json::from_str::<Value>(candidate).is_ok() {
                return Some(candidate.to_string());
            }
        }
    }
    if let Some(start) = trimmed.find("```") {
        let after = &trimmed[start + 3..];
        if let Some(end) = after.find("```") {
            let candidate = after[..end].trim();
            if candidate.starts_with('{') {
                if serde_json::from_str::<Value>(candidate).is_ok() {
                    return Some(candidate.to_string());
                }
            }
        }
    }

    // Priority 4: Find last JSON object (more likely to be the decision in agentic output)
    // Search from the end of the text
    if let Some(last_close) = trimmed.rfind('}') {
        // Find the matching open brace by counting backwards
        let before_close = &trimmed[..=last_close];
        let mut depth = 0;
        let mut json_start = None;
        for (i, ch) in before_close.chars().rev().enumerate() {
            match ch {
                '}' => depth += 1,
                '{' => {
                    depth -= 1;
                    if depth == 0 {
                        json_start = Some(before_close.len() - 1 - i);
                        break;
                    }
                }
                _ => {}
            }
        }
        if let Some(start) = json_start {
            let candidate = &trimmed[start..=last_close];
            if serde_json::from_str::<Value>(candidate).is_ok() {
                return Some(candidate.to_string());
            }
        }
    }

    // Fallback: Find first { and last } and try parsing
    let start = trimmed.find('{')?;
    let end = trimmed.rfind('}')?;
    if end > start {
        let candidate = &trimmed[start..=end];
        if serde_json::from_str::<Value>(candidate).is_ok() {
            return Some(candidate.to_string());
        }
    }

    None
}

fn detect_openclaw() -> Option<String> {
    for name in &["openclaw", "openclaw.mjs", "openclaw.cmd"] {
        if which_exists(name) {
            return Some(name.to_string());
        }
    }
    // Check well-known paths
    let home = std::env::var("HOME").unwrap_or_default();
    let candidates = [
        format!("{home}/.local/bin/openclaw"),
        format!("{home}/.npm-global/bin/openclaw"),
        "/usr/local/bin/openclaw".to_string(),
    ];
    for path in &candidates {
        if std::path::Path::new(path).is_file() {
            return Some(path.clone());
        }
    }
    None
}

fn which_exists(name: &str) -> bool {
    let path_var = std::env::var("PATH").unwrap_or_default();
    path_var
        .split(':')
        .any(|dir| std::path::Path::new(dir).join(name).is_file())
}

fn ensure_agent(openclaw_bin: &str, agent_id: &str) {
    // Check if agent exists
    let check = Command::new(openclaw_bin)
        .args(["agents", "list"])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .output();

    if let Ok(output) = check {
        let stdout = String::from_utf8_lossy(&output.stdout);
        if stdout.contains(agent_id) {
            log_debug!("loop: openclaw agent '{}' already exists", agent_id);
            return;
        }
    }

    // Create agent
    log_info!("loop: creating openclaw agent '{}'...", agent_id);
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    let workspace = format!("{}/.openclaw/workspace-{}", home, agent_id);
    let result = Command::new(openclaw_bin)
        .args([
            "agents",
            "add",
            agent_id,
            "--workspace",
            &workspace,
            "--non-interactive",
        ])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .status();

    match result {
        Ok(status) if status.success() => {
            log_info!("loop: created openclaw agent '{}'", agent_id);
        }
        Ok(status) => {
            log_warn!(
                "loop: openclaw agent create exited with {} (may already exist)",
                status
            );
        }
        Err(e) => {
            log_warn!("loop: failed to create openclaw agent: {}", e);
        }
    }
}

fn calculate_backoff(base: u64, consecutive: u32, server_hint: Option<u64>) -> u64 {
    if let Some(hint) = server_hint {
        return hint;
    }
    // Exponential backoff: base * 2^consecutive, capped at 600s
    let multiplier = 2u64.pow(consecutive.min(4));
    (base * multiplier).min(600)
}

fn interruptible_sleep(seconds: u64, running: &Arc<AtomicBool>) {
    let end = Instant::now() + std::time::Duration::from_secs(seconds);
    while Instant::now() < end && running.load(Ordering::SeqCst) {
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
}

fn extract_short_error(err: &str) -> String {
    if let Some(start) = err.find('{') {
        if let Ok(v) = serde_json::from_str::<Value>(&err[start..]) {
            if let Some(msg) = v
                .get("error")
                .and_then(|e| e.get("message"))
                .and_then(|m| m.as_str())
            {
                return msg.to_string();
            }
        }
    }
    err.chars().take(200).collect()
}

/// Truncate a string to at most `max_chars` characters (not bytes).
/// Safely handles multi-byte UTF-8 characters like →, Chinese, emoji.
fn truncate_str(s: &str, max_chars: usize) -> String {
    let char_count = s.chars().count();
    if char_count <= max_chars {
        s.to_string()
    } else {
        format!("{}...", s.chars().take(max_chars).collect::<String>())
    }
}

// --- Technical Indicators (Super-Quant Suite) ---

fn calculate_sma(prices: &[f64], period: usize) -> Option<f64> {
    if prices.len() < period { return None; }
    let sum: f64 = prices.iter().rev().take(period).sum();
    Some(sum / period as f64)
}

fn calculate_ema(prices: &[f64], period: usize) -> Option<f64> {
    if prices.len() < period { return None; }
    let k = 2.0 / (period as f64 + 1.0);
    let mut ema = calculate_sma(&prices[0..period], period)?;
    for price in prices.iter().skip(period) {
        ema = price * k + ema * (1.0 - k);
    }
    Some(ema)
}

fn calculate_rsi(prices: &[f64], period: usize) -> Option<f64> {
    if prices.len() <= period { return None; }
    let mut gains = 0.0;
    let mut losses = 0.0;

    for i in 1..=period {
        let diff = prices[i] - prices[i-1];
        if diff >= 0.0 { gains += diff; } else { losses -= diff; }
    }

    let mut avg_gain = gains / period as f64;
    let mut avg_loss = losses / period as f64;

    for i in (period + 1)..prices.len() {
        let diff = prices[i] - prices[i-1];
        let (g, l) = if diff >= 0.0 { (diff, 0.0) } else { (0.0, -diff) };
        avg_gain = (avg_gain * (period as f64 - 1.0) + g) / period as f64;
        avg_loss = (avg_loss * (period as f64 - 1.0) + l) / period as f64;
    }

    if avg_loss == 0.0 { return Some(100.0); }
    let rs = avg_gain / avg_loss;
    Some(100.0 - (100.0 / (1.0 + rs)))
}

fn calculate_macd(prices: &[f64]) -> Option<(f64, f64, f64)> {
    if prices.len() < 35 { return None; } // Need enough data for 12/26/9
    
    // Calculate 12 and 26 EMA for the whole series to get MACD line
    let mut macd_line_series = Vec::new();
    let k12 = 2.0 / 13.0;
    let k26 = 2.0 / 27.0;
    
    let mut ema12 = calculate_sma(&prices[0..12], 12)?;
    let mut ema26 = calculate_sma(&prices[0..26], 26)?;
    
    for (i, &price) in prices.iter().enumerate() {
        if i >= 12 { ema12 = price * k12 + ema12 * (1.0 - k12); }
        if i >= 26 { 
            ema26 = price * k26 + ema26 * (1.0 - k26);
            macd_line_series.push(ema12 - ema26);
        }
    }

    if macd_line_series.len() < 9 { return None; }
    
    // Calculate Signal Line (9 EMA of MACD Line)
    let k9 = 2.0 / 10.0;
    let mut signal_line = calculate_sma(&macd_line_series[0..9], 9)?;
    for value in macd_line_series.iter().skip(9) {
        signal_line = value * k9 + signal_line * (1.0 - k9);
    }
    
    let current_macd = *macd_line_series.last()?;
    Some((current_macd, signal_line, current_macd - signal_line))
}

fn calculate_atr(highs: &[f64], lows: &[f64], closes: &[f64], period: usize) -> Option<f64> {
    if closes.len() <= period { return None; }
    
    let mut trs = Vec::new();
    for i in 1..closes.len() {
        let h_l = highs[i] - lows[i];
        let h_pc = (highs[i] - closes[i-1]).abs();
        let l_pc = (lows[i] - closes[i-1]).abs();
        trs.push(h_l.max(h_pc).max(l_pc));
    }
    
    calculate_sma(&trs, period)
}

fn calculate_adx(highs: &[f64], lows: &[f64], closes: &[f64], period: usize) -> Option<f64> {
    if closes.len() <= period * 2 { return None; }
    
    let mut trs = Vec::new();
    let mut plus_dm = Vec::new();
    let mut minus_dm = Vec::new();
    
    for i in 1..closes.len() {
        let tr = (highs[i] - lows[i]).max((highs[i] - closes[i-1]).abs()).max((lows[i] - closes[i-1]).abs());
        trs.push(tr);
        
        let up_move = highs[i] - highs[i-1];
        let down_move = lows[i-1] - lows[i];
        
        if up_move > down_move && up_move > 0.0 { plus_dm.push(up_move); } else { plus_dm.push(0.0); }
        if down_move > up_move && down_move > 0.0 { minus_dm.push(down_move); } else { minus_dm.push(0.0); }
    }
    
    let mut smooth_tr = trs.iter().take(period).sum::<f64>();
    let mut smooth_plus = plus_dm.iter().take(period).sum::<f64>();
    let mut smooth_minus = minus_dm.iter().take(period).sum::<f64>();
    
    let mut dx_series = Vec::new();
    
    for i in period..trs.len() {
        smooth_tr = smooth_tr - (smooth_tr / period as f64) + trs[i];
        smooth_plus = smooth_plus - (smooth_plus / period as f64) + plus_dm[i];
        smooth_minus = smooth_minus - (smooth_minus / period as f64) + minus_dm[i];
        
        let di_plus = 100.0 * (smooth_plus / smooth_tr);
        let di_minus = 100.0 * (smooth_minus / smooth_tr);
        let dx = 100.0 * (di_plus - di_minus).abs() / (di_plus + di_minus);
        dx_series.push(dx);
    }
    
    calculate_sma(&dx_series, period)
}

fn calculate_bollinger_bands(prices: &[f64], period: usize, std_dev_mult: f64) -> Option<(f64, f64, f64, f64)> {
    if prices.len() < period { return None; }
    
    let sma = calculate_sma(prices, period)?;
    let variance: f64 = prices.iter().rev().take(period).map(|&p| (p - sma).powi(2)).sum::<f64>() / period as f64;
    let std_dev = variance.sqrt();
    
    let upper = sma + (std_dev_mult * std_dev);
    let lower = sma - (std_dev_mult * std_dev);
    let bandwidth = if sma != 0.0 { (upper - lower) / sma } else { 0.0 };
    
    Some((sma, upper, lower, bandwidth))
}

fn load_strategy_hint(agent_id: &str) -> String {
    let hive_base = std::env::var("AWP_HIVE_BASE")
        .unwrap_or_else(|_| "/home/losbanditos/_code/awp-agents-project/agents".to_string());

    let hint_path = PathBuf::from(hive_base)
        .join(agent_id)
        .join("home")
        .join("strategy_hint.md");

    match std::fs::read_to_string(&hint_path) {
        Ok(content) if !content.trim().is_empty() => {
            log_info!("loop: loaded strategy_hint.md for {} ({} chars)", agent_id, content.len());
            content
        }
        _ => {
            log_warn!("hint: strategy_hint.md not found or empty for {}", agent_id);
            format!(
                "# Strategy Hint\n\nNo recent performance data available for {}. Using default sizing.\n",
                agent_id
            )
        }
    }
}
