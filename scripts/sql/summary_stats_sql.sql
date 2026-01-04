-- ============================================================================
-- SUMMARY STATISTICS AND DATA AVAILABILITY REPORTING SYSTEM
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. OVERALL DATA SUMMARY - High-level counts and date ranges
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_overall_stats AS
SELECT 
    'Tickers' as metric,
    COUNT(*)::TEXT as value,
    NULL as details
FROM tickers

UNION ALL

SELECT 
    'Stock Prices',
    COUNT(*)::TEXT,
    CONCAT(
        'Date Range: ', 
        MIN(date)::TEXT, 
        ' to ', 
        MAX(date)::TEXT,
        ' (', 
        (MAX(date) - MIN(date))::TEXT, 
        ' days)'
    )
FROM stock_prices

UNION ALL

SELECT 
    'Reddit Posts',
    COUNT(*)::TEXT,
    CONCAT(
        'Date Range: ',
        MIN(created_utc)::DATE::TEXT,
        ' to ',
        MAX(created_utc)::DATE::TEXT
    )
FROM reddit_posts

UNION ALL

SELECT 
    'News Articles',
    COUNT(*)::TEXT,
    CONCAT(
        'Date Range: ',
        MIN(published_at)::DATE::TEXT,
        ' to ',
        MAX(published_at)::DATE::TEXT
    )
FROM news_articles

UNION ALL

SELECT 
    'SEC Filings',
    COUNT(*)::TEXT,
    CONCAT(
        'Date Range: ',
        MIN(filing_date)::TEXT,
        ' to ',
        MAX(filing_date)::TEXT
    )
FROM sec_filings;

-- ----------------------------------------------------------------------------
-- 2. TICKER-LEVEL AVAILABILITY - What data exists for each stock
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_ticker_availability AS
SELECT 
    t.symbol,
    t.company_name,
    t.sector,
    
    -- Price data
    COUNT(DISTINCT sp.date) as price_days,
    MIN(sp.date) as price_start_date,
    MAX(sp.date) as price_end_date,
    CASE 
        WHEN COUNT(DISTINCT sp.date) = 0 THEN 'None'
        WHEN COUNT(DISTINCT sp.date) < 30 THEN 'Limited'
        WHEN COUNT(DISTINCT sp.date) < 252 THEN 'Partial Year'
        ELSE 'Good'
    END as price_coverage,
    
    -- Reddit data
    COUNT(DISTINCT rpt.reddit_post_id) as reddit_posts,
    MIN(rp.created_utc)::DATE as reddit_first_mention,
    MAX(rp.created_utc)::DATE as reddit_last_mention,
    COUNT(DISTINCT rps.sentiment_id) as reddit_sentiment_count,
    ROUND(AVG(rps.sentiment_score)::NUMERIC, 3) as reddit_avg_sentiment,
    
    -- News data
    COUNT(DISTINCT nat.news_article_id) as news_articles,
    MIN(na.published_at)::DATE as news_first_mention,
    MAX(na.published_at)::DATE as news_last_mention,
    COUNT(DISTINCT nas.sentiment_id) as news_sentiment_count,
    ROUND(AVG(nas.sentiment_score)::NUMERIC, 3) as news_avg_sentiment,
    
    -- SEC data
    COUNT(DISTINCT sf.filing_id) as sec_filings,
    COUNT(DISTINCT sf.filing_id) FILTER (WHERE sf.form_type = '10-K') as sec_10k_count,
    COUNT(DISTINCT sf.filing_id) FILTER (WHERE sf.form_type = '10-Q') as sec_10q_count,
    COUNT(DISTINCT sf.filing_id) FILTER (WHERE sf.form_type = '8-K') as sec_8k_count,
    MIN(sf.filing_date) as sec_first_filing,
    MAX(sf.filing_date) as sec_last_filing,
    
    -- Overall assessment
    CASE 
        WHEN COUNT(DISTINCT sp.date) > 100 
         AND COUNT(DISTINCT rpt.reddit_post_id) > 10 
         AND COUNT(DISTINCT nat.news_article_id) > 5 
        THEN 'Excellent'
        WHEN COUNT(DISTINCT sp.date) > 50 
         AND (COUNT(DISTINCT rpt.reddit_post_id) > 5 OR COUNT(DISTINCT nat.news_article_id) > 3)
        THEN 'Good'
        WHEN COUNT(DISTINCT sp.date) > 20
        THEN 'Moderate'
        ELSE 'Limited'
    END as overall_data_quality

