# Banking App Knowledge Base

## Authentication & 2FA
- We use OAuth2.0 and Twilio for SMS 2FA.
- **Troubleshooting 2FA**: If SMS is not arriving, check the Twilio API logs. Ask the customer if their phone number starts with +1.
- **Security Escalation**: If a user bypasses 2FA, it is a CRITICAL severity issue. Escalate to the `Security Analyst`.

## Transactions
- Core ledger is written in Java Spring Boot.
- **Troubleshooting Timeouts**: Transaction timeouts occur if the load balancer misroutes traffic. Escalate to `Backend Developer`.
