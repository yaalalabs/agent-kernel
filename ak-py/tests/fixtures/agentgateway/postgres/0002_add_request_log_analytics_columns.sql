-- Verbatim from agentgateway v1.7.0 (Apache-2.0): crates/agentgateway/src/telemetry/log_store/postgres_migrations/0002_add_request_log_analytics_columns.sql
ALTER TABLE request_logs
	ADD COLUMN IF NOT EXISTS cache_read_input_tokens BIGINT,
	ADD COLUMN IF NOT EXISTS cache_creation_input_tokens BIGINT,
	ADD COLUMN IF NOT EXISTS reasoning_tokens BIGINT,
	ADD COLUMN IF NOT EXISTS time_to_first_token_ms DOUBLE PRECISION,
	ADD COLUMN IF NOT EXISTS time_per_output_token_ms DOUBLE PRECISION;
