-- ============================================================================
-- DATA QUALITY VALIDATION SYSTEM
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. DATA QUALITY RULES TABLE - Define all validation rules
-- ----------------------------------------------------------------------------
CREATE TABLE data_quality_rules (
    rule_id SERIAL PRIMARY KEY,
    rule_name VARCHAR(100) UNIQUE NOT NULL,
    table_name VARCHAR(50) NOT NULL,
    rule_type VARCHAR(50) NOT NULL, -- completeness, consistency, timeliness, accuracy
    sql_check TEXT NOT NULL,
    severity VARCHAR(20) DEFAULT 'warning', -- critical, warning, info
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 2. DATA QUALITY RESULTS TABLE - Store validation results over time
-- ----------------------------------------------------------------------------
CREATE TABLE data_quality_results (
    result_id BIGSERIAL PRIMARY KEY,
    rule_id INTEGER REFERENCES data_quality_rules(rule_id),
    check_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    records_checked BIGINT,
    records_failed BIGINT,
    failure_rate DECIMAL(5,2),
    status VARCHAR(20), -- pass, fail, warning
    details JSONB,
    execution_time_ms INTEGER
);

CREATE INDEX idx_dq_results_timestamp ON data_quality_results(check_timestamp DESC);
CREATE INDEX idx_dq_results_rule ON data_quality_results(rule_id, check_timestamp DESC);

-- ----------------------------------------------------------------------------
-- 3. PRE-POPULATED VALIDATION RULES
-- ----------------------------------------------------------------------------

-- TICKERS validation rules
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('tickers_no_null_symbols', 'tickers', 'completeness', 
 'SELECT COUNT(*) FROM tickers WHERE symbol IS NULL OR symbol = ''''', 
 'critical', 'Tickers must have valid symbols'),

('tickers_symbol_format', 'tickers', 'accuracy',
 'SELECT COUNT(*) FROM tickers WHERE symbol !~ ''^[A-Z]{1,5}$''',
 'warning', 'Ticker symbols should be 1-5 uppercase letters'),

('tickers_unique_symbols', 'tickers', 'consistency',
 'SELECT COUNT(*) - COUNT(DISTINCT symbol) FROM tickers',
 'critical', 'Ticker symbols must be unique'),

('tickers_orphaned_records', 'tickers', 'consistency',
 'SELECT COUNT(*) FROM tickers t WHERE NOT EXISTS (SELECT 1 FROM stock_prices sp WHERE sp.ticker_id = t.ticker_id)',
 'warning', 'Tickers should have at least one stock price record');

-- STOCK PRICES validation rules
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('prices_no_future_dates', 'stock_prices', 'accuracy',
 'SELECT COUNT(*) FROM stock_prices WHERE date > CURRENT_DATE',
 'critical', 'Stock prices should not have future dates'),

('prices_negative_values', 'stock_prices', 'accuracy',
 'SELECT COUNT(*) FROM stock_prices WHERE open < 0 OR high < 0 OR low < 0 OR close < 0',
 'critical', 'Stock prices cannot be negative'),

('prices_high_low_consistency', 'stock_prices', 'consistency',
 'SELECT COUNT(*) FROM stock_prices WHERE high < low',
 'critical', 'High price must be >= low price'),

('prices_ohlc_consistency', 'stock_prices', 'consistency',
 'SELECT COUNT(*) FROM stock_prices WHERE open > high OR open < low OR close > high OR close < low',
 'critical', 'OHLC prices must be within high-low range'),

('prices_zero_volume', 'stock_prices', 'accuracy',
 'SELECT COUNT(*) FROM stock_prices WHERE volume = 0 OR volume IS NULL',
 'warning', 'Stock prices with zero or null volume may indicate data issues'),

('prices_duplicate_dates', 'stock_prices', 'consistency',
 'SELECT COUNT(*) FROM (SELECT ticker_id, date, COUNT(*) as cnt FROM stock_prices GROUP BY ticker_id, date HAVING COUNT(*) > 1) dupes',
 'critical', 'Each ticker should have only one price record per date'),

('prices_large_gaps', 'stock_prices', 'timeliness',
 'SELECT COUNT(*) FROM (
    SELECT ticker_id, date, 
           LAG(date) OVER (PARTITION BY ticker_id ORDER BY date) as prev_date,
           date - LAG(date) OVER (PARTITION BY ticker_id ORDER BY date) as gap_days
    FROM stock_prices
 ) gaps WHERE gap_days > 10',
 'warning', 'Large gaps (>10 days) in price data may indicate missing records'),

