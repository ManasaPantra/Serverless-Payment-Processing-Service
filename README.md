## Serverless Payment Processing Service (Lambda · API Gateway · CloudFront · WAF)

This project deploys a serverless payment workflow:

- REST API for webhook ingestion (`/webhook`) backed by AWS Lambda
- WAF (regional) with an IP allow-list to protect `/webhook`
- CloudFront distribution in front of the REST API for global performance
- Real-time payment events via SNS → Lambda → API Gateway WebSocket
- DynamoDB table to track connected WebSocket clients

### Architecture

- Webhook provider → CloudFront → API Gateway (REST) → Lambda (`PaymentWebhookHandler`)
- Lambda publishes events to SNS topic (`PaymentEventsTopic`)
- SNS triggers `PaymentBroadcaster` Lambda which broadcasts to WebSocket clients
- WebSocket API ($connect/$disconnect) stores/removes connection IDs in DynamoDB
- WAF WebACL (regional) allows `/webhook` only from specified IP CIDR blocks
  - For Stripe, IP allow-listing is not recommended; use signature verification instead (see below)

### Prerequisites

- AWS account with permissions to deploy SAM stacks
- AWS CLI configured (`aws configure`)
- AWS SAM CLI installed (`sam --version`)

### Deploy

1. Build:

```bash
cd "/Users/manasa/Desktop/AWS Lambda"
sam build
```

2. Deploy (first time use `--guided`):

```bash
sam deploy --guided
```

Recommended parameter notes during guided deploy:
- Stack Name: `serverless-payment-service`
- Region: choose your region (e.g., `us-east-1`)
- StageName: `prod` (default)
- EnableWebhookIpAllowList: set to `false` for Stripe (recommended)
- AllowedWebhookCidrs: only if your provider publishes stable IPs (Stripe does not)
- StripeEndpointSecret: your Stripe endpoint secret (starts with `whsec_`)
- StripeToleranceSeconds: signature tolerance window (default 300)
- SigningSecret: for non-Stripe generic HMAC validation via `X-Signature`

The deploy will output:
- `CloudFrontDomainName` (use this to reach your REST API globally)
- `RestApiInvokeUrl` (regional direct invoke URL)
- `WebSocketApiUrl` (use in your web/mobile client for real-time updates)

### Testing

1. Connect a WebSocket client (example with wscat):

```bash
npx wscat -c "wss://<api-id>.execute-api.<region>.amazonaws.com/<stage>"
```

2. Send a test webhook (replace domain with CloudFront or RestApi invoke URL):

```bash
curl -X POST "https://<your-cloudfront-domain>/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Event-Type: test.payment.succeeded" \
  -H "X-Signature: $(echo -n '{"test":"ok"}' | openssl dgst -sha256 -hmac '<SigningSecret>' -hex | sed 's/^.* //')" \
  -d '{"test":"ok"}'
```

All connected WebSocket clients should receive the JSON payload.

### Stripe-specific setup and testing

1. Set parameters:
   - `EnableWebhookIpAllowList = false` (Stripe does not provide stable webhook IPs)
   - `StripeEndpointSecret = whsec_xxx` (from your Stripe Dashboard → Developers → Webhooks)

2. Use Stripe CLI to forward events to your endpoint:

```bash
# Authenticate once:
stripe login

# Listen and forward to your deployed endpoint:
stripe listen --forward-to "https://<your-cloudfront-domain>/webhook"
```

3. Trigger test events (in another terminal):

```bash
stripe trigger payment_intent.succeeded
```

Your connected WebSocket clients should receive the event payload.

### Customization

- Replace `AllowedWebhookCidrs` with your provider IPs
- Configure `SigningSecret` to enable HMAC body verification
- Configure `StripeEndpointSecret` to enable Stripe signature verification
- Extend `webhook_handler.py` to validate provider-specific signatures if required
- Add custom routes/REST endpoints to `template.yaml` as needed

### Clean up

```bash
sam delete
```


