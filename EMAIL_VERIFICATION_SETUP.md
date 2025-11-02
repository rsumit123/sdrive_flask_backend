# Email Verification Setup Guide

## Overview

The email verification flow has been implemented. Users must verify their email address before they can log in. The system supports two email sending methods:

1. **AWS SES** (Recommended if you're already using AWS)
2. **SMTP** (Works with Gmail, SendGrid, Mailgun, etc.)

## How It Works

1. User registers → Backend creates user account with `email_verified: false`
2. Backend sends verification email with a unique token
3. User sees success screen → "Check your email" message
4. User clicks link in email → Opens `/verify-email?token=<token>` on frontend
5. Frontend calls verification API → `POST /api/auth/verify-email/` with token
6. Backend verifies token → Sets `email_verified: true`
7. User can now sign in → Login endpoint checks `email_verified` status

## Environment Variables

### For AWS SES (Recommended)

Add these to your `.env` file:

```bash
# Use AWS SES instead of SMTP
USE_AWS_SES=true

# AWS SES Configuration (uses same credentials as S3)
AWS_SES_REGION=us-east-1  # Change to your AWS region
AWS_SES_FROM_EMAIL=noreply@yourdomain.com  # Must be verified in SES

# Frontend URL for verification links
FRONTEND_URL=https://yourdomain.com
```

**Note:** The email address in `AWS_SES_FROM_EMAIL` must be verified in AWS SES (or the domain must be verified). If you're in SES sandbox mode, all recipient emails must also be verified.

### For SMTP

Add these to your `.env` file:

```bash
# Don't use AWS SES
USE_AWS_SES=false

# SMTP Configuration
SMTP_HOST=smtp.gmail.com  # For Gmail
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # Use app password for Gmail
SMTP_FROM_EMAIL=your-email@gmail.com

# Frontend URL for verification links
FRONTEND_URL=https://yourdomain.com
```

#### SMTP Examples

**Gmail:**
```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # Generate from Google Account settings
```

**SendGrid:**
```bash
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-sendgrid-api-key
SMTP_FROM_EMAIL=noreply@yourdomain.com
```

**Mailgun:**
```bash
SMTP_HOST=smtp.mailgun.org
SMTP_PORT=587
SMTP_USER=postmaster@yourdomain.mailgun.org
SMTP_PASSWORD=your-mailgun-password
SMTP_FROM_EMAIL=noreply@yourdomain.com
```

## API Endpoints

### 1. Registration Endpoint (Updated)

**POST** `/api/auth/register/`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response (201):**
```json
{
  "message": "User created successfully. Please check your email to verify your account.",
  "email_sent": true
}
```

**Changes:**
- No longer returns JWT token immediately
- Sends verification email automatically
- User account created with `email_verified: false`

### 2. Email Verification Endpoint (New)

**POST** `/api/auth/verify-email/`

**Request:**
```json
{
  "token": "verification_token_from_email"
}
```

**Response (200):**
```json
{
  "message": "Email verified successfully"
}
```

**Error Responses:**
- `400` - Invalid or expired token
- `200` - Already verified (returns success message)

### 3. Login Endpoint (Updated)

**POST** `/api/auth/login/`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response (200):**
```json
{
  "message": "Login successful",
  "token": "jwt_token_here"
}
```

**Error Response (403) - Email not verified:**
```json
{
  "error": "Email not verified. Please check your email and verify your account.",
  "email_verified": false
}
```

**Changes:**
- Now checks `email_verified` status
- Returns 403 error if email is not verified
- Users must verify email before logging in

## Database Schema Changes

The user document now includes:

```javascript
{
  "email": "user@example.com",
  "password": "hashed_password",
  "email_verified": false,  // NEW
  "verification_token": "random_token_here",  // NEW
  "verification_token_expiry": ISODate("..."),  // NEW (24 hours from creation)
  "created_at": ISODate("...")  // NEW
}
```

After verification, `verification_token` and `verification_token_expiry` are removed, and `email_verified` is set to `true`.

## Third-Party Services Needed

### Option 1: AWS SES (Recommended)

**Pros:**
- Already using AWS (S3)
- Highly scalable
- Cost-effective (62,000 emails/month free tier)
- No additional setup if SES is configured

**Cons:**
- Requires AWS SES account setup
- Email/domain verification required
- Sandbox mode limitations initially

**Setup Steps:**
1. Go to AWS SES Console
2. Verify your email address or domain
3. If in sandbox mode, verify recipient emails too
4. Request production access for production use
5. Set `USE_AWS_SES=true` in `.env`

### Option 2: SMTP Service

**Popular Options:**
- **Gmail**: Free, but requires app password and has sending limits
- **SendGrid**: 100 emails/day free, then paid
- **Mailgun**: 5,000 emails/month free, then paid
- **Amazon SES SMTP**: Use SES via SMTP (same as Option 1, but different interface)

**Setup Steps:**
1. Sign up for SMTP service
2. Get SMTP credentials
3. Configure in `.env` file
4. Set `USE_AWS_SES=false` in `.env`

## Frontend Integration

The frontend should:

1. **Registration:**
   - Call `POST /api/auth/register/`
   - Show success message: "Check your email to verify your account"
   - Don't try to log in immediately

2. **Email Verification:**
   - Extract token from URL query parameter: `/verify-email?token=...`
   - Call `POST /api/auth/verify-email/` with `{"token": "..."}`
   - Show success message
   - Redirect to login page

3. **Login:**
   - Handle 403 error with `email_verified: false`
   - Show message prompting user to verify email
   - Optionally provide "Resend verification email" option

## Testing

### Test Registration Flow:

1. Register a new user
2. Check that user is created with `email_verified: false`
3. Check email inbox for verification email
4. Extract token from email link
5. Call verification endpoint with token
6. Verify user document has `email_verified: true`
7. Attempt login - should succeed

### Test Unverified Login:

1. Register but don't verify
2. Attempt login
3. Should receive 403 error with `email_verified: false`

## Troubleshooting

### Emails Not Sending

1. **AWS SES:**
   - Check email/domain is verified in SES
   - Check AWS credentials are correct
   - Check SES is not in sandbox mode (or recipient is verified)
   - Check CloudWatch logs for SES errors

2. **SMTP:**
   - Verify SMTP credentials are correct
   - Check firewall allows SMTP connections
   - Gmail users: Must use app password, not regular password
   - Check application logs for SMTP errors

### Verification Token Issues

- Tokens expire after 24 hours
- Each user has only one active token (new registration replaces old token)
- Tokens are one-time use (removed after verification)

## Security Notes

- Verification tokens are cryptographically secure (using `secrets.token_urlsafe`)
- Tokens expire after 24 hours
- Tokens are removed from database after verification
- Unverified users cannot access protected resources (enforced by login check)

