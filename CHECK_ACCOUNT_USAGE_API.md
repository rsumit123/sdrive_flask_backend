# Check Account Usage API - Quick Reference

## Endpoint

**GET** `/api/account/check_account_usage/`

## Authentication

Include the JWT token in the request header:

```
Authorization: Bearer <your_jwt_token>
```

OR

```
x-access-token: <your_jwt_token>
```

## Request

No query parameters required. Simple GET request.

## Response

```json
{
  "total_files": 150,
  "total_file_size": 5242880000,
  "total_file_size_mb": 5000.0,
  "total_file_size_gb": 4.88,
  "files_in_standard": 120,
  "files_in_archive": 30
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_files` | Integer | Total number of files uploaded |
| `total_file_size` | Integer | Total size in bytes |
| `total_file_size_mb` | Float | Total size in MB (rounded to 2 decimals) |
| `total_file_size_gb` | Float | Total size in GB (rounded to 2 decimals) |
| `files_in_standard` | Integer | Number of files in standard storage tier |
| `files_in_archive` | Integer | Number of files in archive/glacier tier |

## Quick Example (JavaScript)

```javascript
// Using fetch
const response = await fetch('/api/account/check_account_usage/', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
const usage = await response.json();

// Using axios
const response = await axios.get('/api/account/check_account_usage/', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
const usage = response.data;

// Display usage
console.log(`Total files: ${usage.total_files}`);
console.log(`Total storage: ${usage.total_file_size_gb} GB`);
console.log(`Standard: ${usage.files_in_standard} files`);
console.log(`Archive: ${usage.files_in_archive} files`);
```

## Deployment

- **Platform**: AWS Lambda via Zappa
- **Environment**: Configured in `zappa_settings.json`
- **Base URL**: Use your deployed Lambda API Gateway URL

## Full Documentation

See `API_DOC.md` for complete documentation with React examples, error handling, and best practices.