FROM tickers t
LEFT JOIN stock_prices sp ON t.ticker_id = sp.ticker_id
LEFT JOIN reddit_post_tickers rpt ON t.ticker_id = rpt.ticker_id
LEFT JOIN reddit_posts rp ON rpt.reddit_post_id = rp.reddit_post_id
LEFT JOIN reddit_post_sentiment rps ON rpt.reddit_post_id = rps.reddit_post_id 
    AND rpt.ticker_id = rps.ticker_id
LEFT JOIN news_article_tickers nat ON t.ticker_id = nat.ticker_id
LEFT JOIN news_articles na ON nat.news_article_id = na.news_article_id
LEFT JOIN news_article_sentiment nas ON nat.news_article_id = nas.news_article_id 
    AND nat.ticker_id = nas.ticker_id
LEFT JOIN sec_filings sf ON t.ticker_id = sf.ticker_id

GROUP BY t.ticker_id, t.symbol, t.company_name, t.sector
ORDER BY price_days DESC, reddit_posts DESC;

-- ----------------------------------------------------------------------------
-- 3. TIME SERIES DENSITY - Data points per month/week
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_time_series_density AS
WITH monthly_counts AS (
    SELECT 
        DATE_TRUNC('month', sp.date) as month,
        COUNT(DISTINCT sp.ticker_id) as tickers_with_prices,
        COUNT(*) as price_records,
        ROUND(AVG(sp.volume)::NUMERIC, 0) as avg_daily_volume
    FROM stock_prices sp
    GROUP BY DATE_TRUNC('month', sp.date)
),
reddit_monthly AS (
    SELECT 
        DATE_TRUNC('month', rp.created_utc) as month,
        COUNT(*) as reddit_posts,
        COUNT(DISTINCT rpt.ticker_id) as tickers_mentioned
    FROM reddit_posts rp
    JOIN reddit_post_tickers rpt ON rp.reddit_post_id = rpt.reddit_post_id
    GROUP BY DATE_TRUNC('month', rp.created_utc)
),
news_monthly AS (
    SELECT 
        DATE_TRUNC('month', na.published_at) as month,
        COUNT(*) as news_articles,
        COUNT(DISTINCT nat.ticker_id) as tickers_mentioned
    FROM news_articles na
    JOIN news_article_tickers nat ON na.news_article_id = nat.news_article_id
    GROUP BY DATE_TRUNC('month', na.published_at)
),
sec_monthly AS (
    SELECT 
        DATE_TRUNC('month', sf.filing_date) as month,
        COUNT(*) as sec_filings,
        COUNT(DISTINCT sf.ticker_id) as tickers_filing
    FROM sec_filings sf
    GROUP BY DATE_TRUNC('month', sf.filing_date)
)
SELECT 
    COALESCE(mc.month, rm.month, nm.month, sm.month) as month,
    COALESCE(mc.tickers_with_prices, 0) as tickers_with_prices,
    COALESCE(mc.price_records, 0) as price_records,
    COALESCE(rm.reddit_posts, 0) as reddit_posts,
    COALESCE(rm.tickers_mentioned, 0) as reddit_ticker_mentions,
    COALESCE(nm.news_articles, 0) as news_articles,
    COALESCE(nm.tickers_mentioned, 0) as news_ticker_mentions,
    COALESCE(sm.sec_filings, 0) as sec_filings,
    COALESCE(sm.tickers_filing, 0) as sec_tickers_filing
FROM monthly_counts mc
FULL OUTER JOIN reddit_monthly rm ON mc.month = rm.month
FULL OUTER JOIN news_monthly nm ON COALESCE(mc.month, rm.month) = nm.month
FULL OUTER JOIN sec_monthly sm ON COALESCE(mc.month, rm.month, nm.month) = sm.month
ORDER BY month DESC;

