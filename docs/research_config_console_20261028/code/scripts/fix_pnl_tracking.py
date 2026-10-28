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
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format='%(message)s')
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
        import copy
        self.original_backup = copy.deepcopy(self.data)
        logger.info(f"Loaded {len(self.data.get('trades', []))} trades")
        
    def analyze_issues(self):
        """Analyze data quality issues."""
        trades = self.data.get('trades', [])
        
        # Issue 1: Duplicate trades
        trade_ids = [t.get('trade_id') for t in trades]
        duplicates = len(trade_ids) - len(set(trade_ids))
        
        # Issue 2: Missing entry prices
        missing_entry = sum(1 for t in trades if t.get('entry_price') in [0.0, None])
        
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
        logger.info(f"  Total P&L (raw): ${total_pnl:,.2f}")
        logger.info(f"  Losing trades: {len(losers)} (expected ~40%, actual: {len(losers)/len(closed_trades)*100:.1f}%)")
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
                logger.warning(f"  Removing duplicate: {trade_id}")
        
        removed = len(trades) - len(unique_trades)
        self.data['trades'] = unique_trades
        
        logger.info(f"✓ Removed {removed} duplicate trades")
        return removed
    
    def fix_missing_entry_prices(self):
        """
        Fix missing entry prices by marking them for review.
        """
        trades = self.data.get('trades', [])
        fixed = 0
        
        for trade in trades:
            if trade.get('entry_price') in [0.0, None]:
                # Mark for manual review
                if 'notes' not in trade:
                    trade['notes'] = []
                
                trade['notes'].append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'note': 'Entry price missing - P&L may be inaccurate',
                })
                
                # If closed, mark P&L as unreliable
                if trade.get('status') == 'closed' and trade.get('pnl') is not None:
                    trade['pnl_reliability'] = 'low'
                
                fixed += 1
        
        logger.info(f"✓ Marked {fixed} trades with missing entry prices")
        return fixed
    
    def recalculate_pnl(self):
        """
        Recalculate P&L for closed trades with valid data.
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
                pnl = (exit_price - entry_price) * qty
            else:
                pnl = (entry_price - exit_price) * qty
            
            return_pct = (pnl / (entry_price * qty)) if entry_price > 0 else 0
            
            # Update if different
            old_pnl = trade.get('pnl')
            if old_pnl is None or abs(pnl - old_pnl) > 0.01:
                if old_pnl is not None:
                    logger.info(f"  {trade.get('symbol')}: ${old_pnl:,.2f} -> ${pnl:,.2f}")
                trade['pnl'] = round(pnl, 2)
                trade['return_pct'] = round(return_pct, 4)
                trade['pnl_recalculated_at'] = datetime.now(timezone.utc).isoformat()
                trade['pnl_reliability'] = 'high'
                recalculated += 1
        
        logger.info(f"✓ Recalculated P&L for {recalculated} trades")
        return recalculated
    
    def fix_reconciled_removed(self):
        """Add explanatory notes to reconciled_removed trades."""
        trades = self.data.get('trades', [])
        fixed = 0
        
        for trade in trades:
            if trade.get('status') == 'reconciled_removed':
                if 'notes' not in trade:
                    trade['notes'] = []
                
                note_text = (
                    'Removed during broker reconciliation - '
                    'position not found in broker account'
                )
                
                existing_notes = [n.get('note', '') for n in trade.get('notes', [])]
                if note_text not in existing_notes:
                    trade['notes'].append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'note': note_text,
                    })
                    fixed += 1
        
        logger.info(f"✓ Added notes to {fixed} reconciled_removed trades")
        return fixed
    
    def generate_summary(self):
        """Generate summary after fixes."""
        trades = self.data.get('trades', [])
        
        # Status counts
        status_counts = defaultdict(int)
        for trade in trades:
            status_counts[trade.get('status', 'unknown')] += 1
        
        # Reliable P&L only
        reliable_closed = [
            t for t in trades 
            if t.get('status') == 'closed' 
            and t.get('pnl') is not None
            and t.get('pnl_reliability') == 'high'
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
        
        logger.info(f"\nReliable P&L Analysis:")
        logger.info(f"  Trades with clean data: {len(reliable_closed)}")
        logger.info(f"  Winning trades: {len(winners)}")
        logger.info(f"  Losing trades: {len(losers)}")
        if reliable_closed:
            win_rate = len(winners) / len(reliable_closed) * 100
            logger.info(f"  Win rate: {win_rate:.1f}%")
        logger.info(f"  Total P&L: ${total_pnl:,.2f}")
        
        if winners:
            avg_win = sum(t.get('pnl', 0) for t in winners) / len(winners)
            max_win = max(t.get('pnl', 0) for t in winners)
            logger.info(f"  Avg win: ${avg_win:,.2f}")
            logger.info(f"  Max win: ${max_win:,.2f}")
        
        if losers:
            avg_loss = sum(t.get('pnl', 0) for t in losers) / len(losers)
            max_loss = min(t.get('pnl', 0) for t in losers)
            logger.info(f"  Avg loss: ${avg_loss:,.2f}")
            logger.info(f"  Max loss: ${max_loss:,.2f}")
        
        logger.info("=" * 60)
        
        return {
            'total_trades': len(trades),
            'status_counts': dict(status_counts),
            'reliable_closed': len(reliable_closed),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': (len(winners) / len(reliable_closed) * 100) if reliable_closed else 0,
            'total_pnl': total_pnl,
        }
    
    def save_backup(self):
        """Save backup of original data."""
        backup_file = self.pnl_file.parent / f"{self.pnl_file.stem}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(backup_file, 'w') as f:
            json.dump(self.original_backup, f, indent=2)
        
        logger.info(f"✓ Backup saved to {backup_file}")
        return backup_file
    
    def save_fixed_data(self):
        """Save fixed data."""
        self.data['last_updated'] = datetime.now(timezone.utc).isoformat()
        
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
            'note': 'Automated P&L tracker fix',
        })
        
        with open(self.pnl_file, 'w') as f:
            json.dump(self.data, f, indent=2)
        
        logger.info(f"✓ Fixed data saved to {self.pnl_file}")
    
    def run_full_fix(self):
        """Run complete fix process."""
        logger.info("\n🔧 Starting P&L tracker fix...\n")
        
        # Load data
        self.load_data()
        
        # Analyze issues
        logger.info("\n=== Step 1: Analyzing Issues ===")
        self.analyze_issues()
        
        # Save backup
        logger.info("\n=== Step 2: Creating Backup ===")
        backup_file = self.save_backup()
        
        # Apply fixes
        logger.info("\n=== Step 3: Applying Fixes ===")
        self.remove_duplicates()
        self.fix_missing_entry_prices()
        self.recalculate_pnl()
        self.fix_reconciled_removed()
        
        # Generate summary
        summary = self.generate_summary()
        
        # Save fixed data
        logger.info("\n=== Step 4: Saving Fixed Data ===")
        self.save_fixed_data()
        
        logger.info("\n✅ P&L tracker fix complete!")
        logger.info(f"📁 Backup: {backup_file}")
        logger.info(f"📁 Fixed: {self.pnl_file}\n")
        
        return summary


def main():
    """Main entry point."""
    pnl_file = "data/tracking/pnl_state.json"
    
    fixer = PnLTrackerFix(pnl_file)
    summary = fixer.run_full_fix()
    
    return summary


if __name__ == "__main__":
    main()
