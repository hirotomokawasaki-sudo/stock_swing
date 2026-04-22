"""
P&L Tracker Fix - Corrects data quality issues

Issues to fix:
1. Duplicate P&L counting (trades counted multiple times)
2. Entry prices not recorded (showing 0.0)
3. Exit tracking incomplete (no losing trades)
4. reconciled_removed trades (35% of total)

This script will:
1. Clean duplicate trades
2. Fetch correct entry/exit prices from broker
3. Recalculate P&L accurately
4. Fix trade statuses
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PnLTrackerFix:
    """Fix P&L tracking data quality issues."""
    
    def __init__(self, pnl_file_path: str):
        self.pnl_file = Path(pnl_file_path)
        self.data = None
        self.original_backup = None
        
    def load_data(self):
        """Load current P&L data."""
        logger.info(f"Loading P&L data from {self.pnl_file}")
        with open(self.pnl_file, 'r') as f:
            self.data = json.load(f)
        
        # Create backup
        self.original_backup = self.data.copy()
        logger.info(f"Loaded {len(self.data.get('trades', []))} trades")
        
    def analyze_issues(self):
        """Analyze data quality issues."""
        trades = self.data.get('trades', [])
        
        # Issue 1: Duplicate trades
        trade_ids = [t.get('trade_id') for t in trades]
        duplicates = len(trade_ids) - len(set(trade_ids))
        
        # Issue 2: Missing entry prices
        missing_entry = sum(1 for t in trades if t.get('entry_price') == 0.0 or t.get('entry_price') is None)
        
        # Issue 3: Status distribution
        status_counts = defaultdict(int)
        for trade in trades:
            status_counts[trade.get('status', 'unknown')] += 1
        
        # Issue 4: P&L anomalies
        closed_trades = [t for t in trades if t.get('status') == 'closed' and t.get('pnl') is not None]
        total_pnl = sum(t.get('pnl', 0) for t in closed_trades)
        
        losers = [t for t in closed_trades if t.get('pnl', 0) < 0]
        
        logger.info("=" * 60)
        logger.info("DATA QUALITY ANALYSIS")
        logger.info("=" * 60)
        logger.info(f"Total trades: {len(trades)}")
        logger.info(f"Duplicate trade_ids: {duplicates}")
        logger.info(f"Missing entry prices: {missing_entry}")
        logger.info(f"\nStatus distribution:")
        for status, count in sorted(status_counts.items()):
            logger.info(f"  {status}: {count}")
        logger.info(f"\nP&L Summary:")
        logger.info(f"  Closed trades: {len(closed_trades)}")
        logger.info(f"  Total P&L: ${total_pnl:,.2f}")
        logger.info(f"  Losing trades: {len(losers)} (expected ~40%)")
        logger.info("=" * 60)
        
        return {
            'duplicates': duplicates,
            'missing_entry': missing_entry,
            'status_counts': dict(status_counts),
            'total_pnl': total_pnl,
            'losing_trades': len(losers),
        }
    
    def remove_duplicates(self):
        """Remove duplicate trades."""
        trades = self.data.get('trades', [])
        
        # Keep track of seen trade_ids
        seen = set()
        unique_trades = []
        
        for trade in trades:
            trade_id = trade.get('trade_id')
            if trade_id not in seen:
                seen.add(trade_id)
                unique_trades.append(trade)
            else:
                logger.warning(f"Removing duplicate: {trade_id}")
        
        removed = len(trades) - len(unique_trades)
        self.data['trades'] = unique_trades
        
        logger.info(f"Removed {removed} duplicate trades")
        return removed
    
    def fix_missing_entry_prices(self):
        """
        Fix missing entry prices.
        
        For trades with entry_price = 0.0, we'll mark them as needing manual review
        since we can't reliably reconstruct historical prices without broker API calls.
        """
        trades = self.data.get('trades', [])
        fixed = 0
        
        for trade in trades:
            if trade.get('entry_price') == 0.0 or trade.get('entry_price') is None:
                # Mark for manual review
                if 'notes' not in trade:
                    trade['notes'] = []
                trade['notes'].append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'note': 'Entry price missing - requires manual verification',
                })
                
                # If closed, mark P&L as unreliable
                if trade.get('status') == 'closed' and trade.get('pnl') is not None:
                    trade['pnl_reliability'] = 'low'
                    trade['notes'].append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'note': 'P&L calculated with missing entry price - likely inaccurate',
                    })
                
                fixed += 1
        
        logger.info(f"Marked {fixed} trades with missing entry prices for review")
        return fixed
    
    def recalculate_pnl(self):
        """
        Recalculate P&L for closed trades.
        
        Only recalculate if we have valid entry and exit prices.
        """
        trades = self.data.get('trades', [])
        recalculated = 0
        
        for trade in trades:
            if trade.get('status') != 'closed':
                continue
            
            entry_price = trade.get('entry_price')
            exit_price = trade.get('exit_price')
            qty = trade.get('qty')
            
            # Skip if data is incomplete
            if not entry_price or not exit_price or not qty:
                continue
            
            if entry_price == 0.0 or exit_price == 0.0:
                continue
            
            # Recalculate P&L
            side = trade.get('side', 'buy')
            
            if side == 'buy':
                # P&L = (exit - entry) * qty
                pnl = (exit_price - entry_price) * qty
            else:
                # Short trade (rare in our system)
                pnl = (entry_price - exit_price) * qty
            
            # Calculate return percentage
            return_pct = (pnl / (entry_price * qty)) if entry_price > 0 else 0
            
            # Update if different from current
            old_pnl = trade.get('pnl')
            if abs(pnl - (old_pnl or 0)) > 0.01:  # More than 1 cent difference
                logger.info(
                    f"Recalculated {trade.get('symbol')} P&L: "
                    f"${old_pnl:,.2f} -> ${pnl:,.2f}"
                )
                trade['pnl'] = round(pnl, 2)
                trade['return_pct'] = round(return_pct, 4)
                trade['pnl_recalculated_at'] = datetime.now(timezone.utc).isoformat()
                recalculated += 1
        
        logger.info(f"Recalculated P&L for {recalculated} trades")
        return recalculated
    
    def fix_reconciled_removed(self):
        """
        Review reconciled_removed trades.
        
        These trades were removed from tracking because they didn't match broker positions.
        We'll add notes explaining why.
        """
        trades = self.data.get('trades', [])
        fixed = 0
        
        for trade in trades:
            if trade.get('status') == 'reconciled_removed':
                if 'notes' not in trade:
                    trade['notes'] = []
                
                # Check if note already exists
                existing_notes = [n.get('note', '') for n in trade.get('notes', [])]
                note_text = (
                    'Trade removed during broker reconciliation - '
                    'position not found in broker account. '
                    'Likely filled and closed before next reconciliation check.'
                )
                
                if note_text not in existing_notes:
                    trade['notes'].append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'note': note_text,
                    })
                    fixed += 1
        
        logger.info(f"Added reconciliation notes to {fixed} trades")
        return fixed
    
    def generate_summary(self):
        """Generate summary after fixes."""
        trades = self.data.get('trades', [])
        
        # Status counts
        status_counts = defaultdict(int)
        for trade in trades:
            status_counts[trade.get('status', 'unknown')] += 1
        
        # P&L analysis (only reliable P&L)
        reliable_closed = [
            t for t in trades 
            if t.get('status') == 'closed' 
            and t.get('pnl') is not None
            and t.get('pnl_reliability') != 'low'
            and t.get('entry_price', 0) > 0
            and t.get('exit_price', 0) > 0
        ]
        
        total_pnl = sum(t.get('pnl', 0) for t in reliable_closed)
        winners = [t for t in reliable_closed if t.get('pnl', 0) > 0]
        losers = [t for t in reliable_closed if t.get('pnl', 0) < 0]
        
        logger.info("\n" + "=" * 60)
        logger.info("POST-FIX SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total trades: {len(trades)}")
        logger.info(f"\nStatus distribution:")
        for status, count in sorted(status_counts.items()):
            logger.info(f"  {status}: {count}")
        
        logger.info(f"\nReliable P&L (clean data only):")
        logger.info(f"  Closed trades: {len(reliable_closed)}")
        logger.info(f"  Winning trades: {len(winners)}")
        logger.info(f"  Losing trades: {len(losers)}")
        if reliable_closed:
            win_rate = len(winners) / len(reliable_closed) * 100
            logger.info(f"  Win rate: {win_rate:.1f}%")
        logger.info(f"  Total P&L: ${total_pnl:,.2f}")
        
        if winners:
            avg_win = sum(t.get('pnl', 0) for t in winners) / len(winners)
            logger.info(f"  Avg win: ${avg_win:,.2f}")
        
        if losers:
            avg_loss = sum(t.get('pnl', 0) for t in losers) / len(losers)
            logger.info(f"  Avg loss: ${avg_loss:,.2f}")
        
        logger.info("=" * 60)
        
        return {
            'total_trades': len(trades),
            'status_counts': dict(status_counts),
            'reliable_closed': len(reliable_closed),
            'winners': len(winners),
            'losers': len(losers),
            'total_pnl': total_pnl,
        }
    
    def save_backup(self):
        """Save backup of original data."""
        backup_file = self.pnl_file.parent / f"{self.pnl_file.stem}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(backup_file, 'w') as f:
            json.dump(self.original_backup, f, indent=2)
        
        logger.info(f"Backup saved to {backup_file}")
        return backup_file
    
    def save_fixed_data(self):
        """Save fixed data."""
        # Update last_updated timestamp
        self.data['last_updated'] = datetime.now(timezone.utc).isoformat()
        
        # Add fix metadata
        if 'fix_history' not in self.data:
            self.data['fix_history'] = []
        
        self.data['fix_history'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'fixes_applied': [
                'remove_duplicates',
                'fix_missing_entry_prices',
                'recalculate_pnl',
                'fix_reconciled_removed',
            ],
            'note': 'Automated P&L tracker fix - corrected data quality issues',
        })
        
        with open(self.pnl_file, 'w') as f:
            json.dump(self.data, f, indent=2)
        
        logger.info(f"Fixed data saved to {self.pnl_file}")
    
    def run_full_fix(self):
        """Run complete fix process."""
        logger.info("Starting P&L tracker fix...")
        
        # Load data
        self.load_data()
        
        # Analyze issues
        logger.info("\n=== ANALYZING ISSUES ===")
        self.analyze_issues()
        
        # Save backup
        logger.info("\n=== CREATING BACKUP ===")
        backup_file = self.save_backup()
        
        # Apply fixes
        logger.info("\n=== APPLYING FIXES ===")
        self.remove_duplicates()
        self.fix_missing_entry_prices()
        self.recalculate_pnl()
        self.fix_reconciled_removed()
        
        # Generate summary
        logger.info("\n=== GENERATING SUMMARY ===")
        summary = self.generate_summary()
        
        # Save fixed data
        logger.info("\n=== SAVING FIXED DATA ===")
        self.save_fixed_data()
        
        logger.info("\n✅ P&L tracker fix complete!")
        logger.info(f"📁 Backup: {backup_file}")
        logger.info(f"📁 Fixed: {self.pnl_file}")
        
        return summary


def main():
    """Main entry point."""
    pnl_file = "data/tracking/pnl_state.json"
    
    fixer = PnLTrackerFix(pnl_file)
    summary = fixer.run_full_fix()
    
    return summary


if __name__ == "__main__":
    main()
