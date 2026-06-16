# Healthcare Portal Knowledge Base

## Document Uploads
- We store Patient Records in AWS S3 buckets.
- **Troubleshooting Uploads**: Max file size is 10MB. If a customer cannot upload a PDF, ask them to check the file size. If the file is under 10MB and it still fails, it could be a CORS issue or an S3 outage. Escalate to `Backend Developer`.

## Database
- We use PostgreSQL for patient metadata.
- **Troubleshooting Slow Queries**: If doctors complain that fetching patient histories takes more than 10 seconds, escalate to `Database Admin` for index optimization.