('prices_extreme_movements', 'stock_prices', 'accuracy',
 'SELECT COUNT(*) FROM (
    SELECT ticker_id, date, close,
           LAG(close) OVER (PARTITION BY ticker_id ORDER BY date) as prev_close,
           ABS((close - LAG(close) OVER (PARTITION BY ticker_id ORDER BY date)) / 
               NULLIF(LAG(close) OVER (PARTITION BY ticker_id ORDER BY date), 0)) as pct_change
    FROM stock_prices
 ) changes WHERE pct_change > 0.50',
 'warning', 'Price changes >50% in one day may indicate data errors or stock splits');

-- REDDIT POSTS validation rules
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('reddit_no_null_post_ids', 'reddit_posts', 'completeness',
 'SELECT COUNT(*) FROM reddit_posts WHERE post_id IS NULL OR post_id = ''''',
 'critical', 'Reddit posts must have valid post IDs'),

('reddit_duplicate_post_ids', 'reddit_posts', 'consistency',
 'SELECT COUNT(*) - COUNT(DISTINCT post_id) FROM reddit_posts',
 'critical', 'Reddit post IDs must be unique'),

('reddit_future_timestamps', 'reddit_posts', 'accuracy',
 'SELECT COUNT(*) FROM reddit_posts WHERE created_utc > CURRENT_TIMESTAMP',
 'critical', 'Reddit posts cannot have future timestamps'),

('reddit_missing_content', 'reddit_posts', 'completeness',
 'SELECT COUNT(*) FROM reddit_posts WHERE (title IS NULL OR title = '''') AND (selftext IS NULL OR selftext = '''')',
 'warning', 'Reddit posts should have either title or selftext'),

('reddit_invalid_upvote_ratio', 'reddit_posts', 'accuracy',
 'SELECT COUNT(*) FROM reddit_posts WHERE upvote_ratio < 0 OR upvote_ratio > 1',
 'critical', 'Upvote ratio must be between 0 and 1'),

('reddit_orphaned_tickers', 'reddit_posts', 'consistency',
 'SELECT COUNT(*) FROM reddit_posts rp WHERE NOT EXISTS (SELECT 1 FROM reddit_post_tickers rpt WHERE rpt.reddit_post_id = rp.reddit_post_id)',
 'warning', 'Reddit posts should be linked to at least one ticker');

-- NEWS ARTICLES validation rules
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('news_no_null_urls', 'news_articles', 'completeness',
 'SELECT COUNT(*) FROM news_articles WHERE url IS NULL OR url = ''''',
 'critical', 'News articles must have valid URLs'),

('news_duplicate_urls', 'news_articles', 'consistency',
 'SELECT COUNT(*) - COUNT(DISTINCT url) FROM news_articles',
 'warning', 'Duplicate news article URLs may indicate data issues'),

('news_future_published', 'news_articles', 'accuracy',
 'SELECT COUNT(*) FROM news_articles WHERE published_at > CURRENT_TIMESTAMP',
 'critical', 'News articles cannot have future publication dates'),

('news_missing_titles', 'news_articles', 'completeness',
 'SELECT COUNT(*) FROM news_articles WHERE title IS NULL OR title = ''''',
 'critical', 'News articles must have titles'),

('news_orphaned_tickers', 'news_articles', 'consistency',
 'SELECT COUNT(*) FROM news_articles na WHERE NOT EXISTS (SELECT 1 FROM news_article_tickers nat WHERE nat.news_article_id = na.news_article_id)',
 'warning', 'News articles should be linked to at least one ticker');

-- SEC FILINGS validation rules
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('sec_no_null_accession', 'sec_filings', 'completeness',
 'SELECT COUNT(*) FROM sec_filings WHERE accession_number IS NULL OR accession_number = ''''',
 'critical', 'SEC filings must have accession numbers'),

('sec_duplicate_accession', 'sec_filings', 'consistency',
 'SELECT COUNT(*) - COUNT(DISTINCT accession_number) FROM sec_filings',
 'critical', 'SEC accession numbers must be unique'),

('sec_invalid_form_types', 'sec_filings', 'accuracy',
 'SELECT COUNT(*) FROM sec_filings WHERE form_type NOT IN (''10-K'', ''10-Q'', ''8-K'', ''S-1'', ''S-3'', ''13F'', ''4'', ''3'', ''DEF 14A'')',
 'info', 'Check for unexpected SEC form types'),

('sec_future_filing_dates', 'sec_filings', 'accuracy',
 'SELECT COUNT(*) FROM sec_filings WHERE filing_date > CURRENT_DATE',
 'critical', 'SEC filings cannot have future dates'),

('sec_period_date_consistency', 'sec_filings', 'consistency',
 'SELECT COUNT(*) FROM sec_filings WHERE period_end_date > filing_date',
 'critical', 'Period end date should be before or equal to filing date');