-- ----------------------------------------------------------------------------
-- 4. SENTIMENT DISTRIBUTION STATISTICS
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_sentiment_stats AS
WITH reddit_stats AS (
    SELECT 
        'Reddit' as source,
        COUNT(*) as total_records,
        ROUND(AVG(sentiment_score)::NUMERIC, 4) as mean_score,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sentiment_score)::NUMERIC, 4) as median_score,
        ROUND(STDDEV(sentiment_score)::NUMERIC, 4) as std_dev,
        MIN(sentiment_score) as min_score,
        MAX(sentiment_score) as max_score,
        ROUND((PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sentiment_score))::NUMERIC, 4) as percentile_25,
        ROUND((PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sentiment_score))::NUMERIC, 4) as percentile_75,
        COUNT(*) FILTER (WHERE sentiment_score > 0) as positive_count,
        COUNT(*) FILTER (WHERE sentiment_score < 0) as negative_count,
        COUNT(*) FILTER (WHERE sentiment_score = 0) as neutral_count,
        COUNT(DISTINCT ticker_id) as unique_tickers
    FROM reddit_post_sentiment
),
news_stats AS (
    SELECT 
        'News' as source,
        COUNT(*) as total_records,
        ROUND(AVG(sentiment_score)::NUMERIC, 4) as mean_score,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sentiment_score)::NUMERIC, 4) as median_score,
        ROUND(STDDEV(sentiment_score)::NUMERIC, 4) as std_dev,
        MIN(sentiment_score) as min_score,
        MAX(sentiment_score) as max_score,
        ROUND((PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sentiment_score))::NUMERIC, 4) as percentile_25,
        ROUND((PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sentiment_score))::NUMERIC, 4) as percentile_75,
        COUNT(*) FILTER (WHERE sentiment_score > 0) as positive_count,
        COUNT(*) FILTER (WHERE sentiment_score < 0) as negative_count,
        COUNT(*) FILTER (WHERE sentiment_score = 0) as neutral_count,
        COUNT(DISTINCT ticker_id) as unique_tickers
    FROM news_article_sentiment
),
sec_stats AS (
    SELECT 
        'SEC Filings' as source,
        COUNT(*) as total_records,
        ROUND(AVG(sentiment_score)::NUMERIC, 4) as mean_score,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sentiment_score)::NUMERIC, 4) as median_score,
        ROUND(STDDEV(sentiment_score)::NUMERIC, 4) as std_dev,
        MIN(sentiment_score) as min_score,
        MAX(sentiment_score) as max_score,
        ROUND((PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sentiment_score))::NUMERIC, 4) as percentile_25,
        ROUND((PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sentiment_score))::NUMERIC, 4) as percentile_75,
        COUNT(*) FILTER (WHERE sentiment_score > 0) as positive_count,
        COUNT(*) FILTER (WHERE sentiment_score < 0) as negative_count,
        COUNT(*) FILTER (WHERE sentiment_score = 0) as neutral_count,
        COUNT(DISTINCT ticker_id) as unique_tickers
    FROM sec_filing_sentiment
)
SELECT * FROM reddit_stats
UNION ALL
SELECT * FROM news_stats
UNION ALL
SELECT * FROM sec_stats;

-- ----------------------------------------------------------------------------
-- 5. PRICE STATISTICS BY TICKER
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_price_stats AS
WITH daily_returns AS (
    SELECT 
        ticker_id,
        date,
        close,
        (close - LAG(close) OVER (PARTITION BY ticker_id ORDER BY date)) 
            / NULLIF(LAG(close) OVER (PARTITION BY ticker_id ORDER BY date), 0) * 100 as daily_return
    FROM stock_prices
),
ticker_stats AS (
    SELECT 
        sp.ticker_id,
        COUNT(*) as trading_days,
        MIN(sp.date) as first_date,
        MAX(sp.date) as last_date,
        ROUND(AVG(sp.close)::NUMERIC, 2) as avg_close_price,
        ROUND(STDDEV(sp.close)::NUMERIC, 2) as price_std_dev,
        MIN(sp.close) as min_close,
        MAX(sp.close) as max_close,
        ROUND(AVG(sp.volume)::NUMERIC, 0) as avg_volume,
        ROUND(MAX(sp.volume)::NUMERIC, 0) as max_volume
    FROM stock_prices sp
    GROUP BY sp.ticker_id
),
return_stats AS (
    SELECT 
        ticker_id,
        ROUND(AVG(daily_return)::NUMERIC, 4) as avg_daily_return_pct,
        ROUND(STDDEV(daily_return)::NUMERIC, 4) as return_volatility_pct
    FROM daily_returns
    WHERE daily_return IS NOT NULL
    GROUP BY ticker_id
),
total_returns AS (
    SELECT 
        ticker_id,
        ROUND((
            (MAX(close) - MIN(close)) / NULLIF(MIN(close), 0) * 100
        )::NUMERIC, 2) as total_return_pct
    FROM stock_prices
    GROUP BY ticker_id
)
SELECT 
    t.symbol,
    t.company_name,
    ts.trading_days,
    ts.first_date,
    ts.last_date,
    ts.avg_close_price,
    ts.price_std_dev,
    ts.min_close,
    ts.max_close,
    ts.avg_volume,
    ts.max_volume,
    rs.avg_daily_return_pct,
    rs.return_volatility_pct,
    tr.total_return_pct
