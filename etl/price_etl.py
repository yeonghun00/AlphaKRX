#!/usr/bin/env python3
"""
Clean ETL Pipeline for KRX Stock Data
Direct Normalization: API → Transform → Load (No Raw Storage)
"""

import sqlite3
import logging
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set

logger = logging.getLogger(__name__)

class CleanETLPipeline:
    """Clean ETL pipeline with direct normalization."""

    def __init__(self, db_path: str = "data/krx_stock_data.db"):
        """
        Initialize clean ETL pipeline.

        Args:
            db_path (str): Path to SQLite database file
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._conn = None
        self._create_normalized_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a database connection (connection pooling)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _create_normalized_tables(self):
        """Create clean normalized tables only."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Stocks table (current metadata)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stocks (
                    stock_code TEXT PRIMARY KEY,
                    current_name TEXT NOT NULL,
                    current_market_type TEXT,
                    current_sector_type TEXT,
                    shares_outstanding INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Stock history table (tracks changes over time)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
                    effective_date TEXT NOT NULL,
                    name TEXT,
                    market_type TEXT,
                    sector_type TEXT,
                    shares_outstanding INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, effective_date)
                )
            ''')
            
            # Daily prices table (normalized price data)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_prices (
                    stock_code TEXT NOT NULL REFERENCES stocks(stock_code),
                    date TEXT NOT NULL,
                    closing_price INTEGER,
                    change INTEGER,
                    change_rate REAL,
                    opening_price INTEGER,
                    high_price INTEGER,
                    low_price INTEGER,
                    volume INTEGER,
                    value INTEGER,
                    market_cap INTEGER,
                    market_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stock_code, date)
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_history_date ON stock_history(effective_date)')
            
            # Add performance indexes for better query performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_date_market ON daily_prices(date, market_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_stock_date ON daily_prices(stock_code, date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_market ON daily_prices(market_type)')
            
            conn.commit()
            self.logger.info("Clean normalized tables created successfully")
    
    def process_data(self, raw_data: List[Dict]) -> Dict[str, int]:
        """
        Process raw API data directly to normalized tables.

        Args:
            raw_data (List[Dict]): Raw API response data

        Returns:
            Dict: Processing statistics
        """
        if not raw_data:
            return {'stocks_processed': 0, 'prices_processed': 0}

        self.logger.info(f"Processing {len(raw_data)} records")

        conn = self._get_connection()
        cursor = conn.cursor()

        # Step 1: Extract and normalize stock metadata
        stock_updates = self._extract_stocks(raw_data)
        stocks_processed = self._upsert_stocks(cursor, stock_updates)

        # Step 2: Track historical changes
        self._insert_stock_history(cursor, stock_updates)

        # Step 3: Extract and normalize price data
        price_records = self._extract_prices(raw_data)
        prices_processed = self._insert_prices(cursor, price_records)

        conn.commit()

        self.logger.info(f"Processed: {stocks_processed} stocks, {prices_processed} prices")
        return {
            'stocks_processed': stocks_processed,
            'prices_processed': prices_processed
        }
    
    def _extract_stocks(self, raw_data: List[Dict]) -> List[Dict]:
        """Extract unique stock metadata from raw data."""
        # Collect all unique stock codes first
        stock_codes = {record.get('ISU_CD') for record in raw_data if record.get('ISU_CD')}

        # Batch fetch existing metadata for all stocks
        existing_metadata = self._get_stocks_metadata_batch(stock_codes)

        stock_metadata = {}
        for record in raw_data:
            stock_code = record.get('ISU_CD')
            if not stock_code:
                continue

            # Get current metadata from batch result
            current_meta = existing_metadata.get(stock_code, {})

            # New metadata from this record
            new_meta = {
                'name': record.get('ISU_NM'),
                'market_type': record.get('MKT_NM'),
                'sector_type': record.get('SECT_TP_NM'),
                'shares_outstanding': record.get('LIST_SHRS')
            }

            # Only update if metadata has changed
            if current_meta != new_meta:
                stock_metadata[stock_code] = {
                    'stock_code': stock_code,
                    'name': new_meta['name'],
                    'market_type': new_meta['market_type'],
                    'sector_type': new_meta['sector_type'],
                    'shares_outstanding': new_meta['shares_outstanding'],
                    'effective_date': record.get('BAS_DD')
                }

        return list(stock_metadata.values())

    def _get_stocks_metadata_batch(self, stock_codes: Set[str]) -> Dict[str, Dict]:
        """
        Batch fetch metadata for multiple stocks in a single query.

        Args:
            stock_codes (Set[str]): Set of stock codes to fetch

        Returns:
            Dict[str, Dict]: Dictionary mapping stock_code to metadata
        """
        if not stock_codes:
            return {}

        conn = self._get_connection()
        cursor = conn.cursor()

        # Build query with placeholders for all stock codes
        placeholders = ','.join('?' * len(stock_codes))
        cursor.execute(f'''
            SELECT stock_code, current_name, current_market_type, current_sector_type, shares_outstanding
            FROM stocks WHERE stock_code IN ({placeholders})
        ''', list(stock_codes))

        results = {}
        for row in cursor.fetchall():
            results[row[0]] = {
                'name': row[1],
                'market_type': row[2],
                'sector_type': row[3],
                'shares_outstanding': row[4]
            }
        return results
    
    def _upsert_stocks(self, cursor, stock_updates: List[Dict]) -> int:
        """Update or insert stock metadata."""
        if not stock_updates:
            return 0
        
        for stock in stock_updates:
            cursor.execute('''
                INSERT OR REPLACE INTO stocks 
                (stock_code, current_name, current_market_type, current_sector_type, shares_outstanding, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (stock['stock_code'], stock['name'], stock['market_type'], 
                  stock['sector_type'], stock['shares_outstanding']))
        
        return len(stock_updates)
    
    def _insert_stock_history(self, cursor, stock_updates: List[Dict]):
        """Insert a stock_history row only when metadata has actually changed."""
        if not stock_updates:
            return

        for stock in stock_updates:
            # Fetch the most recent recorded values for this stock
            cursor.execute('''
                SELECT name, market_type, sector_type, shares_outstanding
                FROM stock_history
                WHERE stock_code = ?
                ORDER BY effective_date DESC
                LIMIT 1
            ''', (stock['stock_code'],))
            last = cursor.fetchone()

            # Only insert if this is the first record or something changed
            if last is None or last != (
                stock['name'], stock['market_type'],
                stock['sector_type'], stock['shares_outstanding']
            ):
                cursor.execute('''
                    INSERT OR IGNORE INTO stock_history
                    (stock_code, effective_date, name, market_type, sector_type, shares_outstanding)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (stock['stock_code'], stock['effective_date'], stock['name'],
                      stock['market_type'], stock['sector_type'], stock['shares_outstanding']))
    
    def _extract_prices(self, raw_data: List[Dict]) -> List[Dict]:
        """Extract price data for normalized insertion."""
        return [{
            'stock_code': record['ISU_CD'],
            'date': record['BAS_DD'],
            'closing_price': record.get('TDD_CLSPRC'),
            'change': record.get('CMPPREVDD_PRC'),
            'change_rate': record.get('FLUC_RT'),
            'opening_price': record.get('TDD_OPNPRC'),
            'high_price': record.get('TDD_HGPRC'),
            'low_price': record.get('TDD_LWPRC'),
            'volume': record.get('ACC_TRDVOL'),
            'value': record.get('ACC_TRDVAL'),
            'market_cap': record.get('MKTCAP'),
            'market_type': record.get('market_type', 'kospi')
        } for record in raw_data if record.get('ISU_CD') and record.get('BAS_DD')]
    
    def _insert_prices(self, cursor, price_records: List[Dict]) -> int:
        """Insert normalized price data."""
        if not price_records:
            return 0
        
        cursor.executemany('''
            INSERT OR REPLACE INTO daily_prices 
            (stock_code, date, closing_price, change, change_rate, opening_price, 
             high_price, low_price, volume, value, market_cap, market_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [(r['stock_code'], r['date'], r['closing_price'], r['change'], 
               r['change_rate'], r['opening_price'], r['high_price'], r['low_price'],
               r['volume'], r['value'], r['market_cap'], r['market_type']) for r in price_records])
        
        return len(price_records)
    
    def get_status(self) -> Dict:
        """Get clean status of normalized data."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM stocks')
        stock_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM daily_prices')
        price_count = cursor.fetchone()[0]

        cursor.execute('SELECT MIN(date), MAX(date) FROM daily_prices')
        date_range = cursor.fetchone()

        return {
            'stocks': stock_count,
            'daily_prices': price_count,
            'date_range': date_range,
            'total_records': stock_count + price_count
        }

    def validate_data(self) -> Dict:
        """Validate normalized data integrity."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Check referential integrity
        cursor.execute('''
            SELECT COUNT(*) FROM daily_prices dp
            LEFT JOIN stocks s ON dp.stock_code = s.stock_code
            WHERE s.stock_code IS NULL
        ''')
        orphaned_prices = cursor.fetchone()[0]

        # Check for duplicate prices
        cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT stock_code, date, COUNT(*) as cnt
                FROM daily_prices
                GROUP BY stock_code, date
                HAVING cnt > 1
            )
        ''')
        duplicate_prices = cursor.fetchone()[0]

        return {
            'orphaned_prices': orphaned_prices,
            'duplicate_prices': duplicate_prices,
            'validation_passed': orphaned_prices == 0 and duplicate_prices == 0
        }

    def check_date_exists(self, date: str) -> bool:
        """
        Check if data already exists for a specific date.

        Args:
            date (str): Date in YYYYMMDD format

        Returns:
            bool: True if data exists for the date, False otherwise
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM daily_prices WHERE date = ?
        ''', (date,))
        count = cursor.fetchone()[0]
        return count > 0

    def get_existing_dates(self, start_date: str, end_date: str) -> set:
        """
        Get all dates that already have data in the specified range.

        Args:
            start_date (str): Start date in YYYYMMDD format
            end_date (str): End date in YYYYMMDD format

        Returns:
            set: Set of dates (as strings) that already have data
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT date FROM daily_prices
            WHERE date >= ? AND date <= ?
            ORDER BY date
        ''', (start_date, end_date))
        existing_dates = {row[0] for row in cursor.fetchall()}
        return existing_dates

    def should_process_date(self, date: str, force: bool = False) -> bool:
        """
        Determine if a date should be processed based on existing data.
        
        Args:
            date (str): Date in YYYYMMDD format
            force (bool): Whether to force processing regardless of existing data
            
        Returns:
            bool: True if the date should be processed, False otherwise
        """
        if force:
            return True
        
        return not self.check_date_exists(date)
    
    def cleanup_old_data(self, days_to_keep: int = 365):
        """
        Clean up old price data to manage storage.
        
        Args:
            days_to_keep (int): Number of days to keep data
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Delete old price data
            cursor.execute('''
                DELETE FROM daily_prices 
                WHERE date < date('now', '-{} days')
            '''.format(days_to_keep))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            self.logger.info(f"Cleaned up {deleted_count} old price records")
    
    def save_progress(self, progress_data: Dict):
        """
        Save progress to a JSON file for resume capability.
        
        Args:
            progress_data (Dict): Progress information to save
        """
        progress_file = f"{self.db_path}.progress.json"
        try:
            with open(progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
            self.logger.info(f"Progress saved to {progress_file}")
        except Exception as e:
            self.logger.error(f"Failed to save progress: {e}")
    
    def load_progress(self) -> Optional[Dict]:
        """
        Load progress from a JSON file for resume capability.
        
        Returns:
            Optional[Dict]: Progress information if exists, None otherwise
        """
        progress_file = f"{self.db_path}.progress.json"
        try:
            if os.path.exists(progress_file):
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                self.logger.info(f"Progress loaded from {progress_file}")
                return progress_data
        except Exception as e:
            self.logger.error(f"Failed to load progress: {e}")
        return None
    
    def get_backfill_progress(self, start_date: str, end_date: str) -> Dict:
        """
        Get detailed backfill progress information.
        
        Args:
            start_date (str): Start date in YYYYMMDD format
            end_date (str): End date in YYYYMMDD format
            
        Returns:
            Dict: Progress information including processed dates, remaining dates, etc.
        """
        from datetime import datetime, timedelta
        
        # Calculate all trading dates in range
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        
        all_dates = set()
        current_date = start_dt
        while current_date <= end_dt:
            if current_date.weekday() < 5:  # Monday = 0, Sunday = 6
                all_dates.add(current_date.strftime('%Y%m%d'))
            current_date += timedelta(days=1)
        
        # Get existing dates
        existing_dates = self.get_existing_dates(start_date, end_date)
        
        # Calculate progress
        processed_dates = existing_dates.intersection(all_dates)
        remaining_dates = all_dates - existing_dates
        
        return {
            'start_date': start_date,
            'end_date': end_date,
            'total_trading_days': len(all_dates),
            'processed_dates': len(processed_dates),
            'remaining_dates': len(remaining_dates),
            'progress_percentage': (len(processed_dates) / len(all_dates)) * 100 if all_dates else 0,
            'processed_dates_list': sorted(list(processed_dates)),
            'remaining_dates_list': sorted(list(remaining_dates)),
            'last_processed_date': max(processed_dates) if processed_dates else None
        }
    
    def optimize_database(self):
        """Optimize database performance by rebuilding indexes and vacuuming."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Rebuild indexes
            cursor.execute('REINDEX idx_daily_prices_date')
            cursor.execute('REINDEX idx_stock_history_date')
            
            # Vacuum database to reclaim space and optimize performance
            cursor.execute('VACUUM')
            
            conn.commit()
            self.logger.info("Database optimization completed")
    
    def add_performance_indexes(self):
        """Add additional performance indexes for better query performance."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Add composite index for date-based queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_date_market ON daily_prices(date, market_type)')
            
            # Add index for stock-based queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_stock_date ON daily_prices(stock_code, date)')
            
            # Add index for market-based queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_market ON daily_prices(market_type)')
            
            conn.commit()
            self.logger.info("Performance indexes added")


def main():
    """Main function to handle command-line interface."""
    import argparse
    import sys
    from datetime import datetime, timedelta
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description='Clean ETL Pipeline for KRX Stock Data')
    parser.add_argument('--create-schema', action='store_true', help='Create normalized database schema')
    parser.add_argument('--backfill', action='store_true', help='Run historical backfill')
    parser.add_argument('--start-date', type=str, help='Start date for backfill (YYYYMMDD)')
    parser.add_argument('--end-date', type=str, help='End date for backfill (YYYYMMDD)')
    parser.add_argument('--force', action='store_true', help='Force processing even if data already exists')
    parser.add_argument('--daily-update', action='store_true', help='Run daily update')
    parser.add_argument('--date', type=str, help='Specific date for daily update (YYYYMMDD)')
    parser.add_argument('--markets', type=str, default='kospi', help='Comma-separated list of markets to fetch (kospi,kosdaq,kodex)')
    parser.add_argument('--db-path', type=str, default='data/krx_stock_data.db', help='Database path')
    
    args = parser.parse_args()
    
    # Initialize pipeline
    pipeline = CleanETLPipeline(args.db_path)
    
    if args.create_schema:
        logger.info("Schema already created during initialization")
        return

    if args.backfill:
        if not args.start_date or not args.end_date:
            logger.error("--start-date and --end-date are required for backfill")
            sys.exit(1)

        # Parse markets argument
        markets = [m.strip() for m in args.markets.split(',')]
        valid_markets = ['kospi', 'kosdaq', 'kodex']
        markets = [m for m in markets if m in valid_markets]

        if not markets:
            logger.error("No valid markets specified. Use: kospi,kosdaq,kodex")
            sys.exit(1)

        logger.info("Starting backfill from %s to %s", args.start_date, args.end_date)
        logger.info("Fetching data for markets: %s", ', '.join(markets))
        if args.force:
            logger.info("Force flag enabled - will process all dates regardless of existing data")
        
        # Import KRX API and config
        from krx_api import KRXAPI
        from config import load_config
        
        config_dict = load_config()
        api = KRXAPI(config_dict['api']['auth_key'], config_dict.get('api', {}))
        
        # Check for resume capability
        progress_data = pipeline.load_progress()
        if progress_data and not args.force:
            logger.info("Found existing progress: %.1f%% complete", progress_data.get('progress_percentage', 0))
            resume = input("Resume from last processed date? (y/n): ").lower().strip()
            if resume == 'y':
                start_date_str = progress_data.get('last_processed_date')
                if start_date_str:
                    logger.info("Resuming from %s", start_date_str)
                    # Adjust start date to continue from next trading day
                    from datetime import timedelta
                    resume_date = datetime.strptime(start_date_str, '%Y%m%d') + timedelta(days=1)
                    args.start_date = resume_date.strftime('%Y%m%d')
                    logger.info("Adjusted start date to: %s", args.start_date)

        # Generate date range
        start_date = datetime.strptime(args.start_date, '%Y%m%d')
        end_date = datetime.strptime(args.end_date, '%Y%m%d')

        # Get progress information
        progress = pipeline.get_backfill_progress(args.start_date, args.end_date)
        logger.info("Total trading days to process: %s", progress['total_trading_days'])
        logger.info("Already processed: %s", progress['processed_dates'])
        logger.info("Remaining: %s", progress['remaining_dates'])
        logger.info("Progress: %.1f%%", progress['progress_percentage'])

        # Use parallel processing for better performance
        logger.info("Using optimized parallel processing...")
        
        try:
            # Determine which dates to process based on force flag
            if args.force:
                # When force is used, process all trading dates
                logger.info("Force flag enabled - will process all dates regardless of existing data")
                dates_to_process = progress['remaining_dates_list'] + progress['processed_dates_list']
                dates_to_process.sort()
            else:
                # When force is not used, only process dates without existing data
                dates_to_process = progress['remaining_dates_list']
                if not dates_to_process:
                    logger.info("All dates already processed. Use --force to reprocess existing data.")
                    return

            logger.info("Processing %d dates...", len(dates_to_process))
            
            processed_dates = 0
            total_records = 0
            
            # Process dates one by one to respect force flag logic
            for date_str in dates_to_process:
                try:
                    # Fetch data for this specific date only
                    market_data = api.fetch_data_for_date_parallel(date_str, markets, is_backfill=True)
                    
                    if market_data:
                        # Combine data from all markets for this date
                        raw_data = []
                        for market, records in market_data.items():
                            raw_data.extend(records)
                        
                        if raw_data:
                            # Process and store data (INSERT OR REPLACE will overwrite existing data)
                            result = pipeline.process_data(raw_data)
                            total_records += result['prices_processed']
                            processed_dates += 1
                            
                            logger.info("Processed %d records for %s", result['prices_processed'], date_str)

                            # Save progress periodically
                            if processed_dates % 10 == 0:  # Save every 10 dates
                                progress_info = {
                                    'start_date': args.start_date,
                                    'end_date': args.end_date,
                                    'last_processed_date': date_str,
                                    'processed_dates': processed_dates,
                                    'total_records': total_records,
                                    'markets': markets
                                }
                                pipeline.save_progress(progress_info)
                    else:
                        logger.warning("No data available for %s", date_str)

                except Exception as e:
                    logger.error("Error processing %s: %s", date_str, e)
                    # Save progress on error for resume capability
                    error_progress = {
                        'start_date': args.start_date,
                        'end_date': args.end_date,
                        'last_processed_date': date_str,
                        'processed_dates': processed_dates,
                        'total_records': total_records,
                        'markets': markets,
                        'error': str(e)
                    }
                    pipeline.save_progress(error_progress)
            
            logger.info("Backfill completed. Processed %d dates with %d total records.", processed_dates, total_records)

            # Final progress update
            final_progress = pipeline.get_backfill_progress(args.start_date, args.end_date)
            logger.info("Final progress: %.1f%%", final_progress['progress_percentage'])

            # Clean up progress file if completed
            if final_progress['remaining_dates'] == 0:
                progress_file = f"{args.db_path}.progress.json"
                if os.path.exists(progress_file):
                    os.remove(progress_file)
                    logger.info("Backfill completed - progress file cleaned up")

        except Exception as e:
            logger.error("Error during backfill: %s", e)
            # Save progress on error for resume capability
            error_progress = {
                'start_date': args.start_date,
                'end_date': args.end_date,
                'last_processed_date': date_str if 'date_str' in locals() else None,
                'processed_dates': processed_dates if 'processed_dates' in locals() else 0,
                'total_records': total_records if 'total_records' in locals() else 0,
                'markets': markets,
                'error': str(e)
            }
            pipeline.save_progress(error_progress)
            logger.info("Progress saved - you can resume later")
    
    elif args.daily_update:
        # Parse markets argument
        markets = [m.strip() for m in args.markets.split(',')]
        valid_markets = ['kospi', 'kosdaq', 'kodex']
        markets = [m for m in markets if m in valid_markets]
        
        if not markets:
            logger.error("No valid markets specified. Use: kospi,kosdaq,kodex")
            sys.exit(1)

        # Import KRX API and config
        from krx_api import KRXAPI
        from config import load_config

        config_dict = load_config()
        api = KRXAPI(config_dict['api']['auth_key'], config_dict.get('api', {}))

        # Calculate yesterday's date
        if args.date:
            date_str = args.date
        else:
            yesterday = datetime.now() - timedelta(days=1)
            date_str = yesterday.strftime('%Y%m%d')

        logger.info("Running daily update for %s", date_str)
        logger.info("Fetching data for markets: %s", ', '.join(markets))

        # Check if data already exists (unless force flag is used)
        if not args.force and pipeline.check_date_exists(date_str):
            logger.info("Skipping %s - data already exists", date_str)
            return
        
        try:
            # Fetch data from API for all specified markets
            if len(markets) == 1 and markets[0] == 'kospi':
                # Use original single-market method for backward compatibility
                raw_data = api.fetch_data_for_date(date_str)
            else:
                # Use multi-market method
                market_data = api.fetch_data_for_date_multi_market(date_str, markets)
                # Combine data from all markets
                raw_data = []
                for market, records in market_data.items():
                    raw_data.extend(records)
            
            if raw_data:
                # Process and store data
                result = pipeline.process_data(raw_data)
                logger.info("Processed %d records for %s", result['prices_processed'], date_str)
            else:
                logger.warning("No data available for %s", date_str)

        except Exception as e:
            logger.error("Error processing %s: %s", date_str, e)

    else:
        logger.info("Use --help for available options")


if __name__ == '__main__':
    main()
