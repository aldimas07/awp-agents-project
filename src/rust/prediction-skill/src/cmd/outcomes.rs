use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

use crate::client::ApiClient;
use crate::output::{Internal, Output};
use crate::{log_error, log_info};

pub fn run(server_url: &str, agent_id: &str, limit: u32) -> Result<()> {
    log_info!(
        "outcomes: syncing last {} predictions for {}",
        limit,
        agent_id
    );
    let client = ApiClient::new(server_url.to_string())?;
    let resp = match client.get_auth(&format!("/api/v1/predictions/me?limit={}", limit)) {
        Ok(v) => v,
        Err(e) => {
            log_error!("outcomes: failed to fetch predictions: {}", e);
            Output::error_with_debug(
                format!("Failed to fetch predictions: {e}"),
                "OUTCOMES_FETCH_FAILED",
                "network",
                true,
                "Check coordinator connectivity and retry.",
                json!({"server_url": server_url, "limit": limit, "error_detail": format!("{e:#}")}),
                Internal {
                    next_action: "retry".into(),
                    next_command: Some(format!(
                        "predict-agent outcomes --agent-id {} --limit {}",
                        agent_id, limit
                    )),
                    ..Default::default()
                },
            )
            .print();
            return Ok(());
        }
    };

    let predictions = resp
        .get("data")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let rows: Vec<BTreeMap<String, String>> = predictions
        .iter()
        .map(|p| normalize_prediction(agent_id, p))
        .collect();

    let path = write_outcomes_csv(agent_id, &rows)?;
    let summary = summarize(&rows);

    Output::success(
        format!(
            "Synced {} predictions for {}. Resolved win rate: {:.1}% ({}/{}).",
            rows.len(),
            agent_id,
            summary.resolved_win_rate * 100.0,
            summary.resolved_wins,
            summary.resolved_count
        ),
        json!({
            "agent_id": agent_id,
            "path": path.to_string_lossy(),
            "rows": rows.len(),
            "resolved_count": summary.resolved_count,
            "resolved_wins": summary.resolved_wins,
            "resolved_win_rate": summary.resolved_win_rate,
            "filled_resolved_count": summary.filled_resolved_count,
            "filled_resolved_wins": summary.filled_resolved_wins,
            "filled_resolved_win_rate": summary.filled_resolved_win_rate
        }),
        Internal {
            next_action: "review_metrics".into(),
            next_command: Some("predict-agent history --limit 50".into()),
            ..Default::default()
        },
    )
    .print();

    Ok(())
}

struct Summary {
    resolved_count: usize,
    resolved_wins: usize,
    resolved_win_rate: f64,
    filled_resolved_count: usize,
    filled_resolved_wins: usize,
    filled_resolved_win_rate: f64,
}

fn summarize(rows: &[BTreeMap<String, String>]) -> Summary {
    let resolved: Vec<&BTreeMap<String, String>> = rows
        .iter()
        .filter(|r| !r.get("won").map(|v| v.is_empty()).unwrap_or(true))
        .collect();
    let resolved_wins = resolved
        .iter()
        .filter(|r| r.get("won").map(|v| v == "true").unwrap_or(false))
        .count();
    let filled_resolved: Vec<&BTreeMap<String, String>> = resolved
        .iter()
        .copied()
        .filter(|r| {
            r.get("tickets_filled")
                .and_then(|v| v.parse::<f64>().ok())
                .unwrap_or(0.0)
                > 0.0
        })
        .collect();
    let filled_resolved_wins = filled_resolved
        .iter()
        .filter(|r| r.get("won").map(|v| v == "true").unwrap_or(false))
        .count();
    Summary {
        resolved_count: resolved.len(),
        resolved_wins,
        resolved_win_rate: ratio(resolved_wins, resolved.len()),
        filled_resolved_count: filled_resolved.len(),
        filled_resolved_wins,
        filled_resolved_win_rate: ratio(filled_resolved_wins, filled_resolved.len()),
    }
}

fn ratio(n: usize, d: usize) -> f64 {
    if d == 0 {
        0.0
    } else {
        n as f64 / d as f64
    }
}