FROM tickers t
JOIN ticker_stats ts ON t.ticker_id = ts.ticker_id
LEFT JOIN return_stats rs ON t.ticker_id = rs.ticker_id
LEFT JOIN total_returns tr ON t.ticker_id = tr.ticker_id
ORDER BY ts.trading_days DESC;

-- ----------------------------------------------------------------------------
-- 6. SOURCE ACTIVITY BY TICKER - Which tickers are most mentioned/active
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_ticker_activity AS
SELECT 
    t.symbol,
    t.company_name,
    
    -- Reddit activity
    COUNT(DISTINCT rpt.reddit_post_id) as reddit_mentions,
    COUNT(DISTINCT DATE(rp.created_utc)) as reddit_active_days,
    ROUND(AVG(rp.score)::NUMERIC, 0) as reddit_avg_score,
    ROUND(AVG(rps.sentiment_score)::NUMERIC, 3) as reddit_avg_sentiment,
    
    -- News activity
    COUNT(DISTINCT nat.news_article_id) as news_mentions,
    COUNT(DISTINCT DATE(na.published_at)) as news_active_days,
    ROUND(AVG(nas.sentiment_score)::NUMERIC, 3) as news_avg_sentiment,
    
    -- SEC activity
    COUNT(DISTINCT sf.filing_id) as total_filings,
    COUNT(DISTINCT sf.filing_id) FILTER (WHERE sf.form_type IN ('10-K', '10-Q')) as earnings_filings,
    COUNT(DISTINCT sf.filing_id) FILTER (WHERE sf.form_type = '8-K') as material_event_filings,
    
    -- Overall activity score (weighted combination)
    (
        COUNT(DISTINCT rpt.reddit_post_id) * 1.0 +
        COUNT(DISTINCT nat.news_article_id) * 2.0 +
        COUNT(DISTINCT sf.filing_id) * 5.0
    ) as activity_score

FROM tickers t
LEFT JOIN reddit_post_tickers rpt ON t.ticker_id = rpt.ticker_id
LEFT JOIN reddit_posts rp ON rpt.reddit_post_id = rp.reddit_post_id
LEFT JOIN reddit_post_sentiment rps ON rpt.reddit_post_id = rps.reddit_post_id 
    AND rpt.ticker_id = rps.ticker_id
LEFT JOIN news_article_tickers nat ON t.ticker_id = nat.ticker_id
LEFT JOIN news_articles na ON nat.news_article_id = na.news_article_id
LEFT JOIN news_article_sentiment nas ON nat.news_article_id = nas.news_article_id 
    AND nat.ticker_id = nas.ticker_id
LEFT JOIN sec_filings sf ON t.ticker_id = sf.ticker_id

GROUP BY t.ticker_id, t.symbol, t.company_name
ORDER BY activity_score DESC;

-- ----------------------------------------------------------------------------
-- 7. DATA GAPS REPORT - Missing data periods
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_data_gaps AS
WITH price_gaps AS (
    SELECT 
        t.symbol,
        sp.date as gap_end,
        LAG(sp.date) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date) as gap_start,
        sp.date - LAG(sp.date) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date) as gap_days
    FROM stock_prices sp
    JOIN tickers t ON sp.ticker_id = t.ticker_id
)
SELECT 
    symbol,
    gap_start,
    gap_end,
    gap_days,
    CASE 
        WHEN gap_days <= 3 THEN 'Weekend/Holiday'
        WHEN gap_days <= 7 THEN 'Short Gap'
        WHEN gap_days <= 30 THEN 'Medium Gap'
        ELSE 'Long Gap'
    END as gap_severity
FROM price_gaps
WHERE gap_days > 5  -- Only show gaps > 5 days (weekends + holiday)
ORDER BY gap_days DESC, symbol;

