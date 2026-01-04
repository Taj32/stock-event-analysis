-- ============================================================================
-- DATE ALIGNMENT SYSTEM
-- Ensures all events sync to correct trading days
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. TRADING CALENDAR TABLE - Reference timeline
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading_calendar (
    calendar_date DATE PRIMARY KEY,
    is_trading_day BOOLEAN NOT NULL DEFAULT FALSE,
    exchange VARCHAR(10) DEFAULT 'NYSE',
    holiday_name VARCHAR(100),
    year INTEGER,
    month INTEGER,
    day_of_week INTEGER, -- 0=Monday, 6=Sunday
    quarter INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trading_calendar_trading_days ON trading_calendar(calendar_date) 
    WHERE is_trading_day = TRUE;
CREATE INDEX IF NOT EXISTS idx_trading_calendar_year_month ON trading_calendar(year, month);

-- ----------------------------------------------------------------------------
-- 2. POPULATE TRADING CALENDAR (2020-2026)
-- ----------------------------------------------------------------------------

-- Function to populate basic calendar (all dates, mark weekends)
CREATE OR REPLACE FUNCTION populate_calendar(start_date DATE, end_date DATE)
RETURNS VOID AS $$
BEGIN
    INSERT INTO trading_calendar (
        calendar_date, 
        is_trading_day, 
        year, 
        month, 
        day_of_week,
        quarter
    )
    SELECT
        d,
        CASE WHEN EXTRACT(DOW FROM d) IN (0, 6) THEN FALSE ELSE TRUE END,
        EXTRACT(YEAR FROM d)::INTEGER,
        EXTRACT(MONTH FROM d)::INTEGER,
        CASE WHEN EXTRACT(DOW FROM d) = 0 THEN 6 ELSE EXTRACT(DOW FROM d) - 1 END,
        EXTRACT(QUARTER FROM d)::INTEGER
    FROM generate_series(start_date, end_date, '1 day'::INTERVAL) AS d
    ON CONFLICT (calendar_date) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Populate calendar from 2020 to 2026
SELECT populate_calendar('2020-01-01'::DATE, '2026-12-31'::DATE);

-- Mark US market holidays (NYSE/NASDAQ)
-- Note: Some holidays vary by year, this covers common ones

-- New Year's Day
UPDATE trading_calendar 
SET is_trading_day = FALSE, holiday_name = 'New Year''s Day'
WHERE (month = 1 AND day_of_week IN (SELECT EXTRACT(DOW FROM date) FROM generate_series('2020-01-01'::date, '2026-01-01'::date, '1 year'::interval) date WHERE EXTRACT(MONTH FROM date) = 1 AND EXTRACT(DAY FROM date) = 1))
   OR (month = 1 AND EXTRACT(DAY FROM calendar_date) = 1);

-- Simplified holiday marking - mark known holidays
UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'New Year''s Day' 
WHERE (month = 1 AND EXTRACT(DAY FROM calendar_date) = 1);

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Independence Day' 
WHERE (month = 7 AND EXTRACT(DAY FROM calendar_date) = 4);

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Christmas' 
WHERE (month = 12 AND EXTRACT(DAY FROM calendar_date) = 25);

-- Specific known holidays (you can expand this list)
UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'MLK Day' 
WHERE calendar_date IN ('2020-01-20', '2021-01-18', '2022-01-17', '2023-01-16', '2024-01-15', '2025-01-20', '2026-01-19');

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Presidents Day' 
WHERE calendar_date IN ('2020-02-17', '2021-02-15', '2022-02-21', '2023-02-20', '2024-02-19', '2025-02-17', '2026-02-16');

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Good Friday' 
WHERE calendar_date IN ('2020-04-10', '2021-04-02', '2022-04-15', '2023-04-07', '2024-03-29', '2025-04-18', '2026-04-03');

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Memorial Day' 
WHERE calendar_date IN ('2020-05-25', '2021-05-31', '2022-05-30', '2023-05-29', '2024-05-27', '2025-05-26', '2026-05-25');

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Labor Day' 
WHERE calendar_date IN ('2020-09-07', '2021-09-06', '2022-09-05', '2023-09-04', '2024-09-02', '2025-09-01', '2026-09-07');

UPDATE trading_calendar SET is_trading_day = FALSE, holiday_name = 'Thanksgiving' 
WHERE calendar_date IN ('2020-11-26', '2021-11-25', '2022-11-24', '2023-11-23', '2024-11-28', '2025-11-27', '2026-11-26');

-- ----------------------------------------------------------------------------
-- 3. HELPER FUNCTIONS
-- ----------------------------------------------------------------------------

-- Get next trading day
CREATE OR REPLACE FUNCTION get_next_trading_day(input_date DATE)
RETURNS DATE AS $$
DECLARE
    next_day DATE;
BEGIN
    SELECT MIN(calendar_date) INTO next_day
    FROM trading_calendar
    WHERE calendar_date >= input_date 
      AND is_trading_day = TRUE;
    RETURN next_day;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Get previous trading day
CREATE OR REPLACE FUNCTION get_previous_trading_day(input_date DATE)
RETURNS DATE AS $$
DECLARE
    prev_day DATE;
BEGIN
    SELECT MAX(calendar_date) INTO prev_day
    FROM trading_calendar
    WHERE calendar_date <= input_date 
      AND is_trading_day = TRUE;
    RETURN prev_day;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Check if a date is a trading day
CREATE OR REPLACE FUNCTION is_trading_day(check_date DATE)
RETURNS BOOLEAN AS $$
DECLARE
    result BOOLEAN;
BEGIN
    SELECT is_trading_day INTO result
    FROM trading_calendar
    WHERE calendar_date = check_date;
    RETURN COALESCE(result, FALSE);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ----------------------------------------------------------------------------
-- 4. MAIN ALIGNMENT FUNCTION
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION align_to_trading_day(
    input_timestamp TIMESTAMP WITH TIME ZONE,
    market_timezone TEXT DEFAULT 'America/New_York'
)
RETURNS TABLE(
    trading_date DATE,
    is_market_hours BOOLEAN,
    alignment_rule VARCHAR(50)
) AS $$
DECLARE
    local_time TIMESTAMP;
    event_date DATE;
    event_time TIME;
    market_open TIME := '09:30:00';
    market_close TIME := '16:00:00';
    next_trading DATE;
    is_trading BOOLEAN;
BEGIN
    -- Convert to market timezone (NYSE = Eastern Time)
    local_time := input_timestamp AT TIME ZONE market_timezone;
    event_date := local_time::DATE;
    event_time := local_time::TIME;
    
    -- Check if during market hours
    is_market_hours := (event_time >= market_open AND event_time < market_close);
    
    -- Check if event date is a trading day
    SELECT tc.is_trading_day INTO is_trading
    FROM trading_calendar tc
    WHERE tc.calendar_date = event_date;
    
    -- Alignment logic
    IF is_trading AND is_market_hours THEN
        -- Event during market hours on a trading day
        trading_date := event_date;
        alignment_rule := 'same_day_market_hours';
        
    ELSIF is_trading AND event_time >= market_close THEN
        -- Event after market close on a trading day
        trading_date := get_next_trading_day(event_date + 1);
        is_market_hours := FALSE;
        alignment_rule := 'after_hours_to_next';
        
    ELSIF is_trading AND event_time < market_open THEN
        -- Event before market open on a trading day
        trading_date := event_date;
        is_market_hours := FALSE;
        alignment_rule := 'pre_market_to_same';
        
    ELSE
        -- Event on non-trading day (weekend/holiday)
        trading_date := get_next_trading_day(event_date);
        is_market_hours := FALSE;
        alignment_rule := 'non_trading_day_to_next';
    END IF;
    
    RETURN QUERY SELECT trading_date, is_market_hours, alignment_rule;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Simpler version that just returns the date
CREATE OR REPLACE FUNCTION align_timestamp_to_trading_date(
    input_timestamp TIMESTAMP WITH TIME ZONE
)
RETURNS DATE AS $$
DECLARE
    result RECORD;
BEGIN
    SELECT * INTO result FROM align_to_trading_day(input_timestamp);
    RETURN result.trading_date;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ----------------------------------------------------------------------------
-- 5. UPDATE EXISTING TABLES - Add alignment columns
-- ----------------------------------------------------------------------------

-- Add columns to reddit_posts
ALTER TABLE reddit_posts 
ADD COLUMN IF NOT EXISTS trading_date DATE,
ADD COLUMN IF NOT EXISTS is_market_hours BOOLEAN,
ADD COLUMN IF NOT EXISTS alignment_rule VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_reddit_posts_trading_date ON reddit_posts(trading_date);
CREATE INDEX IF NOT EXISTS idx_reddit_posts_ticker_trading_date ON reddit_posts(trading_date);

-- Add columns to news_articles
ALTER TABLE news_articles 
ADD COLUMN IF NOT EXISTS trading_date DATE,
ADD COLUMN IF NOT EXISTS is_market_hours BOOLEAN,
ADD COLUMN IF NOT EXISTS alignment_rule VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_news_articles_trading_date ON news_articles(trading_date);

-- Add columns to sec_filings
ALTER TABLE sec_filings 
ADD COLUMN IF NOT EXISTS trading_date DATE,
ADD COLUMN IF NOT EXISTS is_market_hours BOOLEAN,
ADD COLUMN IF NOT EXISTS alignment_rule VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_sec_filings_trading_date ON sec_filings(trading_date);

-- ----------------------------------------------------------------------------
-- 6. POPULATE ALIGNMENT FOR EXISTING DATA
-- ----------------------------------------------------------------------------

-- Align Reddit posts
UPDATE reddit_posts rp
SET (trading_date, is_market_hours, alignment_rule) = (
    SELECT a.trading_date, a.is_market_hours, a.alignment_rule
    FROM align_to_trading_day(rp.created_utc) a
)
WHERE trading_date IS NULL;

-- Align News articles
UPDATE news_articles na
SET (trading_date, is_market_hours, alignment_rule) = (
    SELECT a.trading_date, a.is_market_hours, a.alignment_rule
    FROM align_to_trading_day(na.published_at) a
)
WHERE trading_date IS NULL;

-- Align SEC filings
UPDATE sec_filings sf
SET (trading_date, is_market_hours, alignment_rule) = (
    SELECT a.trading_date, a.is_market_hours, a.alignment_rule
    FROM align_to_trading_day(
        COALESCE(sf.acceptance_datetime, sf.filing_date::TIMESTAMP WITH TIME ZONE)
    ) a
)
WHERE trading_date IS NULL;

-- ----------------------------------------------------------------------------
-- 7. AUTOMATIC ALIGNMENT TRIGGERS
-- ----------------------------------------------------------------------------

-- Trigger function for Reddit posts
CREATE OR REPLACE FUNCTION align_reddit_post_dates()
RETURNS TRIGGER AS $$
DECLARE
    alignment RECORD;
BEGIN
    SELECT * INTO alignment FROM align_to_trading_day(NEW.created_utc);
    NEW.trading_date := alignment.trading_date;
    NEW.is_market_hours := alignment.is_market_hours;
    NEW.alignment_rule := alignment.alignment_rule;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS reddit_post_alignment_trigger ON reddit_posts;
CREATE TRIGGER reddit_post_alignment_trigger
    BEFORE INSERT OR UPDATE OF created_utc ON reddit_posts
    FOR EACH ROW
    EXECUTE FUNCTION align_reddit_post_dates();

-- Trigger function for News articles
CREATE OR REPLACE FUNCTION align_news_article_dates()
RETURNS TRIGGER AS $$
DECLARE
    alignment RECORD;
BEGIN
    SELECT * INTO alignment FROM align_to_trading_day(NEW.published_at);
    NEW.trading_date := alignment.trading_date;
    NEW.is_market_hours := alignment.is_market_hours;
    NEW.alignment_rule := alignment.alignment_rule;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS news_article_alignment_trigger ON news_articles;
CREATE TRIGGER news_article_alignment_trigger
    BEFORE INSERT OR UPDATE OF published_at ON news_articles
    FOR EACH ROW
    EXECUTE FUNCTION align_news_article_dates();

-- Trigger function for SEC filings
CREATE OR REPLACE FUNCTION align_sec_filing_dates()
RETURNS TRIGGER AS $$
DECLARE
    alignment RECORD;
    timestamp_to_use TIMESTAMP WITH TIME ZONE;
BEGIN
    timestamp_to_use := COALESCE(NEW.acceptance_datetime, NEW.filing_date::TIMESTAMP WITH TIME ZONE);
    SELECT * INTO alignment FROM align_to_trading_day(timestamp_to_use);
    NEW.trading_date := alignment.trading_date;
    NEW.is_market_hours := alignment.is_market_hours;
    NEW.alignment_rule := alignment.alignment_rule;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop and recreate sec filing trigger to avoid conflicts
DROP TRIGGER IF EXISTS sec_filing_alignment_trigger ON sec_filings;
CREATE TRIGGER sec_filing_alignment_trigger
    BEFORE INSERT OR UPDATE OF acceptance_datetime, filing_date ON sec_filings
    FOR EACH ROW
    EXECUTE FUNCTION align_sec_filing_dates();

-- ----------------------------------------------------------------------------
-- 8. UNIFIED EVENTS VIEW - All sources with aligned dates
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW unified_events_aligned AS
-- Reddit events
SELECT 
    t.symbol AS ticker,
    t.ticker_id,
    rp.trading_date,
    rp.created_utc AS original_timestamp,
    'reddit' AS source,
    'reddit_post' AS event_type,
    rps.sentiment_score AS magnitude,
    CASE 
        WHEN rps.sentiment_score > 0 THEN 'positive'
        WHEN rps.sentiment_score < 0 THEN 'negative'
        ELSE 'neutral'
    END AS direction,
    rp.is_market_hours,
    rp.alignment_rule,
    rp.reddit_post_id AS source_id
FROM reddit_posts rp
JOIN reddit_post_tickers rpt ON rp.reddit_post_id = rpt.reddit_post_id
JOIN tickers t ON rpt.ticker_id = t.ticker_id
LEFT JOIN reddit_post_sentiment rps ON rp.reddit_post_id = rps.reddit_post_id 
    AND rps.ticker_id = t.ticker_id
WHERE rp.trading_date IS NOT NULL

UNION ALL

-- News events
SELECT 
    t.symbol AS ticker,
    t.ticker_id,
    na.trading_date,
    na.published_at AS original_timestamp,
    'news' AS source,
    'news_article' AS event_type,
    nas.sentiment_score AS magnitude,
    CASE 
        WHEN nas.sentiment_score > 0 THEN 'positive'
        WHEN nas.sentiment_score < 0 THEN 'negative'
        ELSE 'neutral'
    END AS direction,
    na.is_market_hours,
    na.alignment_rule,
    na.news_article_id AS source_id
FROM news_articles na
JOIN news_article_tickers nat ON na.news_article_id = nat.news_article_id
JOIN tickers t ON nat.ticker_id = t.ticker_id
LEFT JOIN news_article_sentiment nas ON na.news_article_id = nas.news_article_id 
    AND nas.ticker_id = t.ticker_id
WHERE na.trading_date IS NOT NULL

UNION ALL

-- SEC filing events
SELECT 
    t.symbol AS ticker,
    t.ticker_id,
    sf.trading_date,
    COALESCE(sf.acceptance_datetime, sf.filing_date::TIMESTAMP) AS original_timestamp,
    'sec' AS source,
    sf.form_type AS event_type,
    sfs.sentiment_score AS magnitude,
    CASE 
        WHEN sfs.sentiment_score > 0 THEN 'positive'
        WHEN sfs.sentiment_score < 0 THEN 'negative'
        ELSE 'neutral'
    END AS direction,
    sf.is_market_hours,
    sf.alignment_rule,
    sf.filing_id AS source_id
FROM sec_filings sf
JOIN tickers t ON sf.ticker_id = t.ticker_id
LEFT JOIN sec_filing_sentiment sfs ON sf.filing_id = sfs.filing_id
WHERE sf.trading_date IS NOT NULL;

-- ----------------------------------------------------------------------------
-- 9. VERIFICATION QUERIES
-- ----------------------------------------------------------------------------

-- View alignment statistics
CREATE OR REPLACE VIEW alignment_statistics AS
SELECT 
    'Reddit Posts' as source,
    COUNT(*) as total_records,
    COUNT(*) FILTER (WHERE alignment_rule = 'same_day_market_hours') as same_day_market_hours,
    COUNT(*) FILTER (WHERE alignment_rule = 'after_hours_to_next') as after_hours,
    COUNT(*) FILTER (WHERE alignment_rule = 'pre_market_to_same') as pre_market,
    COUNT(*) FILTER (WHERE alignment_rule = 'non_trading_day_to_next') as non_trading_day
FROM reddit_posts
WHERE trading_date IS NOT NULL

UNION ALL

SELECT 
    'News Articles',
    COUNT(*),
    COUNT(*) FILTER (WHERE alignment_rule = 'same_day_market_hours'),
    COUNT(*) FILTER (WHERE alignment_rule = 'after_hours_to_next'),
    COUNT(*) FILTER (WHERE alignment_rule = 'pre_market_to_same'),
    COUNT(*) FILTER (WHERE alignment_rule = 'non_trading_day_to_next')
FROM news_articles
WHERE trading_date IS NOT NULL

UNION ALL

SELECT 
    'SEC Filings',
    COUNT(*),
    COUNT(*) FILTER (WHERE alignment_rule = 'same_day_market_hours'),
    COUNT(*) FILTER (WHERE alignment_rule = 'after_hours_to_next'),
    COUNT(*) FILTER (WHERE alignment_rule = 'pre_market_to_same'),
    COUNT(*) FILTER (WHERE alignment_rule = 'non_trading_day_to_next')
FROM sec_filings
WHERE trading_date IS NOT NULL;