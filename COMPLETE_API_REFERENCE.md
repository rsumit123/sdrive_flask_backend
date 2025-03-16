# S3 Drive API Reference

This document provides a comprehensive reference for the S3 Drive API, including endpoints for file listing, uploading, and management.

## Authentication

All API endpoints require authentication using JWT tokens. Include the token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

## Endpoints

### 1. List Files

Retrieves a paginated list of files for the authenticated user with metadata from S3.

#### Request

```
GET /api/v2/files/
```

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | Integer | No | 1 | Page number for offset-based pagination |
| `per_page` | Integer | No | 50 | Number of items per page (max 100) |
| `cursor` | String | No | null | Cursor for cursor-based pagination (overrides page parameter) |
| `use_cache` | Boolean | No | true | Whether to use cached metadata or fetch fresh data from S3 |

#### Response

```json
{
  "files": [
    {
      "file_name": "example.jpg",
      "simple_url": "https://bucket-url.com/username/example.jpg",
      "metadata": {
        "tier": "standard",
        "size": 1024000
      },
      "upload_complete": "complete",
      "last_modified": "2023-05-15T14:30:45.123Z",
      "id": "username/example.jpg",
      "s3_key": "username/example.jpg"
    }
  ],
  "total": 120,
  "total_pages": 3,
  "page": 1,
  "per_page": 50,
  "next_cursor": "ts:2023-05-15T14:30:45.123Z"
}
```

### 2. List Files - Optimized (v3)

A high-performance version of the list files endpoint that significantly reduces response time, especially for large file collections.

#### Request

```
GET /api/v3/files/
```

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | Integer | No | 1 | Page number for offset-based pagination |
| `per_page` | Integer | No | 50 | Number of items per page (max 1000) |
| `cursor` | String | No | null | Cursor for cursor-based pagination (overrides page parameter) |
| `use_cache` | Boolean | No | true | Whether to use cached results |

#### Response

```json
{
  "files": [
    {
      "file_name": "example.jpg",
      "simple_url": "https://bucket-url.com/username/example.jpg",
      "metadata": {
        "tier": "standard",
        "size": 1024000,
        "content_type": "image/jpeg"
      },
      "upload_complete": "complete",
      "last_modified": "2023-05-15T14:30:45.123Z",
      "id": "username-example.jpg",
      "s3_key": "username/example.jpg",
      "exists_in_db": true
    }
  ],
  "total": 120,
  "total_pages": 3,
  "page": 1,
  "per_page": 50,
  "next_cursor": "eyJrZXkiOiJ1c2VybmFtZS9leGFtcGxlLmpwZyJ9"
}
```

#### Performance Improvements

This endpoint offers several performance advantages over the v2 endpoint:

1. **Reduced API Calls**: Uses S3's `list_objects_v2` API to get multiple files in a single call
2. **Response Caching**: Caches entire responses for 5 minutes
3. **Efficient Pagination**: Uses S3's native pagination mechanisms
4. **Automatic Cache Expiration**: Cache entries automatically expire after 1 hour
5. **Recently Uploaded Files**: Includes recently uploaded files that might not yet appear in S3 listings due to S3's eventual consistency model

#### Handling of Recently Uploaded Files

Due to S3's eventual consistency model, newly uploaded files might not immediately appear in the `list_objects_v2` API results. To address this issue, the endpoint also checks the database for recently uploaded files (within the last 5 minutes) and includes them in the response. This ensures that files are visible in the listing immediately after upload confirmation, even if they haven't propagated through S3's consistency model yet.

When `use_cache=false` is specified, the endpoint will:
1. Fetch the latest file list from S3
2. Check the database for recently uploaded files
3. Combine and sort the results
4. Skip caching the response if recently uploaded files are included

This approach provides the best balance between performance and data freshness.

### 3. Upload Files

Generates presigned URLs for uploading files directly to S3. Supports both single and multiple file uploads.

#### Request (Multiple Files)

```
POST /api/files/upload/
```

#### Request Body (Multiple Files)

```json
{
  "files": [
    {
      "file_name": "example1.jpg",
      "content_type": "image/jpeg",
      "file_size": 1024000,
      "tier": "standard"
    },
    {
      "file_name": "example2.pdf",
      "content_type": "application/pdf",
      "file_size": 2048000,
      "tier": "glacier"
    }
  ]
}
```

#### Request Body (Single File - Backward Compatibility)

```json
{
  "file_name": "example.jpg",
  "content_type": "image/jpeg",
  "file_size": 1024000,
  "tier": "standard"
}
```

#### Response

```json
{
  "message": "Successfully generated presigned URLs for 2 files. 0 files failed.",
  "successful": [
    {
      "file_name": "example1.jpg",
      "presigned_url": "https://bucket-name.s3.amazonaws.com/...",
      "s3_key": "username/example1.jpg",
      "id": "username-example1.jpg",
      "status": "success"
    },
    {
      "file_name": "example2.pdf",
      "presigned_url": "https://bucket-name.s3.amazonaws.com/...",
      "s3_key": "username/example2.pdf",
      "id": "username-example2.pdf",
      "status": "success"
    }
  ],
  "failed": []
}
```

### 4. Confirm Multiple Uploads

Confirms that multiple files have been successfully uploaded to S3.

#### Request

```
POST /api/files/confirm_uploads/
```

#### Request Body

```json
{
  "s3_keys": [
    "username/example1.jpg",
    "username/example2.pdf"
  ]
}
```

#### Response

```json
{
  "message": "Upload confirmation processed",
  "results": [
    {
      "s3_key": "username/example1.jpg",
      "status": "success",
      "message": "Upload confirmed"
    },
    {
      "s3_key": "username/example2.pdf",
      "status": "success",
      "message": "Upload confirmed"
    }
  ]
}
```

