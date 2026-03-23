# Gmail E2E Integration Test

This directory contains the true End-to-End (E2E) integration test for the Gmail integration. This test performs real network calls to Google's API, meaning it actually sends and processes emails.

## Running Locally

Because this test reaches out to external services, you **must** supply real Gmail OAuth credentials before running it.

### Prerequisites
1. Follow the authentication setup steps in the root `README.md` to obtain `AK_GMAIL__CLIENT_ID` and `AK_GMAIL__CLIENT_SECRET`.
2. Ensure you have the test target email exported:
   ```bash
   export AK_TEST_GMAIL_ADDRESS="your-bot-email@gmail.com"
   ```

### Execution
Run the test exactly as you would a normal pytest module:
```bash
uv run pytest server_test.py -s
```

*(Note: During CI, GitHub Actions automatically handles credential provisioning for the `nightly` workflows).*

## How Authentication Works in CI
Because the Google OAuth flow normally requires opening a web browser (which is impossible in a headless GitHub Actions runner), the test bypasses manual login by using a pre-authorized `token.pickle`. 

1. **Locally:** The first time you run the script, it opens a browser, you log in, and it saves a `token.pickle` file to the root `gmail` directory.
2. **In GitHub Actions:** The CI pipeline securely stores a base64-encoded version of this `token.pickle` as a secret (`AK_GMAIL_TOKEN_PICKLE_B64`). Before running the test, GitHub Actions decodes this secret and drops it directly into `examples/api/gmail/token.pickle`.
3. **Execution:** When `test_gmail_real_integration` runs, it spots the `token.pickle` file waiting for it, perfectly bypassing the browser login and using the refresh token to immediately talk to the Gmail API!
