import yaml

CONFIG_PATH = '/Users/hirotomookawasaki/stock_swing/config/strategy/portfolio_allocation.yaml'


def load_portfolio_allocation():
    with open(CONFIG_PATH, 'r') as file:
        return yaml.safe_load(file)


def display_portfolio_allocation():
    config = load_portfolio_allocation()
    etf_allocation = config['portfolio']['allocation']['ETFs']
    stock_allocation = config['portfolio']['allocation']['stocks']
    
    print(f"\nCurrent Portfolio Allocation:")
    print(f"- ETFs: {etf_allocation * 100}%")
    print(f"- Stocks: {stock_allocation * 100}%\n")


if __name__ == '__main__':
    display_portfolio_allocation()
