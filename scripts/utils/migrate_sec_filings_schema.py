"""
Migration script to add missing columns to sec_filings table
"""
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

db_params = {
    'dbname': os.getenv('DB_NAME', 'stock_events'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

try:
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()
    
    # Check which columns already exist
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='sec_filings'
    """)
    
    existing_cols = {row[0] for row in cursor.fetchall()}
    print(f"Existing columns in sec_filings: {existing_cols}")
    
    # Add missing columns
    migration_sql = []
    
    if 'acceptance_datetime' not in existing_cols:
        migration_sql.append("ALTER TABLE sec_filings ADD COLUMN acceptance_datetime TIMESTAMP;")
        print("✓ Will add: acceptance_datetime")
    
    if 'primary_document' not in existing_cols:
        migration_sql.append("ALTER TABLE sec_filings ADD COLUMN primary_document VARCHAR(255);")
        print("✓ Will add: primary_document")
    
    if 'primary_doc_description' not in existing_cols:
        migration_sql.append("ALTER TABLE sec_filings ADD COLUMN primary_doc_description TEXT;")
        print("✓ Will add: primary_doc_description")
    
    if 'form_category' not in existing_cols:
        migration_sql.append("ALTER TABLE sec_filings ADD COLUMN form_category VARCHAR(100);")
        print("✓ Will add: form_category")
    
    if 'items_parsed' not in existing_cols:
        migration_sql.append("ALTER TABLE sec_filings ADD COLUMN items_parsed VARCHAR(255);")
        print("✓ Will add: items_parsed")
    
    # Add index on form_category if it doesn't exist
    cursor.execute("""
        SELECT indexname 
        FROM pg_indexes 
        WHERE tablename = 'sec_filings' AND indexname = 'idx_sec_filings_form_category'
    """)
    
    if not cursor.fetchone():
        migration_sql.append("CREATE INDEX idx_sec_filings_form_category ON sec_filings(form_category);")
        print("✓ Will add: index on form_category")
    
    # Execute migrations
    if migration_sql:
        print(f"\nExecuting {len(migration_sql)} migration(s)...")
        for sql in migration_sql:
            print(f"  - {sql[:60]}...")
            cursor.execute(sql)
        
        conn.commit()
        print("\n✓ Migration completed successfully!")
    else:
        print("\n✓ Database schema is already up-to-date.")
    
    cursor.close()
    conn.close()

except Exception as e:
    print(f"✗ Migration failed: {e}")
    raise