-- ----------------------------------------------------------------------------
-- 8. SECTOR ANALYSIS - Statistics by sector
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_sector_stats AS
WITH daily_returns AS (
    SELECT 
        sp.ticker_id,
        (sp.close - LAG(sp.close) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date)) 
            / NULLIF(LAG(sp.close) OVER (PARTITION BY sp.ticker_id ORDER BY sp.date), 0) * 100 as daily_return
    FROM stock_prices sp
)
SELECT 
    t.sector,
    COUNT(DISTINCT t.ticker_id) as ticker_count,
    COUNT(DISTINCT sp.date) as total_price_records,
    COUNT(DISTINCT rpt.reddit_post_id) as total_reddit_mentions,
    COUNT(DISTINCT nat.news_article_id) as total_news_articles,
    COUNT(DISTINCT sf.filing_id) as total_sec_filings,
    ROUND(AVG(rps.sentiment_score)::NUMERIC, 3) as avg_reddit_sentiment,
    ROUND(AVG(nas.sentiment_score)::NUMERIC, 3) as avg_news_sentiment,
    ROUND((SELECT AVG(daily_return) FROM daily_returns dr 
           JOIN tickers t2 ON dr.ticker_id = t2.ticker_id 
           WHERE t2.sector = t.sector)::NUMERIC, 4) as avg_daily_return_pct
FROM tickers t
LEFT JOIN stock_prices sp ON t.ticker_id = sp.ticker_id
LEFT JOIN reddit_post_tickers rpt ON t.ticker_id = rpt.ticker_id
LEFT JOIN reddit_post_sentiment rps ON rpt.reddit_post_id = rps.reddit_post_id 
    AND rpt.ticker_id = rps.ticker_id
LEFT JOIN news_article_tickers nat ON t.ticker_id = nat.ticker_id
LEFT JOIN news_article_sentiment nas ON nat.news_article_id = nas.news_article_id 
    AND nat.ticker_id = nas.ticker_id
LEFT JOIN sec_filings sf ON t.ticker_id = sf.ticker_id
WHERE t.sector IS NOT NULL
GROUP BY t.sector
ORDER BY ticker_count DESC;

-- ----------------------------------------------------------------------------
-- 9. DAILY SNAPSHOT - Recent activity summary
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW summary_recent_activity AS
WITH recent_days AS (
    SELECT DISTINCT date 
    FROM stock_prices 
    ORDER BY date DESC 
    LIMIT 30
),
daily_returns AS (
    SELECT 
        date,
        ticker_id,
        (close - LAG(close) OVER (PARTITION BY ticker_id ORDER BY date)) 
            / NULLIF(LAG(close) OVER (PARTITION BY ticker_id ORDER BY date), 0) * 100 as daily_return
    FROM stock_prices
)
SELECT 
    rd.date,
    COUNT(DISTINCT sp.ticker_id) as tickers_traded,
    ROUND(AVG(sp.volume)::NUMERIC, 0) as avg_volume,
    COUNT(DISTINCT rp.reddit_post_id) as reddit_posts,
    COUNT(DISTINCT na.news_article_id) as news_articles,
    COUNT(DISTINCT sf.filing_id) as sec_filings,
    ROUND((SELECT AVG(daily_return) FROM daily_returns WHERE date = rd.date)::NUMERIC, 2) as market_avg_return_pct
FROM recent_days rd
LEFT JOIN stock_prices sp ON rd.date = sp.date
LEFT JOIN reddit_posts rp ON DATE(rp.created_utc) = rd.date
LEFT JOIN news_articles na ON DATE(na.published_at) = rd.date
LEFT JOIN sec_filings sf ON sf.filing_date = rd.date
GROUP BY rd.date
ORDER BY rd.date DESC;

-- ----------------------------------------------------------------------------
-- HELPER FUNCTION: Generate full summary report
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION generate_summary_report()
RETURNS TABLE(
    section VARCHAR,
    subsection VARCHAR,
    metric VARCHAR,
    value TEXT
) AS $$
BEGIN
    RETURN QUERY
    -- Overall stats
    SELECT 
        'Overall Statistics'::VARCHAR,
        'Database Totals'::VARCHAR,
        metric,
        value
    FROM summary_overall_stats
    
    UNION ALL
    
    -- Top tickers by data quality
    SELECT 
        'Top Tickers'::VARCHAR,
        'Best Data Coverage'::VARCHAR,
        symbol,
        overall_data_quality
    FROM summary_ticker_availability
    ORDER BY 
        CASE overall_data_quality 
            WHEN 'Excellent' THEN 1 
            WHEN 'Good' THEN 2 
            WHEN 'Moderate' THEN 3 
            ELSE 4 
        END
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;