### 5. Confirm Single Upload (Backward Compatibility)

Confirms that a single file has been successfully uploaded to S3.

#### Request

```
POST /api/files/confirm_upload/
```

#### Request Body

```json
{
  "s3_key": "username/example.jpg"
}
```

#### Response

```json
{
  "message": "Upload confirmed successfully"
}
```

### 6. Download File

Downloads a file from S3.

#### Request

```
GET /api/files/{file_identifier}/download_file/
```

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A MongoDB ObjectId
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

#### Response

The file content with appropriate headers for download.

### 7. Generate Download Presigned URL

Generates a presigned URL for downloading a file directly from S3.

#### Request

```
GET /api/files/{file_identifier}/download_presigned_url/
```

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A MongoDB ObjectId
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

#### Response

```json
{
  "presigned_url": "https://bucket-name.s3.amazonaws.com/...",
  "file_name": "example.jpg"
}
```

### 8. Delete File

Deletes a file from S3 and removes its metadata from the database.

#### Request

```
DELETE /api/files/
```

#### Request Body

```json
{
  "s3_key": "username/example.jpg"
}
```

#### Response

```json
{
  "message": "File deleted successfully."
}
```

### 9. Rename File

Renames a file in S3 and updates its metadata in the database.

#### Request

```
POST /api/files/rename/
```

#### Request Body

```json
{
  "s3_key": "username/example.jpg",
  "new_filename": "new_example.jpg"
}
```

#### Response

```json
{
  "message": "File renamed successfully.",
  "new_s3_key": "username/new_example.jpg",
  "new_filename": "new_example.jpg"
}
```

### 10. Refresh File Metadata

Refreshes the metadata for a file from S3.

#### Request

```
GET /api/files/{file_identifier}/refresh
```

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A MongoDB ObjectId
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

#### Response

```json
{
  "message": "Metadata refreshed",
  "metadata": {
    "tier": "standard",
    "content_type": "image/jpeg",
    "size": 1024000
  }
}
```

### 11. Change File Storage Tier

Changes the storage tier of a file between standard and glacier (archived) storage.

#### Request

```
POST /api/files/{file_identifier}/change_tier/
```

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A MongoDB ObjectId
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

#### Request Body

```json
{
  "target_tier": "standard" or "glacier"
}
```

#### Response (Success - Already in Requested Tier)

```json
{
  "message": "File is already in standard tier",
  "metadata": {
    "tier": "standard",
    "content_type": "image/jpeg",
    "size": 1024000,
    "last_modified": "2023-05-15T14:30:45.123Z"
  }
}
```

#### Response (Success - Changed to Glacier)

```json
{
  "message": "File successfully changed to glacier tier",
  "metadata": {
    "tier": "glacier",
    "content_type": "image/jpeg",
    "size": 1024000,
    "last_modified": "2023-05-15T14:30:45.123Z"
  }
}
```

#### Response (Restoration Required)

```json
{
  "message": "File restoration initiated. Try changing the tier again after restoration is complete."
}
```

Status code: 202 Accepted

#### Error Response (File Not Found)

```json
{
  "error": "File not found"
}
```

Status code: 404 Not Found

#### Error Response (Invalid Request)

```json
{
  "error": "target_tier is required and must be either \"standard\" or \"glacier\"."
}
```

Status code: 400 Bad Request

### 12. Get File Details

Retrieves detailed information about a specific file, even if it only exists in S3 and not in the database.

#### Request

```
GET /api/files/{file_identifier}/details/
```

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

#### Response

```json
{
  "file_name": "example.jpg",
  "simple_url": "https://bucket-url.com/username/example.jpg",
  "metadata": {
    "tier": "standard",
    "size": 1024000,
    "content_type": "image/jpeg",
    "last_modified": "2023-05-15T14:30:45.123Z"
  },
  "upload_complete": "complete",
  "id": "username-example.jpg",
  "s3_key": "username/example.jpg",
  "exists_in_db": true
}
```

#### Error Response (File Not Found)

```json
{
  "error": "File not found in S3"
}
```

## Error Handling

All endpoints return appropriate HTTP status codes and error messages in case of failure:

- `400 Bad Request`: Invalid input parameters
- `401 Unauthorized`: Missing or invalid authentication
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server-side error

Error responses follow this format:

```json
{
  "error": "Error message details"
}
```

## Pagination

The List Files endpoint supports two pagination methods:

1. **Offset-based pagination**: Use `page` and `per_page` parameters
2. **Cursor-based pagination**: Use the `cursor` parameter

For large datasets, cursor-based pagination is recommended as it provides better performance.

## File Storage Tiers

The API supports different storage tiers for files:

- `standard`: Regular S3 storage with immediate access
- `glacier`: Archived storage with delayed access (requires restoration)

When uploading files, you can specify the desired tier in the request.

## Implementation Notes

### File Upload Process

1. Call `/api/files/upload/` to get presigned URLs for the files
2. Upload the files directly to S3 using the presigned URLs
3. Call `/api/files/confirm_uploads/` to confirm the uploads

### Handling Glacier Files

Files stored in the Glacier tier require restoration before they can be downloaded:

1. When attempting to download a Glacier file, the API will return a 202 status code if the file is being restored
2. Check the file's metadata periodically to see if the restoration is complete
3. Once restored, the file can be downloaded normally for a limited time

### Metadata Caching

The List Files endpoint caches S3 metadata to improve performance:

- By default, cached metadata is used if available and not expired
- To bypass the cache and fetch fresh metadata, set `use_cache=false` in the request 