-- SENTIMENT validation rules (all sentiment tables)
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('reddit_sentiment_score_range', 'reddit_post_sentiment', 'accuracy',
 'SELECT COUNT(*) FROM reddit_post_sentiment WHERE sentiment_score < -1 OR sentiment_score > 1',
 'critical', 'Sentiment scores must be between -1 and 1'),

('reddit_sentiment_probability_sum', 'reddit_post_sentiment', 'accuracy',
 'SELECT COUNT(*) FROM reddit_post_sentiment WHERE ABS((positive_score + negative_score + neutral_score) - 1.0) > 0.01',
 'warning', 'Sentiment probabilities should sum to ~1.0'),

('news_sentiment_score_range', 'news_article_sentiment', 'accuracy',
 'SELECT COUNT(*) FROM news_article_sentiment WHERE sentiment_score < -1 OR sentiment_score > 1',
 'critical', 'Sentiment scores must be between -1 and 1'),

('sec_sentiment_score_range', 'sec_filing_sentiment', 'accuracy',
 'SELECT COUNT(*) FROM sec_filing_sentiment WHERE sentiment_score < -1 OR sentiment_score > 1',
 'critical', 'Sentiment scores must be between -1 and 1');

-- CROSS-TABLE validation rules
INSERT INTO data_quality_rules (rule_name, table_name, rule_type, sql_check, severity, description) VALUES
('cross_orphaned_reddit_sentiment', 'reddit_post_sentiment', 'consistency',
 'SELECT COUNT(*) FROM reddit_post_sentiment rps WHERE NOT EXISTS (SELECT 1 FROM reddit_posts rp WHERE rp.reddit_post_id = rps.reddit_post_id)',
 'critical', 'Sentiment records must reference valid posts'),

('cross_orphaned_news_sentiment', 'news_article_sentiment', 'consistency',
 'SELECT COUNT(*) FROM news_article_sentiment nas WHERE NOT EXISTS (SELECT 1 FROM news_articles na WHERE na.news_article_id = nas.news_article_id)',
 'critical', 'Sentiment records must reference valid articles'),

('cross_mismatched_ticker_mapping', 'reddit_post_tickers', 'consistency',
 'SELECT COUNT(*) FROM reddit_post_sentiment rps 
  LEFT JOIN reddit_post_tickers rpt ON rps.reddit_post_id = rpt.reddit_post_id AND rps.ticker_id = rpt.ticker_id
  WHERE rpt.mapping_id IS NULL',
 'warning', 'Sentiment records should have corresponding ticker mappings');

-- ----------------------------------------------------------------------------
-- 4. FUNCTIONS TO RUN VALIDATION CHECKS
-- ----------------------------------------------------------------------------

-- Execute a single validation rule
CREATE OR REPLACE FUNCTION run_quality_check(p_rule_id INTEGER)
RETURNS TABLE(
    rule_name VARCHAR,
    records_failed BIGINT,
    status VARCHAR,
    details TEXT
) AS $$
DECLARE
    v_rule data_quality_rules%ROWTYPE;
    v_failed_count BIGINT;
    v_start_time TIMESTAMP;
    v_execution_ms INTEGER;
BEGIN
    v_start_time := clock_timestamp();
    
    -- Get rule details
    SELECT * INTO v_rule FROM data_quality_rules WHERE rule_id = p_rule_id AND is_active = true;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Rule ID % not found or inactive', p_rule_id;
    END IF;
    
    -- Execute the validation query
    EXECUTE v_rule.sql_check INTO v_failed_count;
    
    v_execution_ms := EXTRACT(MILLISECONDS FROM clock_timestamp() - v_start_time);
    
    -- Determine status
    status := CASE
        WHEN v_failed_count = 0 THEN 'pass'
        WHEN v_rule.severity = 'critical' THEN 'fail'
        ELSE 'warning'
    END;
    
    -- Store result
    INSERT INTO data_quality_results (
        rule_id, records_checked, records_failed, 
        failure_rate, status, execution_time_ms
    ) VALUES (
        p_rule_id, NULL, v_failed_count,
        NULL, status, v_execution_ms
    );
    
    RETURN QUERY SELECT v_rule.rule_name, v_failed_count, status, v_rule.description;
END;
$$ LANGUAGE plpgsql;

-- Run all validation checks
CREATE OR REPLACE FUNCTION run_all_quality_checks()
RETURNS TABLE(
    rule_name VARCHAR,
    table_name VARCHAR,
    severity VARCHAR,
    records_failed BIGINT,
    status VARCHAR,
    description TEXT
) AS $$
DECLARE
    v_rule RECORD;
    v_failed_count BIGINT;
    v_status VARCHAR;