fn normalize_prediction(agent_id: &str, p: &Value) -> BTreeMap<String, String> {
    let mut row = BTreeMap::new();
    for key in headers() {
        row.insert(key.to_string(), String::new());
    }
    row.insert("agent_id".to_string(), agent_id.to_string());
    put(&mut row, "prediction_id", p, &["id", "prediction_id"]);
    put(&mut row, "market_id", p, &["market_id", "market"]);
    put(&mut row, "asset", p, &["asset"]);
    put(&mut row, "window", p, &["window"]);
    put(&mut row, "direction", p, &["direction", "prediction"]);
    put(&mut row, "outcome", p, &["outcome", "market_outcome"]);
    put(
        &mut row,
        "payout_chips",
        p,
        &["payout_chips", "payout", "payout_received"],
    );
    put(
        &mut row,
        "tickets_filled",
        p,
        &["tickets_filled", "filled_amount"],
    );
    put(&mut row, "tickets", p, &["tickets", "predicted_amount"]);
    put(
        &mut row,
        "entry_price",
        p,
        &["entry_price", "limit_price", "price"],
    );
    put(&mut row, "order_status", p, &["order_status", "status"]);
    put(&mut row, "created_at", p, &["created_at", "timestamp"]);
    put(&mut row, "resolved_at", p, &["resolved_at"]);

    let direction = row
        .get("direction")
        .cloned()
        .unwrap_or_default()
        .to_lowercase();
    let outcome = row
        .get("outcome")
        .cloned()
        .unwrap_or_default()
        .to_lowercase();
    let payout_present = row
        .get("payout_chips")
        .map(|v| !v.is_empty())
        .unwrap_or(false);
    let payout = row
        .get("payout_chips")
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(0.0);
    let filled = row
        .get("tickets_filled")
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(0.0);
    let won = if !direction.is_empty() && !outcome.is_empty() {
        Some(direction == outcome)
    } else if payout_present && filled > 0.0 {
        Some(payout > 0.0)
    } else {
        None
    };
    if let Some(w) = won {
        row.insert(
            "won".to_string(),
            if w { "true" } else { "false" }.to_string(),
        );
    }
    row
}

fn put(row: &mut BTreeMap<String, String>, out_key: &str, p: &Value, candidates: &[&str]) {
    for key in candidates {
        if let Some(value) = p.get(*key) {
            if !value.is_null() {
                row.insert(out_key.to_string(), value_to_string(value));
                return;
            }
        }
    }
}

fn value_to_string(v: &Value) -> String {
    v.as_str()
        .map(|s| s.to_string())
        .unwrap_or_else(|| v.to_string().trim_matches('"').to_string())
}

fn write_outcomes_csv(agent_id: &str, rows: &[BTreeMap<String, String>]) -> Result<PathBuf> {
    let root = project_root()?;
    let data_dir = root.join("data");
    fs::create_dir_all(&data_dir)?;
    let path = data_dir.join(format!("prediction_outcomes_{}.csv", agent_id));
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)?;
    writeln!(file, "{}", headers().join(","))?;
    for row in rows {
        let line = headers()
            .iter()
            .map(|h| csv_escape(row.get(*h).map(String::as_str).unwrap_or("")))
            .collect::<Vec<_>>()
            .join(",");
        writeln!(file, "{}", line)?;
    }
    Ok(path)
}

fn project_root() -> Result<PathBuf> {
    let exe = std::env::current_exe()?;
    let cwd = std::env::current_dir()?;
    for candidate in [cwd.as_path(), exe.parent().unwrap_or(cwd.as_path())] {
        if candidate.join("data").exists()
            || candidate.join("agents").exists()
            || candidate.join("config").exists()
        {
            return Ok(candidate.to_path_buf());
        }
    }
    std::env::var("PROJECT_ROOT")
        .map(PathBuf::from)
        .context("PROJECT_ROOT not set and project root could not be inferred")
}

fn csv_escape(s: &str) -> String {
    if s.contains(',') || s.contains('"') || s.contains('\n') || s.contains('\r') {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

fn headers() -> Vec<&'static str> {
    vec![
        "agent_id",
        "prediction_id",
        "market_id",
        "asset",
        "window",
        "direction",
        "outcome",
        "won",
        "payout_chips",
        "tickets_filled",
        "tickets",
        "entry_price",
        "order_status",
        "created_at",
        "resolved_at",
    ]
}
