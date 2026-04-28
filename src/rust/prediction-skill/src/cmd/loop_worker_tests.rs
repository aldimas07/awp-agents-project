#[cfg(test)]
mod debate_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_parse_llm_response_submit() {
        let json_str = r#"{"action":"submit","direction":"up","reasoning":"BTC showing strong momentum","tickets":1000,"market_id":"test-123","limit_price":0.55}"#;
        let result = parse_llm_response(json_str);
        assert!(result.is_ok());
        match result.unwrap() {
            LlmDecision::Submit { direction, reasoning, tickets, market_id, limit_price } => {
                assert_eq!(direction, "up");
                assert_eq!(reasoning, "BTC showing strong momentum");
                assert_eq!(tickets, 1000);
                assert_eq!(market_id, "test-123");
                assert_eq!(limit_price, 0.55);
            }
            _ => panic!("Expected Submit decision"),
        }
    }

    #[test]
    fn test_parse_llm_response_skip() {
        let json_str = r#"{"action":"skip","reasoning":"No good opportunities"}"#;
        let result = parse_llm_response(json_str);
        assert!(result.is_ok());
        match result.unwrap() {
            LlmDecision::Skip { reason } => {
                assert_eq!(reason, "No good opportunities");
            }
            _ => panic!("Expected Skip decision"),
        }
    }

    #[test]
    fn test_parse_llm_response_with_markdown() {
        let json_str = r#"Here's my decision:

```json
{"action":"submit","direction":"down","reasoning":"Bearish trend","tickets":500,"market_id":"test-456"}
```

That's my analysis."#;
        let result = parse_llm_response(json_str);
        assert!(result.is_ok());
        match result.unwrap() {
            LlmDecision::Submit { direction, .. } => {
                assert_eq!(direction, "down");
            }
            _ => panic!("Expected Submit decision"),
        }
    }

    #[test]
    fn test_parse_llm_response_invalid_json() {
        let json_str = r#"not valid json at all"#;
        let result = parse_llm_response(json_str);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_llm_response_missing_action() {
        let json_str = r#"{"direction":"up","reasoning":"test"}"#;
        let result = parse_llm_response(json_str);
        assert!(result.is_err());
    }

    #[test]
    fn test_truncate_str() {
        assert_eq!(truncate_str("hello", 10), "hello");
        assert_eq!(truncate_str("hello world", 5), "hello");
        assert_eq!(truncate_str("", 10), "");
    }

    #[test]
    fn test_extract_json_from_text() {
        let text = r#"Some text before
{"action":"submit","direction":"up"}
Some text after"#;
        let result = extract_json(text);
        assert!(result.is_ok());
        let json_str = result.unwrap();
        assert!(json_str.contains("submit"));
    }

    #[test]
    fn test_extract_json_from_markdown() {
        let text = r#"Here's the JSON:

```json
{"action":"skip","reasoning":"test"}
```

Done."#;
        let result = extract_json(text);
        assert!(result.is_ok());
        let json_str = result.unwrap();
        assert!(json_str.contains("skip"));
    }

    #[test]
    fn test_extract_json_no_json_found() {
        let text = r#"Just some text with no JSON here"#;
        let result = extract_json(text);
        assert!(result.is_err());
    }
}