BEGIN
    FOR v_rule IN 
        SELECT rule_id, data_quality_rules.rule_name, data_quality_rules.table_name, 
               data_quality_rules.severity, sql_check, data_quality_rules.description
        FROM data_quality_rules 
        WHERE is_active = true
        ORDER BY rule_id
    LOOP
        BEGIN
            EXECUTE v_rule.sql_check INTO v_failed_count;
            
            v_status := CASE
                WHEN v_failed_count = 0 THEN 'pass'
                WHEN v_rule.severity = 'critical' THEN 'fail'
                ELSE 'warning'
            END;
            
            INSERT INTO data_quality_results (
                rule_id, records_failed, status
            ) VALUES (
                v_rule.rule_id, v_failed_count, v_status
            );
            
            RETURN QUERY SELECT 
                v_rule.rule_name, 
                v_rule.table_name, 
                v_rule.severity,
                v_failed_count, 
                v_status,
                v_rule.description;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 
                v_rule.rule_name,
                v_rule.table_name,
                v_rule.severity,
                -1::BIGINT,
                'error'::VARCHAR,
                ('Error: ' || SQLERRM)::TEXT;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 5. DATA QUALITY DASHBOARD VIEW
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW data_quality_dashboard AS
SELECT 
    r.table_name,
    r.rule_type,
    r.severity,
    COUNT(*) as total_rules,
    COUNT(*) FILTER (WHERE res.status = 'pass') as passed,
    COUNT(*) FILTER (WHERE res.status = 'fail') as failed,
    COUNT(*) FILTER (WHERE res.status = 'warning') as warnings,
    MAX(res.check_timestamp) as last_check
FROM data_quality_rules r
LEFT JOIN LATERAL (
    SELECT status, check_timestamp
    FROM data_quality_results
    WHERE rule_id = r.rule_id
    ORDER BY check_timestamp DESC
    LIMIT 1
) res ON true
WHERE r.is_active = true
GROUP BY r.table_name, r.rule_type, r.severity
ORDER BY r.table_name, r.rule_type;

-- ----------------------------------------------------------------------------
-- 6. DETAILED QUALITY REPORT VIEW
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW data_quality_latest_results AS
SELECT 
    r.rule_name,
    r.table_name,
    r.rule_type,
    r.severity,
    r.description,
    res.records_failed,
    res.status,
    res.check_timestamp,
    res.execution_time_ms
FROM data_quality_rules r
JOIN LATERAL (
    SELECT *
    FROM data_quality_results
    WHERE rule_id = r.rule_id
    ORDER BY check_timestamp DESC
    LIMIT 1
) res ON true
WHERE r.is_active = true
ORDER BY 
    CASE res.status 
        WHEN 'fail' THEN 1 
        WHEN 'warning' THEN 2 
        ELSE 3 
    END,
    r.table_name,
    r.rule_name;

-- ----------------------------------------------------------------------------
-- 7. DATA COMPLETENESS SUMMARY
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW data_completeness_summary AS
SELECT 
    'tickers' as table_name,
    COUNT(*) as total_records,
    COUNT(*) FILTER (WHERE symbol IS NOT NULL) as non_null_symbols,
    COUNT(*) FILTER (WHERE company_name IS NOT NULL) as non_null_names,
    COUNT(*) FILTER (WHERE sector IS NOT NULL) as non_null_sectors
FROM tickers
UNION ALL
SELECT 
    'stock_prices',
    COUNT(*),
    COUNT(*) FILTER (WHERE close IS NOT NULL),
    COUNT(*) FILTER (WHERE volume IS NOT NULL),
    COUNT(*) FILTER (WHERE adj_close IS NOT NULL)
FROM stock_prices
UNION ALL
SELECT 
    'reddit_posts',
    COUNT(*),
    COUNT(*) FILTER (WHERE title IS NOT NULL),
    COUNT(*) FILTER (WHERE selftext IS NOT NULL AND selftext != ''),
    COUNT(*) FILTER (WHERE score IS NOT NULL)
FROM reddit_posts
UNION ALL
SELECT 
    'news_articles',
    COUNT(*),
    COUNT(*) FILTER (WHERE title IS NOT NULL),
    COUNT(*) FILTER (WHERE content IS NOT NULL AND content != ''),
    COUNT(*) FILTER (WHERE author IS NOT NULL)
FROM news_articles
UNION ALL
SELECT 
    'sec_filings',
    COUNT(*),
    COUNT(*) FILTER (WHERE form_type IS NOT NULL),
    COUNT(*) FILTER (WHERE filing_date IS NOT NULL),
    COUNT(*) FILTER (WHERE document_text IS NOT NULL)
FROM sec_filings;