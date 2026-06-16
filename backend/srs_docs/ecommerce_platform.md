# E-commerce Platform Knowledge Base

## UI/Frontend
- Built on React and TailwindCSS.
- **Troubleshooting CSS**: If buttons are misaligned or overlapping, tell the customer to perform a Hard Refresh (Ctrl+F5) to clear the browser cache. If the issue persists, escalate to `Frontend Developer`.

## Payment Gateway
- We use Stripe API.
- **Troubleshooting Payments**: "Card Declined" usually means insufficient funds. "Gateway Timeout" means our webhooks are failing. Escalate timeouts to `Backend Developer`.
