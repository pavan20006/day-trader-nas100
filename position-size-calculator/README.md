# Position Size Calculator

A standalone, responsive browser tool for estimating trade size and risk across index CFDs, Forex, metals, stocks and futures.

## Run locally
1. Clone or download this repository.
2. Open `position-size-calculator/index.html` in a modern browser.
3. Enter account size and currency, choose a risk mode, then enter entry, stop and optional target.
4. Set contract units per lot, account-currency value per point per lot, and leverage to match your broker.
5. Review estimated quantity, stop loss, target gain, reward-to-risk and margin.

No server, API key or external JavaScript library is required.

## NAS100 strategy preset
The preset loads a $10,000 USD example account, fixed $75 risk, 24,000 entry, 23,980 stop (20 points), 24,040 target (40 points), contract size 1 and $1 value per point per lot. Under those assumptions, the estimate is 3.75 lots, $75 risk and $150 gross target gain before fees.

**Important:** NAS100 contract specifications vary by broker. The $1-per-point-per-lot setting is only an example. Confirm the broker's point value, contract size, minimum lot increment and margin rules before trading. Change the inputs to match the broker.

## Why it is useful
- Converts fixed cash risk or a percentage of account equity into a position-size estimate.
- Helps keep risk consistent when stop distance changes.
- Shows estimated loss at stop and net gain at target after entered fees.
- Calculates net reward-to-risk and approximate break-even win rate.
- Estimates notional exposure, margin required and balance remaining after margin.
- Supports manual quantity checks and quick what-if comparisons.

## Calculation assumptions and limitations
- Point value means account-currency value for one price point per lot.
- Contract units per lot is used for notional exposure and estimated margin.
- Risk-based quantity is rounded down to 0.01 lots.
- Estimated margin = notional value / leverage; broker margin may differ.
- Fees are treated as one total trade cost and deducted from the risk budget and target proceeds.
- No live price, FX conversion or broker contract data is fetched.
- Spread, slippage, swaps, partial fills, stop gaps, liquidation rules and taxes are not modeled unless represented in the fees input.
- A stop is not a guaranteed fill price. Losses can exceed estimates during gaps or fast markets.

Educational arithmetic only; not financial advice. Test on a demo account and verify every contract setting with your broker.
