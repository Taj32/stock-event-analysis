-- ============================================================================
-- ESSENTIAL STOCK EVENT DATABASE SCHEMA (12 Tables)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. TICKERS - Central hub for all stock data
-- ----------------------------------------------------------------------------
CREATE TABLE tickers (
    ticker_id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) UNIQUE NOT NULL,
    company_name VARCHAR(255),
    sector VARCHAR(100),
    industry VARCHAR(100),
    cik VARCHAR(10),  -- SEC Central Index Key
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tickers_symbol ON tickers(symbol);

-- ----------------------------------------------------------------------------
-- 2. STOCK PRICES - Historical price data
-- ----------------------------------------------------------------------------
CREATE TABLE stock_prices (
    price_id BIGSERIAL PRIMARY KEY,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    open DECIMAL(12,4),
    high DECIMAL(12,4),
    low DECIMAL(12,4),
    close DECIMAL(12,4),
    adj_close DECIMAL(12,4),
    volume BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker_id, date)
);

CREATE INDEX idx_stock_prices_ticker_date ON stock_prices(ticker_id, date DESC);
CREATE INDEX idx_stock_prices_date ON stock_prices(date DESC);

-- ----------------------------------------------------------------------------
-- 3. REDDIT POSTS - Raw Reddit content
-- ----------------------------------------------------------------------------
CREATE TABLE reddit_posts (
    reddit_post_id BIGSERIAL PRIMARY KEY,
    post_id VARCHAR(20) UNIQUE NOT NULL,
    subreddit VARCHAR(100) NOT NULL,
    author VARCHAR(100),
    title TEXT,
    selftext TEXT,
    url TEXT,
    score INTEGER,
    upvote_ratio DECIMAL(4,3),
    num_comments INTEGER,
    created_utc TIMESTAMP NOT NULL,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT check_upvote_ratio CHECK (upvote_ratio >= 0 AND upvote_ratio <= 1)
);

CREATE INDEX idx_reddit_posts_created ON reddit_posts(created_utc DESC);
CREATE INDEX idx_reddit_posts_subreddit ON reddit_posts(subreddit, created_utc DESC);
CREATE INDEX idx_reddit_posts_post_id ON reddit_posts(post_id);

-- ----------------------------------------------------------------------------
-- 4. REDDIT POST TICKERS - Maps posts to mentioned tickers
-- ----------------------------------------------------------------------------
CREATE TABLE reddit_post_tickers (
    mapping_id BIGSERIAL PRIMARY KEY,
    reddit_post_id BIGINT REFERENCES reddit_posts(reddit_post_id) ON DELETE CASCADE,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    mention_count INTEGER DEFAULT 1,
    confidence DECIMAL(4,3),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(reddit_post_id, ticker_id)
);

CREATE INDEX idx_reddit_post_tickers_post ON reddit_post_tickers(reddit_post_id);
CREATE INDEX idx_reddit_post_tickers_ticker ON reddit_post_tickers(ticker_id);

-- ----------------------------------------------------------------------------
-- 5. REDDIT POST SENTIMENT - Sentiment analysis results for posts
-- ----------------------------------------------------------------------------
CREATE TABLE reddit_post_sentiment (
    sentiment_id BIGSERIAL PRIMARY KEY,
    reddit_post_id BIGINT REFERENCES reddit_posts(reddit_post_id) ON DELETE CASCADE,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    sentiment_label VARCHAR(20),
    sentiment_score DECIMAL(5,4),
    positive_score DECIMAL(5,4),
    negative_score DECIMAL(5,4),
    neutral_score DECIMAL(5,4),
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(reddit_post_id, ticker_id),
    CONSTRAINT check_sentiment_score CHECK (sentiment_score >= -1 AND sentiment_score <= 1)
);

CREATE INDEX idx_reddit_post_sentiment_post ON reddit_post_sentiment(reddit_post_id);
CREATE INDEX idx_reddit_post_sentiment_ticker ON reddit_post_sentiment(ticker_id);
CREATE INDEX idx_reddit_post_sentiment_score ON reddit_post_sentiment(sentiment_score);

-- ----------------------------------------------------------------------------
-- 6. NEWS ARTICLES - Raw news content
-- ----------------------------------------------------------------------------
CREATE TABLE news_articles (
    news_article_id BIGSERIAL PRIMARY KEY,
    article_id VARCHAR(255) UNIQUE,
    source VARCHAR(100) NOT NULL,
    author VARCHAR(255),
    title TEXT NOT NULL,
    description TEXT,
    content TEXT,
    url TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    word_count INTEGER
);

CREATE INDEX idx_news_published ON news_articles(published_at DESC);
CREATE INDEX idx_news_source ON news_articles(source, published_at DESC);
CREATE INDEX idx_news_url ON news_articles(url);

-- ----------------------------------------------------------------------------
-- 7. NEWS ARTICLE TICKERS - Maps articles to mentioned tickers
-- ----------------------------------------------------------------------------
CREATE TABLE news_article_tickers (
    mapping_id BIGSERIAL PRIMARY KEY,
    news_article_id BIGINT REFERENCES news_articles(news_article_id) ON DELETE CASCADE,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    mention_count INTEGER DEFAULT 1,
    prominence DECIMAL(4,3),
    relevance DECIMAL(4,3),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(news_article_id, ticker_id)
);

