"""
Apply a SQL migration file to the database.
Usage: python apply_migration.py <migration_file.sql>
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from db.db_setup import engine
from sqlalchemy import text

def apply_migration(sql_file_path):
    """Apply a SQL migration file to the database."""
    # Read the SQL file
    with open(sql_file_path, 'r') as f:
        sql = f.read()
    
    # Execute the SQL
    with engine.connect() as conn:
        # Split by semicolons and execute each statement
        statements = [s.strip() for s in sql.split(';') if s.strip()]
        
        for statement in statements:
            print(f"Executing: {statement[:100]}...")
            conn.execute(text(statement))
            conn.commit()
    
    print(f"✅ Migration applied successfully: {sql_file_path}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python apply_migration.py <migration_file.sql>")
        sys.exit(1)
    
    sql_file = sys.argv[1]
    
    if not os.path.exists(sql_file):
        print(f"Error: File not found: {sql_file}")
        sys.exit(1)
    
    apply_migration(sql_file)
