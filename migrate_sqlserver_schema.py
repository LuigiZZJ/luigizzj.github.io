#!/usr/bin/env python3
"""
SQL Server Schema Migration Script
Migrates all objects and data from one schema to another
"""

import pymssql
import sys
import argparse
from datetime import datetime

class SQLServerMigrator:
    def __init__(self, source_config, target_config, schema_name):
        self.source_config = source_config
        self.target_config = target_config
        self.schema_name = schema_name
        self.source_conn = None
        self.target_conn = None

    def connect_source(self):
        """Connect to source SQL Server"""
        print(f"Connecting to source server {self.source_config['server']}...")
        try:
            self.source_conn = pymssql.connect(
                server=self.source_config['server'],
                user=self.source_config['user'],
                password=self.source_config['password'],
                database=self.source_config['database']
            )
            print("✓ Source connection established")
            return True
        except Exception as e:
            print(f"✗ Failed to connect to source: {e}")
            return False

    def connect_target(self):
        """Connect to target SQL Server"""
        print(f"Connecting to target server {self.target_config['server']}...")
        try:
            self.target_conn = pymssql.connect(
                server=self.target_config['server'],
                user=self.target_config['user'],
                password=self.target_config['password'],
                database=self.target_config['database']
            )
            print("✓ Target connection established")
            return True
        except Exception as e:
            print(f"✗ Failed to connect to target: {e}")
            return False

    def create_schema_if_not_exists(self):
        """Create schema in target database if it doesn't exist"""
        print(f"\nChecking if schema '{self.schema_name}' exists in target...")
        cursor = self.target_conn.cursor()

        # Check if schema exists
        cursor.execute("""
            SELECT SCHEMA_NAME
            FROM INFORMATION_SCHEMA.SCHEMATA
            WHERE SCHEMA_NAME = %s
        """, (self.schema_name,))

        if cursor.fetchone():
            print(f"✓ Schema '{self.schema_name}' already exists")
        else:
            print(f"Creating schema '{self.schema_name}'...")
            cursor.execute(f"CREATE SCHEMA [{self.schema_name}]")
            self.target_conn.commit()
            print(f"✓ Schema '{self.schema_name}' created")

        cursor.close()

    def get_tables(self):
        """Get list of tables in the schema"""
        print(f"\nFetching tables from schema '{self.schema_name}'...")
        cursor = self.source_conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """, (self.schema_name,))

        tables = [row[0] for row in cursor.fetchall()]
        print(f"✓ Found {len(tables)} tables")
        cursor.close()
        return tables

    def get_table_create_script(self, table_name):
        """Generate CREATE TABLE script"""
        cursor = self.source_conn.cursor()

        # Get columns
        cursor.execute("""
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                IS_NULLABLE,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (self.schema_name, table_name))

        columns = cursor.fetchall()

        # Build CREATE TABLE statement
        col_definitions = []
        for col in columns:
            col_name, data_type, char_len, num_prec, num_scale, is_null, col_default = col

            # Build data type
            if data_type in ('varchar', 'nvarchar', 'char', 'nchar'):
                if char_len == -1:
                    dtype = f"{data_type}(MAX)"
                else:
                    dtype = f"{data_type}({char_len})"
            elif data_type in ('decimal', 'numeric'):
                dtype = f"{data_type}({num_prec},{num_scale})"
            else:
                dtype = data_type

            # Build column definition
            col_def = f"[{col_name}] {dtype}"

            # Add NULL/NOT NULL
            if is_null == 'NO':
                col_def += " NOT NULL"

            # Add DEFAULT (if exists)
            if col_default:
                col_def += f" DEFAULT {col_default}"

            col_definitions.append(col_def)

        create_script = f"CREATE TABLE [{self.schema_name}].[{table_name}] (\n  "
        create_script += ",\n  ".join(col_definitions)
        create_script += "\n)"

        cursor.close()
        return create_script

    def get_primary_keys(self, table_name):
        """Get primary key constraints"""
        cursor = self.source_conn.cursor()

        cursor.execute("""
            SELECT
                kcu.COLUMN_NAME,
                tc.CONSTRAINT_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                AND tc.TABLE_NAME = kcu.TABLE_NAME
            WHERE tc.TABLE_SCHEMA = %s
                AND tc.TABLE_NAME = %s
                AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ORDER BY kcu.ORDINAL_POSITION
        """, (self.schema_name, table_name))

        pk_columns = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return pk_columns

    def drop_table_if_exists(self, table_name):
        """Drop table if exists in target"""
        cursor = self.target_conn.cursor()
        cursor.execute(f"IF OBJECT_ID('[{self.schema_name}].[{table_name}]', 'U') IS NOT NULL DROP TABLE [{self.schema_name}].[{table_name}]")
        self.target_conn.commit()
        cursor.close()

    def create_table(self, table_name):
        """Create table in target database"""
        print(f"  Creating table [{self.schema_name}].[{table_name}]...")

        # Drop if exists
        self.drop_table_if_exists(table_name)

        # Get CREATE script
        create_script = self.get_table_create_script(table_name)

        # Execute CREATE
        cursor = self.target_conn.cursor()
        cursor.execute(create_script)

        # Add PRIMARY KEY if exists
        pk_columns = self.get_primary_keys(table_name)
        if pk_columns:
            pk_script = f"ALTER TABLE [{self.schema_name}].[{table_name}] ADD PRIMARY KEY ({','.join(['[' + c + ']' for c in pk_columns])})"
            cursor.execute(pk_script)

        self.target_conn.commit()
        cursor.close()
        print(f"  ✓ Table created")

    def copy_table_data(self, table_name, batch_size=1000):
        """Copy data from source to target"""
        print(f"  Copying data for [{self.schema_name}].[{table_name}]...")

        # Get data from source
        source_cursor = self.source_conn.cursor()
        source_cursor.execute(f"SELECT * FROM [{self.schema_name}].[{table_name}]")

        # Get column names
        columns = [desc[0] for desc in source_cursor.description]
        col_list = ','.join([f'[{c}]' for c in columns])
        placeholders = ','.join(['%s'] * len(columns))

        # Insert into target
        target_cursor = self.target_conn.cursor()
        insert_sql = f"INSERT INTO [{self.schema_name}].[{table_name}] ({col_list}) VALUES ({placeholders})"

        # Fetch and insert in batches
        total_rows = 0
        while True:
            rows = source_cursor.fetchmany(batch_size)
            if not rows:
                break

            target_cursor.executemany(insert_sql, rows)
            self.target_conn.commit()
            total_rows += len(rows)

        source_cursor.close()
        target_cursor.close()

        print(f"  ✓ Copied {total_rows} rows")
        return total_rows

    def get_views(self):
        """Get list of views in the schema"""
        print(f"\nFetching views from schema '{self.schema_name}'...")
        cursor = self.source_conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
        """, (self.schema_name,))

        views = [row[0] for row in cursor.fetchall()]
        print(f"✓ Found {len(views)} views")
        cursor.close()
        return views

    def get_view_definition(self, view_name):
        """Get view definition"""
        cursor = self.source_conn.cursor()

        cursor.execute("""
            SELECT VIEW_DEFINITION
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """, (self.schema_name, view_name))

        result = cursor.fetchone()
        cursor.close()

        if result:
            return result[0]
        return None

    def create_view(self, view_name):
        """Create view in target database"""
        print(f"  Creating view [{self.schema_name}].[{view_name}]...")

        view_def = self.get_view_definition(view_name)
        if not view_def:
            print(f"  ✗ Could not get view definition")
            return

        # Drop if exists
        cursor = self.target_conn.cursor()
        cursor.execute(f"IF OBJECT_ID('[{self.schema_name}].[{view_name}]', 'V') IS NOT NULL DROP VIEW [{self.schema_name}].[{view_name}]")

        # Create view
        create_script = f"CREATE VIEW [{self.schema_name}].[{view_name}] AS {view_def}"
        cursor.execute(create_script)

        self.target_conn.commit()
        cursor.close()
        print(f"  ✓ View created")

    def get_stored_procedures(self):
        """Get list of stored procedures in the schema"""
        print(f"\nFetching stored procedures from schema '{self.schema_name}'...")
        cursor = self.source_conn.cursor()

        cursor.execute("""
            SELECT ROUTINE_NAME
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'PROCEDURE'
            ORDER BY ROUTINE_NAME
        """, (self.schema_name,))

        procs = [row[0] for row in cursor.fetchall()]
        print(f"✓ Found {len(procs)} stored procedures")
        cursor.close()
        return procs

    def get_procedure_definition(self, proc_name):
        """Get stored procedure definition"""
        cursor = self.source_conn.cursor()

        cursor.execute("""
            SELECT ROUTINE_DEFINITION
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_SCHEMA = %s AND ROUTINE_NAME = %s
        """, (self.schema_name, proc_name))

        result = cursor.fetchone()
        cursor.close()

        if result:
            return result[0]
        return None

    def create_stored_procedure(self, proc_name):
        """Create stored procedure in target database"""
        print(f"  Creating procedure [{self.schema_name}].[{proc_name}]...")

        proc_def = self.get_procedure_definition(proc_name)
        if not proc_def:
            print(f"  ✗ Could not get procedure definition")
            return

        # Drop if exists
        cursor = self.target_conn.cursor()
        cursor.execute(f"IF OBJECT_ID('[{self.schema_name}].[{proc_name}]', 'P') IS NOT NULL DROP PROCEDURE [{self.schema_name}].[{proc_name}]")

        # Create procedure
        create_script = f"CREATE PROCEDURE [{self.schema_name}].[{proc_name}] AS {proc_def}"
        cursor.execute(create_script)

        self.target_conn.commit()
        cursor.close()
        print(f"  ✓ Procedure created")

    def migrate(self):
        """Execute full migration"""
        print("="*60)
        print(f"SQL Server Schema Migration")
        print(f"Schema: {self.schema_name}")
        print(f"Source: {self.source_config['server']}/{self.source_config['database']}")
        print(f"Target: {self.target_config['server']}/{self.target_config['database']}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)

        # Connect to servers
        if not self.connect_source():
            return False
        if not self.connect_target():
            return False

        try:
            # Create schema
            self.create_schema_if_not_exists()

            # Migrate tables
            print("\n" + "="*60)
            print("MIGRATING TABLES")
            print("="*60)
            tables = self.get_tables()
            for i, table in enumerate(tables, 1):
                print(f"\n[{i}/{len(tables)}] {table}")
                self.create_table(table)
                self.copy_table_data(table)

            # Migrate views
            print("\n" + "="*60)
            print("MIGRATING VIEWS")
            print("="*60)
            views = self.get_views()
            for i, view in enumerate(views, 1):
                print(f"\n[{i}/{len(views)}] {view}")
                try:
                    self.create_view(view)
                except Exception as e:
                    print(f"  ✗ Error creating view: {e}")

            # Migrate stored procedures
            print("\n" + "="*60)
            print("MIGRATING STORED PROCEDURES")
            print("="*60)
            procs = self.get_stored_procedures()
            for i, proc in enumerate(procs, 1):
                print(f"\n[{i}/{len(procs)}] {proc}")
                try:
                    self.create_stored_procedure(proc)
                except Exception as e:
                    print(f"  ✗ Error creating procedure: {e}")

            print("\n" + "="*60)
            print(f"✓ MIGRATION COMPLETED SUCCESSFULLY")
            print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*60)

            return True

        except Exception as e:
            print(f"\n✗ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            # Close connections
            if self.source_conn:
                self.source_conn.close()
            if self.target_conn:
                self.target_conn.close()


def main():
    parser = argparse.ArgumentParser(description='Migrate SQL Server schema')

    # Source connection
    parser.add_argument('--source-server', required=True, help='Source server address')
    parser.add_argument('--source-user', required=True, help='Source username')
    parser.add_argument('--source-password', required=True, help='Source password')
    parser.add_argument('--source-database', required=True, help='Source database name')

    # Target connection
    parser.add_argument('--target-server', required=True, help='Target server address')
    parser.add_argument('--target-user', required=True, help='Target username')
    parser.add_argument('--target-password', required=True, help='Target password')
    parser.add_argument('--target-database', required=True, help='Target database name')

    # Schema to migrate
    parser.add_argument('--schema', required=True, help='Schema name to migrate')

    args = parser.parse_args()

    source_config = {
        'server': args.source_server,
        'user': args.source_user,
        'password': args.source_password,
        'database': args.source_database
    }

    target_config = {
        'server': args.target_server,
        'user': args.target_user,
        'password': args.target_password,
        'database': args.target_database
    }

    migrator = SQLServerMigrator(source_config, target_config, args.schema)
    success = migrator.migrate()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
