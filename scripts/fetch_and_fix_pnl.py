"""
Fetch actual entry/exit prices from broker and fix P&L data.

This script will:
1. Connect to Alpaca broker
2. Fetch order history
3. Match orders with trades in pnl_state.json
4. Update entry/exit prices
5. Recalculate P&L accurately
"""

import json
import logging
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Import broker client
from stock_swing.sources.broker_client import BrokerClient


class PnLFixer:
    """Fix P&L by fetching actual prices from broker."""
    
    def __init__(self, pnl_file_path: str):
        self.pnl_file = Path(pnl_file_path)
        self.data = None
        
        # Initialize broker client
        logger.info("Initializing Alpaca broker client...")
        api_key = os.getenv("BROKER_API_KEY")
        api_secret = os.getenv("BROKER_API_SECRET")
        
        if not api_key or not api_secret:
            raise ValueError("BROKER_API_KEY and BROKER_API_SECRET must be set in .env")
        
        self.broker = BrokerClient(
            api_key=api_key,
            api_secret=api_secret,
            paper_mode=True,
        )
    
    def load_data(self):
        """Load P&L data."""
        logger.info(f"Loading {self.pnl_file}...")
        with open(self.pnl_file, 'r') as f:
            self.data = json.load(f)
        logger.info(f"✓ Loaded {len(self.data.get('trades', []))} trades\n")
        
    def fetch_order_history(self):
        """Fetch all orders from broker."""
        logger.info("Fetching order history from Alpaca...")
        
        try:
            # Fetch all orders (paper account)
            response = self.broker.client.get('/v2/orders', params={
                'status': 'all',
                'limit': 500,  # Max allowed
                'direction': 'desc',
            })
            
            orders = response.json() if hasattr(response, 'json') else response
            logger.info(f"✓ Fetched {len(orders)} orders from broker\n")
            
            return orders
            
        except Exception as e:
            logger.error(f"❌ Error fetching orders: {e}")
            return []
    
    def match_and_fix_trades(self, orders):
        """Match broker orders with trades and fix prices."""
        trades = self.data.get('trades', [])
        
        # Index orders by broker_order_id
        order_map = {}
        for order in orders:
            order_id = order.get('id')
            if order_id:
                order_map[order_id] = order
        
        logger.info("=== Matching & Fixing Trades ===\n")
        
        fixed = 0
        matched = 0
        
        for trade in trades:
            broker_order_id = trade.get('broker_order_id')
            
            if not broker_order_id:
                continue
            
            if broker_order_id in order_map:
                matched += 1
                order = order_map[broker_order_id]
                
                # Get filled price
                filled_avg_price = order.get('filled_avg_price')
                filled_qty = order.get('filled_qty')
                status = order.get('status')
                side = order.get('side')
                
                if filled_avg_price and float(filled_avg_price) > 0:
                    # Update entry price
                    trade['entry_price'] = float(filled_avg_price)
                    trade['qty'] = int(filled_qty) if filled_qty else trade.get('qty')
                    trade['order_status'] = status
                    
                    logger.info(
                        f"✓ {trade.get('symbol'):6} "
                        f"{side:4} "
                        f"{trade['qty']:3} shares @ ${float(filled_avg_price):.2f} "
                        f"({status})"
                    )
                    
                    fixed += 1
        
        logger.info(f"\n✓ Matched {matched} trades")
        logger.info(f"✓ Fixed {fixed} entry prices\n")
        
        return fixed
    
    def fetch_current_positions(self):
        """Fetch current positions to get current prices for open trades."""
        logger.info("Fetching current positions...")
        
        try:
            positions_response = self.broker.fetch_positions()
            positions = positions_response.payload if hasattr(positions_response, 'payload') else positions_response
            
            # Index by symbol
            position_map = {}
            for pos in positions:
                symbol = pos.get('symbol')
                if symbol:
                    position_map[symbol] = pos
            
            logger.info(f"✓ Found {len(position_map)} open positions\n")
            
            # Update open trades with current prices
            trades = self.data.get('trades', [])
            updated = 0
            
            for trade in trades:
                if trade.get('status') != 'open':
                    continue
                
                symbol = trade.get('symbol')
                if symbol in position_map:
                    pos = position_map[symbol]
                    
                    # Update with position data
                    trade['avg_entry_price'] = float(pos.get('avg_entry_price', 0))
                    trade['current_price'] = float(pos.get('current_price', 0))
                    trade['qty'] = int(float(pos.get('qty', trade.get('qty', 0))))
                    trade['market_value'] = float(pos.get('market_value', 0))
                    trade['unrealized_pl'] = float(pos.get('unrealized_pl', 0))
                    trade['unrealized_plpc'] = float(pos.get('unrealized_plpc', 0))
                    
                    # Use avg_entry_price as entry_price if missing
                    if trade.get('entry_price') in [0.0, None] and trade.get('avg_entry_price'):
                        trade['entry_price'] = trade['avg_entry_price']
                    
                    updated += 1
            
            logger.info(f"✓ Updated {updated} open positions with current prices\n")
            
            return updated
            
        except Exception as e:
            logger.error(f"❌ Error fetching positions: {e}")
            return 0
    
    def recalculate_pnl(self):
        """Recalculate P&L for closed trades."""
        trades = self.data.get('trades', [])
        recalculated = 0
        
        logger.info("=== Recalculating P&L ===\n")
        
        for trade in trades:
            if trade.get('status') != 'closed':
                continue
            
            entry_price = trade.get('entry_price')
            exit_price = trade.get('exit_price')
            qty = trade.get('qty')
            
            if not entry_price or not exit_price or not qty:
                continue
            
            if entry_price == 0.0 or exit_price == 0.0:
                continue
            
            # Calculate P&L
            side = trade.get('side', 'buy')
            
            if side == 'buy':
                pnl = (exit_price - entry_price) * qty
            else:
                pnl = (entry_price - exit_price) * qty
            
            return_pct = (pnl / (entry_price * qty)) if entry_price > 0 else 0
            
            # Update
            trade['pnl'] = round(pnl, 2)
            trade['return_pct'] = round(return_pct, 4)
            trade['pnl_reliability'] = 'high'
            trade['pnl_recalculated_at'] = datetime.now(timezone.utc).isoformat()
            
            recalculated += 1
            
            logger.info(
                f"{trade.get('symbol'):6} "
                f"Entry: ${entry_price:.2f}, Exit: ${exit_price:.2f}, "
                f"P&L: ${pnl:+,.2f}"
            )
        
        logger.info(f"\n✓ Recalculated {recalculated} closed trades\n")
        
        return recalculated
    
    def generate_summary(self):
        """Generate final summary."""
        trades = self.data.get('trades', [])
        
        # All closed trades with valid data
        closed_trades = [
            t for t in trades
            if t.get('status') == 'closed'
            and t.get('pnl') is not None
            and t.get('entry_price', 0) > 0
            and t.get('exit_price', 0) > 0
        ]
        
        total_pnl = sum(t.get('pnl', 0) for t in closed_trades)
        winners = [t for t in closed_trades if t.get('pnl', 0) > 0]
        losers = [t for t in closed_trades if t.get('pnl', 0) < 0]
        
        # Open trades
        open_trades = [t for t in trades if t.get('status') == 'open']
        unrealized_pnl = sum(t.get('unrealized_pl', 0) for t in open_trades)
        
        logger.info("=" * 60)
        logger.info("FINAL SUMMARY")
        logger.info("=" * 60)
        
        logger.info(f"\nClosed Trades: {len(closed_trades)}")
        logger.info(f"  Winners: {len(winners)}")
        logger.info(f"  Losers: {len(losers)}")
        if closed_trades:
            win_rate = len(winners) / len(closed_trades) * 100
            logger.info(f"  Win Rate: {win_rate:.1f}%")
        logger.info(f"  Total Realized P&L: ${total_pnl:+,.2f}")
        
        if winners:
            avg_win = sum(t.get('pnl', 0) for t in winners) / len(winners)
            max_win = max(t.get('pnl', 0) for t in winners)
            logger.info(f"  Avg Win: ${avg_win:,.2f}")
            logger.info(f"  Max Win: ${max_win:,.2f}")
        
        if losers:
            avg_loss = sum(t.get('pnl', 0) for t in losers) / len(losers)
            max_loss = min(t.get('pnl', 0) for t in losers)
            logger.info(f"  Avg Loss: ${avg_loss:,.2f}")
            logger.info(f"  Max Loss: ${max_loss:,.2f}")
        
        logger.info(f"\nOpen Positions: {len(open_trades)}")
        logger.info(f"  Total Unrealized P&L: ${unrealized_pnl:+,.2f}")
        
        logger.info(f"\nCombined:")
        logger.info(f"  Total P&L: ${total_pnl + unrealized_pnl:+,.2f}")
        
        logger.info("=" * 60)
        
        return {
            'closed_trades': len(closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': (len(winners) / len(closed_trades) * 100) if closed_trades else 0,
            'total_realized_pnl': total_pnl,
            'total_unrealized_pnl': unrealized_pnl,
            'total_pnl': total_pnl + unrealized_pnl,
        }
    
    def save_data(self):
        """Save fixed data."""
        self.data['last_updated'] = datetime.now(timezone.utc).isoformat()
        
        if 'fix_history' not in self.data:
            self.data['fix_history'] = []
        
        self.data['fix_history'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'method': 'fetch_from_broker',
            'note': 'Fetched actual prices from Alpaca and recalculated P&L',
        })
        
        # Save
        with open(self.pnl_file, 'w') as f:
            json.dump(self.data, f, indent=2)
        
        logger.info(f"\n✅ Saved fixed data to {self.pnl_file}")
    
    def run(self):
        """Run full fix process."""
        logger.info("\n" + "=" * 60)
        logger.info("P&L FIXER - FETCH FROM BROKER")
        logger.info("=" * 60 + "\n")
        
        # Load data
        self.load_data()
        
        # Fetch order history
        orders = self.fetch_order_history()
        
        # Match and fix
        self.match_and_fix_trades(orders)
        
        # Update open positions
        self.fetch_current_positions()
        
        # Recalculate P&L
        self.recalculate_pnl()
        
        # Summary
        summary = self.generate_summary()
        
        # Save
        self.save_data()
        
        logger.info("\n✅ P&L fix complete!\n")
        
        return summary


def main():
    fixer = PnLFixer("data/tracking/pnl_state.json")
    summary = fixer.run()
    return summary


if __name__ == "__main__":
    main()