CREATE INDEX idx_news_article_tickers_article ON news_article_tickers(news_article_id);
CREATE INDEX idx_news_article_tickers_ticker ON news_article_tickers(ticker_id);

-- ----------------------------------------------------------------------------
-- 8. NEWS ARTICLE SENTIMENT - Sentiment analysis results for articles
-- ----------------------------------------------------------------------------
CREATE TABLE news_article_sentiment (
    sentiment_id BIGSERIAL PRIMARY KEY,
    news_article_id BIGINT REFERENCES news_articles(news_article_id) ON DELETE CASCADE,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    sentiment_label VARCHAR(20),
    sentiment_score DECIMAL(5,4),
    positive_score DECIMAL(5,4),
    negative_score DECIMAL(5,4),
    neutral_score DECIMAL(5,4),
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(news_article_id, ticker_id),
    CONSTRAINT check_sentiment_score CHECK (sentiment_score >= -1 AND sentiment_score <= 1)
);

CREATE INDEX idx_news_article_sentiment_article ON news_article_sentiment(news_article_id);
CREATE INDEX idx_news_article_sentiment_ticker ON news_article_sentiment(ticker_id);
CREATE INDEX idx_news_article_sentiment_score ON news_article_sentiment(sentiment_score);

-- ----------------------------------------------------------------------------
-- 9. SEC FILINGS - Official SEC documents
-- ----------------------------------------------------------------------------
CREATE TABLE sec_filings (
    filing_id BIGSERIAL PRIMARY KEY,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    accession_number VARCHAR(20) UNIQUE NOT NULL,
    form_type VARCHAR(10) NOT NULL,
    filing_date DATE NOT NULL,
    period_end_date DATE,
    filing_url TEXT,
    document_text TEXT,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sec_filings_ticker ON sec_filings(ticker_id, filing_date DESC);
CREATE INDEX idx_sec_filings_form_type ON sec_filings(form_type, filing_date DESC);
CREATE INDEX idx_sec_filings_accession ON sec_filings(accession_number);

-- ----------------------------------------------------------------------------
-- 10. SEC FILING SENTIMENT - Sentiment analysis of filing sections
-- ----------------------------------------------------------------------------
CREATE TABLE sec_filing_sentiment (
    sentiment_id BIGSERIAL PRIMARY KEY,
    filing_id BIGINT REFERENCES sec_filings(filing_id) ON DELETE CASCADE,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    section VARCHAR(100),
    sentiment_label VARCHAR(20),
    sentiment_score DECIMAL(5,4),
    positive_score DECIMAL(5,4),
    negative_score DECIMAL(5,4),
    neutral_score DECIMAL(5,4),
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_id, section),
    CONSTRAINT check_sentiment_score CHECK (sentiment_score >= -1 AND sentiment_score <= 1)
);

CREATE INDEX idx_sec_filing_sentiment_filing ON sec_filing_sentiment(filing_id);
CREATE INDEX idx_sec_filing_sentiment_ticker ON sec_filing_sentiment(ticker_id);

-- ----------------------------------------------------------------------------
-- 11. EVENT TYPES - Lookup table for event categories
-- ----------------------------------------------------------------------------
CREATE TABLE event_types (
    event_type_id SERIAL PRIMARY KEY,
    event_type_name VARCHAR(50) UNIQUE NOT NULL,
    source_category VARCHAR(50),
    description TEXT
);

-- Pre-populate common event types
INSERT INTO event_types (event_type_name, source_category, description) VALUES
-- ('reddit_sentiment_spike', 'social', 'Abnormal spike in Reddit sentiment'),
('reddit_volume_surge', 'social', 'High volume of Reddit mentions'),
('news_cluster', 'news', 'Multiple news articles in short timeframe'),
('earnings_report', 'financial', 'Quarterly earnings announcement (10-Q)'),
('annual_report', 'financial', 'Annual report filing (10-K)'),
('material_event', 'financial', 'Material event filing (8-K)'),
('sec_filing', 'regulatory', 'General SEC filing');

-- ----------------------------------------------------------------------------
-- 12. EVENTS - Unified event detection across all sources
-- ----------------------------------------------------------------------------
CREATE TABLE events (
    event_id BIGSERIAL PRIMARY KEY,
    ticker_id INTEGER REFERENCES tickers(ticker_id) ON DELETE CASCADE,
    event_type_id INTEGER REFERENCES event_types(event_type_id),
    event_timestamp TIMESTAMP NOT NULL,
    magnitude DECIMAL(10,4),
    direction VARCHAR(20),
    confidence DECIMAL(4,3),
    source_id BIGINT,
    source_table VARCHAR(50),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_ticker_time ON events(ticker_id, event_timestamp DESC);
CREATE INDEX idx_events_type ON events(event_type_id, event_timestamp DESC);
CREATE INDEX idx_events_timestamp ON events(event_timestamp DESC);

-- ----------------------------------------------------------------------------
-- UTILITY FUNCTIONS
-- ----------------------------------------------------------------------------

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tickers table
CREATE TRIGGER update_tickers_updated_at 
    BEFORE UPDATE ON tickers
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- ----------------------------------------------------------------------------
-- VERIFICATION QUERIES
-- ----------------------------------------------------------------------------

-- Check all tables were created
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

-- Check all indexes
SELECT indexname, tablename 
FROM pg_indexes 
WHERE schemaname = 'public' 
ORDER BY tablename, indexname;