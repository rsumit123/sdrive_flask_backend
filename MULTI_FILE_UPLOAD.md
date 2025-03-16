# Multi-File Upload Implementation

This document explains the implementation of multi-file upload functionality for the S3 Drive Flask backend.

## Overview

The implementation allows users to upload multiple files simultaneously to S3 using presigned URLs. The process is efficient and asynchronous, with parallel processing of file uploads.

## Backend Changes

### 1. Modified Endpoints

#### `/api/files/upload/` (POST)
- Now supports both single file and multiple file uploads
- Processes files in parallel using ThreadPoolExecutor
- Returns presigned URLs for each file
- Handles errors gracefully, providing detailed feedback

#### `/api/files/confirm_uploads/` (POST)
- New endpoint to confirm multiple file uploads at once
- Accepts an array of S3 keys
- Returns status for each confirmation

#### `/api/files/confirm_upload/` (POST)
- Original endpoint maintained for backward compatibility
- Confirms a single file upload

### 2. Implementation Details

- **Parallel Processing**: Uses Python's `concurrent.futures.ThreadPoolExecutor` to process multiple files concurrently
- **Error Handling**: Each file is processed independently, so failures don't affect other uploads
- **Response Format**: Returns detailed information about successful and failed uploads
- **Backward Compatibility**: Maintains support for the original single-file upload format

## Frontend Integration

A React example component is provided in `frontend_example.js` that demonstrates how to:

1. Select multiple files
2. Prepare file metadata
3. Request presigned URLs from the backend
4. Upload files directly to S3 using the presigned URLs
5. Track upload progress for each file
6. Confirm uploads with the backend

## API Usage

### Multi-File Upload Request

```json
POST /api/files/upload/
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

### Multi-File Upload Response

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

### Confirm Multiple Uploads Request

```json
POST /api/files/confirm_uploads/
{
  "s3_keys": [
    "username/example1.jpg",
    "username/example2.pdf"
  ]
}
```

### Confirm Multiple Uploads Response

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

## Performance Considerations

- The backend uses a thread pool with a maximum of 10 workers to prevent overwhelming the server
- Each file is processed independently, allowing for efficient parallel processing
- The frontend example uses Promise.all to handle multiple uploads in parallel
- Progress tracking is implemented for each file individually

## Error Handling

- If a file exceeds the size limit (800MB), it will be rejected with an appropriate error message
- If a file fails to upload, the error will be reported in the response
- The frontend example handles errors gracefully, displaying them to the user

## Limitations

- The maximum file size is still 800MB per file
- The maximum number of concurrent uploads is limited to 10 to prevent overwhelming the server
- The presigned URLs expire after 1 hour 